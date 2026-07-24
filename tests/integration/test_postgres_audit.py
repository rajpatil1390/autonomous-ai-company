"""Integration coverage for PostgreSQL audit storage and its composition."""

import asyncio
import os
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import psycopg
import pytest
from pydantic import ValidationError
from psycopg.types.json import Jsonb
from testcontainers.postgres import PostgresContainer

from autonomous_ai_company.audit.audit_logger import (
    AuditLogger,
    InMemoryAuditStorage,
)
from autonomous_ai_company.audit.postgres_storage import PostgresAuditStorage
from autonomous_ai_company.bootstrap import build_finance_agent
from autonomous_ai_company.config import Settings
from autonomous_ai_company.exceptions import AuditError
from autonomous_ai_company.schemas.audit import AuditEvent, AuditEventType


SCHEMA_PATH = (
    Path(__file__).parents[2] / "src" / "autonomous_ai_company" / "audit" / "schema.sql"
)


def configured_settings(**postgres: object) -> Settings:
    """Return complete application configuration with optional DB overrides."""

    return Settings(
        ANTHROPIC_API_KEY="test-api-key",
        MODEL_NAME="test-model",
        TEMPERATURE=0.0,
        MAX_TOKENS=100,
        LOG_LEVEL="INFO",
        _env_file=None,
        **postgres,
    )


def audit_event(
    *,
    run_id: str = "run-1",
    timestamp: datetime | None = None,
    event_type: AuditEventType = AuditEventType.START,
    metadata: dict[str, object] | None = None,
) -> AuditEvent:
    """Return a validated event with nested JSON data."""

    return AuditEvent(
        run_id=run_id,
        timestamp=timestamp or datetime(2026, 1, 1, tzinfo=timezone.utc),
        event_type=event_type,
        component="integration-test",
        payload={"dataset_size": 2, "nested": {"values": [1, 2]}},
        metadata=metadata,
    )


def mocked_database(
    rows: list[tuple[object, ...]] | None = None,
) -> tuple[Mock, MagicMock, MagicMock]:
    """Return a connection factory and context-managed connection/cursor."""

    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchall.return_value = rows or []
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value = cursor
    factory = Mock(return_value=connection)
    return factory, connection, cursor


def test_storage_requires_dsn_or_complete_connection_parameters() -> None:
    """Partial direct construction must fail before using ambient credentials."""

    with pytest.raises(ValueError, match="conninfo or complete parameters"):
        PostgresAuditStorage(host="localhost")


def test_insert_uses_jsonb_and_exposes_only_append_sql() -> None:
    """The adapter should serialize nested immutable values into one insert."""

    factory, connection, cursor = mocked_database()
    storage = PostgresAuditStorage(
        conninfo="postgresql://isolated-test",
        connection_factory=factory,  # type: ignore[arg-type]
    )
    event = audit_event(metadata={"dataset_size": 2})

    storage.append(event)

    factory.assert_called_once_with(
        "postgresql://isolated-test",
        connect_timeout=5,
    )
    connection.cursor.assert_called_once_with()
    sql, values = cursor.execute.call_args.args
    normalized_sql = " ".join(sql.split()).upper()
    assert normalized_sql.startswith("INSERT INTO AUDIT_EVENTS")
    assert "UPDATE" not in normalized_sql
    assert "DELETE" not in normalized_sql
    assert values[:4] == (
        event.run_id,
        event.timestamp,
        event.event_type.value,
        event.component,
    )
    assert isinstance(values[4], Jsonb)
    assert values[4].obj == {
        "dataset_size": 2,
        "nested": {"values": [1, 2]},
    }
    assert isinstance(values[5], Jsonb)
    assert values[5].obj == {"dataset_size": 2}
    assert not hasattr(storage, "update")
    assert not hasattr(storage, "delete")


def test_insert_preserves_null_metadata() -> None:
    """Absent optional metadata must remain SQL NULL rather than fabricated JSON."""

    factory, _, cursor = mocked_database()
    storage = PostgresAuditStorage(
        host="localhost",
        port=5432,
        database="audit_test",
        user="audit_user",
        password="test-password",
        connection_factory=factory,  # type: ignore[arg-type]
    )

    storage.append(audit_event())

    factory.assert_called_once_with(
        "",
        connect_timeout=5,
        host="localhost",
        port=5432,
        dbname="audit_test",
        user="audit_user",
        password="test-password",
    )
    assert cursor.execute.call_args.args[1][5] is None


def test_snapshot_rebuilds_deeply_immutable_events_in_database_order() -> None:
    """Rows should retain SQL timestamp/id ordering and schema guarantees."""

    first_timestamp = datetime(
        2026,
        1,
        1,
        5,
        30,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )
    second_timestamp = datetime(2026, 1, 2, tzinfo=timezone.utc)
    rows = [
        (
            2,
            "run-1",
            first_timestamp,
            "start",
            "finance",
            {"dataset_size": 2},
            {"dataset_size": 2},
        ),
        (
            3,
            "run-1",
            second_timestamp,
            "finish",
            "finance",
            {"status": "completed"},
            None,
        ),
    ]
    factory, _, cursor = mocked_database(rows)
    storage = PostgresAuditStorage(
        conninfo="postgresql://isolated-test",
        connection_factory=factory,  # type: ignore[arg-type]
    )

    events = storage.snapshot()

    normalized_sql = " ".join(cursor.execute.call_args.args[0].split()).upper()
    assert "ORDER BY TIMESTAMP ASC, ID ASC" in normalized_sql
    assert tuple(event.event_type for event in events) == (
        AuditEventType.START,
        AuditEventType.FINISH,
    )
    assert events[0].timestamp == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert events[0].model_dump(mode="json")["metadata"] == {"dataset_size": 2}
    with pytest.raises(TypeError):
        events[0].payload["new"] = "forbidden"  # type: ignore[index]


def test_snapshot_rejects_invalid_database_timestamp() -> None:
    """Malformed database rows must not bypass the AuditEvent contract."""

    rows = [(1, "run-1", "not-a-date", "start", "finance", {}, None)]
    factory, _, _ = mocked_database(rows)
    storage = PostgresAuditStorage(
        conninfo="postgresql://isolated-test",
        connection_factory=factory,  # type: ignore[arg-type]
    )

    with pytest.raises(TypeError, match="timestamp"):
        storage.snapshot()


@pytest.mark.parametrize("operation", ["append", "snapshot"])
def test_connection_failures_remain_observable(operation: str) -> None:
    """Connection errors should propagate to the AuditLogger translation boundary."""

    failure = psycopg.OperationalError("isolated database unavailable")
    factory = Mock(side_effect=failure)
    storage = PostgresAuditStorage(
        conninfo="postgresql://unavailable-test",
        connection_factory=factory,  # type: ignore[arg-type]
    )

    if operation == "append":
        with pytest.raises(psycopg.OperationalError) as captured:
            storage.append(audit_event())
    else:
        with pytest.raises(psycopg.OperationalError) as captured:
            storage.snapshot()

    assert captured.value is failure


def test_audit_logger_wraps_postgres_failure_without_importing_driver() -> None:
    """Caller-facing storage failures should remain the existing AuditError."""

    failure = psycopg.OperationalError("isolated database unavailable")
    storage = PostgresAuditStorage(
        conninfo="postgresql://unavailable-test",
        connection_factory=Mock(side_effect=failure),  # type: ignore[arg-type]
    )
    logger = AuditLogger(storage=storage)

    with pytest.raises(AuditError) as captured:
        logger.log_start("run-1", "finance", {"dataset_size": 2})

    assert captured.value.__cause__ is failure


def test_storage_remains_usable_from_async_application_execution() -> None:
    """The synchronous protocol can be isolated from an async loop in a worker."""

    factory, _, _ = mocked_database()
    storage = PostgresAuditStorage(
        conninfo="postgresql://isolated-test",
        connection_factory=factory,  # type: ignore[arg-type]
    )
    logger = AuditLogger(storage=storage)

    async def record() -> AuditEvent:
        return await asyncio.to_thread(
            logger.log_start,
            "async-run",
            "finance",
            {"dataset_size": 2},
        )

    event = asyncio.run(record())

    assert event.run_id == "async-run"
    factory.assert_called_once()


def test_postgres_configuration_is_optional_but_complete_when_enabled() -> None:
    """Disabled settings use defaults while enabled partial settings fail."""

    disabled = configured_settings()

    with pytest.raises(ValidationError, match="POSTGRES_PORT"):
        configured_settings(
            POSTGRES_ENABLED=True,
            POSTGRES_HOST="localhost",
        )

    enabled = configured_settings(
        POSTGRES_ENABLED=True,
        POSTGRES_HOST="localhost",
        POSTGRES_PORT=5432,
        POSTGRES_DATABASE="audit_test",
        POSTGRES_USER="audit_user",
        POSTGRES_PASSWORD="test-password",
    )

    assert disabled.postgres_enabled is False
    assert disabled.postgres_host is None
    assert enabled.postgres_enabled is True
    assert enabled.postgres_password is not None
    assert "test-password" not in repr(enabled)


def test_invalid_postgres_port_is_rejected() -> None:
    """Invalid network configuration should fail before bootstrap construction."""

    with pytest.raises(ValidationError):
        configured_settings(
            POSTGRES_ENABLED=True,
            POSTGRES_HOST="localhost",
            POSTGRES_PORT=70_000,
            POSTGRES_DATABASE="audit_test",
            POSTGRES_USER="audit_user",
            POSTGRES_PASSWORD="test-password",
        )


@pytest.mark.parametrize("postgres_enabled", [False, True])
def test_bootstrap_injects_configured_audit_storage(
    postgres_enabled: bool,
) -> None:
    """Composition should select exactly one backend without changing agents."""

    postgres_values: dict[str, object] = {}
    if postgres_enabled:
        postgres_values = {
            "POSTGRES_ENABLED": True,
            "POSTGRES_HOST": "localhost",
            "POSTGRES_PORT": 5432,
            "POSTGRES_DATABASE": "audit_test",
            "POSTGRES_USER": "audit_user",
            "POSTGRES_PASSWORD": "test-password",
        }
    settings = configured_settings(**postgres_values)
    with (
        patch(
            "autonomous_ai_company.bootstrap.get_settings",
            return_value=settings,
        ),
        patch(
            "autonomous_ai_company.llm.claude_client.AsyncAnthropic",
            return_value=Mock(),
        ),
    ):
        agent = build_finance_agent()

    storage = agent._audit_logger._storage
    if postgres_enabled:
        assert isinstance(storage, PostgresAuditStorage)
    else:
        assert isinstance(storage, InMemoryAuditStorage)


def test_schema_defines_only_append_table_and_required_indexes() -> None:
    """The SQL artifact should contain the requested JSONB audit table only."""

    schema = SCHEMA_PATH.read_text(encoding="utf-8").upper()

    assert "CREATE TABLE IF NOT EXISTS AUDIT_EVENTS" in schema
    assert "PAYLOAD JSONB NOT NULL" in schema
    assert "METADATA JSONB" in schema
    assert "AUDIT_EVENTS_RUN_ID_IDX" in schema
    assert "AUDIT_EVENTS_TIMESTAMP_IDX" in schema
    assert "UPDATE " not in schema
    assert "DELETE " not in schema


@pytest.fixture(scope="module")
def real_postgres_dsn() -> Iterator[str]:
    """Prefer Testcontainers and fall back only to an explicit isolated DSN."""

    fallback_dsn = os.getenv("POSTGRES_TEST_DSN")
    if fallback_dsn:
        yield fallback_dsn
        return

    try:
        container = PostgresContainer("postgres:16-alpine", driver=None)
        container.start()
    except Exception as error:
        pytest.skip(
            "Real PostgreSQL integration pending: Docker unavailable and "
            f"POSTGRES_TEST_DSN unset ({type(error).__name__})"
        )
    try:
        yield container.get_connection_url(driver=None)
    finally:
        container.stop()


def test_real_postgres_insert_ordering_json_and_async_round_trip(
    real_postgres_dsn: str,
) -> None:
    """Verify the complete storage contract against isolated PostgreSQL."""

    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with psycopg.connect(real_postgres_dsn) as connection:
        connection.execute(schema)
        connection.execute("TRUNCATE audit_events RESTART IDENTITY")

    storage = PostgresAuditStorage(conninfo=real_postgres_dsn)
    logger = AuditLogger(storage=storage)
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)
    second = first + timedelta(seconds=1)
    first_event = audit_event(timestamp=first, metadata={"dataset_size": 2})
    second_event = audit_event(
        timestamp=second,
        event_type=AuditEventType.FINISH,
    )

    async def append_events() -> None:
        await asyncio.to_thread(storage.append, second_event)
        await asyncio.to_thread(storage.append, first_event)

    asyncio.run(append_events())
    events = logger.get_events()

    assert events == (first_event, second_event)
    assert events[0].model_dump(mode="json")["payload"] == {
        "dataset_size": 2,
        "nested": {"values": [1, 2]},
    }
