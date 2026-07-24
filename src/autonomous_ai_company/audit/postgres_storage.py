"""Persist validated audit events through the PostgreSQL adapter boundary."""

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg import Connection
from psycopg.types.json import Jsonb

from autonomous_ai_company.schemas.audit import AuditEvent, AuditEventType


_INSERT_EVENT = """
    INSERT INTO audit_events (
        run_id,
        timestamp,
        event_type,
        component,
        payload,
        metadata
    )
    VALUES (%s, %s, %s, %s, %s, %s)
"""

_SELECT_EVENTS = """
    SELECT
        id,
        run_id,
        timestamp,
        event_type,
        component,
        payload,
        metadata
    FROM audit_events
    ORDER BY timestamp ASC, id ASC
"""

type ConnectionFactory = Callable[..., Connection[Any]]


class PostgresAuditStorage:
    """Implement append-only ``AuditStorage`` operations with PostgreSQL.

    The adapter creates no tables and owns no migration policy. Each call uses
    an independent connection, so instances retain no mutable request or cursor
    state and remain reusable by concurrent application workflows.
    """

    def __init__(
        self,
        *,
        conninfo: str = "",
        host: str | None = None,
        port: int | None = None,
        database: str | None = None,
        user: str | None = None,
        password: str | None = None,
        connection_factory: ConnectionFactory = psycopg.connect,
    ) -> None:
        """Retain connection configuration without opening a global session."""

        parameters = {
            "host": host,
            "port": port,
            "dbname": database,
            "user": user,
            "password": password,
        }
        if not conninfo and any(value is None for value in parameters.values()):
            raise ValueError(
                "PostgresAuditStorage requires conninfo or complete parameters"
            )
        self._conninfo = conninfo
        self._parameters = {
            name: value for name, value in parameters.items() if value is not None
        }
        self._connection_factory = connection_factory

    def _connect(self) -> Connection[Any]:
        """Open one caller-owned connection with a bounded startup wait."""

        return self._connection_factory(
            self._conninfo,
            connect_timeout=5,
            **self._parameters,
        )

    def append(self, event: AuditEvent) -> None:
        """Insert one immutable event without update or delete capabilities."""

        serialized = event.model_dump(mode="json")
        metadata = serialized["metadata"]
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    _INSERT_EVENT,
                    (
                        event.run_id,
                        event.timestamp,
                        event.event_type.value,
                        event.component,
                        Jsonb(serialized["payload"]),
                        Jsonb(metadata) if metadata is not None else None,
                    ),
                )

    def snapshot(self) -> tuple[AuditEvent, ...]:
        """Return all stored events in stable timestamp and insertion order."""

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(_SELECT_EVENTS)
                rows = cursor.fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    @staticmethod
    def _event_from_row(row: tuple[object, ...]) -> AuditEvent:
        """Rebuild the provider-independent immutable schema from one DB row."""

        timestamp = row[2]
        if not isinstance(timestamp, datetime):
            raise TypeError("audit timestamp returned by PostgreSQL is invalid")
        return AuditEvent(
            run_id=str(row[1]),
            timestamp=timestamp.astimezone(timezone.utc),
            event_type=AuditEventType(str(row[3])),
            component=str(row[4]),
            payload=row[5],  # type: ignore[arg-type]
            metadata=row[6],  # type: ignore[arg-type]
        )
