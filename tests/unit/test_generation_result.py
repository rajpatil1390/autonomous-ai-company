"""Unit tests for the provider-neutral generation result contract."""

import json

import pytest
from pydantic import ValidationError

from autonomous_ai_company.llm.generation_result import GenerationResult


def test_generation_result_is_json_serializable_with_telemetry() -> None:
    """Complete provider telemetry should round-trip without SDK objects."""

    result = GenerationResult(
        text="Generated analysis",
        model_name="model-1",
        input_tokens=100,
        output_tokens=25,
        total_tokens=125,
        latency_ms=42.5,
        request_id="request-1",
        stop_reason="end_turn",
        provider="anthropic",
        metadata={"cache": {"hits": [1, 2]}, "region": "us-east"},
    )

    serialized = result.model_dump_json()
    decoded = json.loads(serialized)

    assert decoded == {
        "text": "Generated analysis",
        "model_name": "model-1",
        "input_tokens": 100,
        "output_tokens": 25,
        "total_tokens": 125,
        "latency_ms": 42.5,
        "request_id": "request-1",
        "stop_reason": "end_turn",
        "provider": "anthropic",
        "metadata": {
            "cache": {"hits": [1, 2]},
            "region": "us-east",
        },
    }
    assert GenerationResult.model_validate_json(serialized) == result


def test_generation_result_is_deeply_immutable() -> None:
    """Neither DTO fields nor nested metadata may change after creation."""

    result = GenerationResult(
        text="Generated analysis",
        provider="fake",
        metadata={"nested": {"items": [1, 2]}},
    )

    with pytest.raises(ValidationError):
        result.text = "changed"
    with pytest.raises(TypeError):
        result.metadata["new"] = "value"  # type: ignore[index]

    nested = result.metadata["nested"]  # type: ignore[index]
    with pytest.raises(TypeError):
        nested["new"] = "value"  # type: ignore[index]
    assert nested["items"] == (1, 2)  # type: ignore[index]


def test_generation_result_allows_missing_telemetry() -> None:
    """Providers must use None instead of inventing unavailable telemetry."""

    result = GenerationResult(
        text="Generated analysis",
        provider="local",
        metadata=None,
    )

    assert result.model_name is None
    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.total_tokens is None
    assert result.latency_ms is None
    assert result.request_id is None
    assert result.stop_reason is None
    assert result.metadata is None
    assert json.loads(result.model_dump_json())["metadata"] is None
