"""Define the provider-neutral result returned by every LLM adapter.

The DTO keeps generated text and safe telemetry independent of SDK response
classes so agents, evaluators, and observability code consume one stable JSON
contract regardless of the configured provider.
"""

from collections.abc import Mapping
from types import MappingProxyType

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_serializer,
    field_validator,
)


def _freeze_json(value: JsonValue) -> object:
    """Recursively freeze JSON containers so metadata cannot mutate later."""

    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> JsonValue:
    """Convert frozen metadata containers back to standard JSON structures."""

    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value  # type: ignore[return-value]


class GenerationResult(BaseModel):
    """Carry generated text and optional telemetry across provider boundaries.

    The immutable contract prevents downstream code from altering evidence used
    for auditing, evaluation, and cost accounting after a provider returns it.
    SDK-specific response objects must be reduced to these portable fields by
    the adapter that owns them. Deep immutability also makes one result safe to
    hand between concurrent tasks without synchronization or shared mutations.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

    text: str = Field(
        min_length=1,
        description="Generated provider text consumed by an application agent.",
    )
    model_name: str | None = Field(
        default=None,
        min_length=1,
        description="Provider-reported model identifier when available.",
    )
    input_tokens: int | None = Field(
        default=None,
        ge=0,
        description="Provider-reported input token count when available.",
    )
    output_tokens: int | None = Field(
        default=None,
        ge=0,
        description="Provider-reported output token count when available.",
    )
    total_tokens: int | None = Field(
        default=None,
        ge=0,
        description="Total known tokens when both component counts are available.",
    )
    latency_ms: float | None = Field(
        default=None,
        ge=0.0,
        description="End-to-end provider request latency in milliseconds.",
    )
    request_id: str | None = Field(
        default=None,
        min_length=1,
        description="Provider request identifier used for operational tracing.",
    )
    stop_reason: str | None = Field(
        default=None,
        min_length=1,
        description="Provider-reported reason generation stopped.",
    )
    provider: str = Field(
        min_length=1,
        description="Provider-neutral name of the adapter that produced the result.",
    )
    metadata: Mapping[str, JsonValue] | None = Field(
        default=None,
        description="Optional immutable JSON telemetry not covered by core fields.",
    )

    @field_validator("metadata")
    @classmethod
    def freeze_metadata(
        cls,
        value: Mapping[str, JsonValue] | None,
    ) -> Mapping[str, JsonValue] | None:
        """Defensively copy and deeply freeze optional metadata containers."""

        if value is None:
            return None
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )

    @field_serializer("metadata")
    def serialize_metadata(
        self,
        value: Mapping[str, JsonValue] | None,
    ) -> JsonValue:
        """Emit ordinary JSON containers without exposing mutable model state."""

        if value is None:
            return None
        return _thaw_json(value)
