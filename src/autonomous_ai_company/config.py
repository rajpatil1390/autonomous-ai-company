"""Centralize validated runtime configuration at the application boundary.

Keeping environment access in one independent module prevents infrastructure
details and secrets from being scattered across business logic.
"""

from functools import lru_cache
from typing import Literal

from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from autonomous_ai_company.exceptions import ConfigurationError


class Settings(BaseSettings):
    """Describe and validate configuration before the application uses it.

    Requiring values here makes deployment choices explicit and gives the rest
    of the codebase one typed contract instead of repeated environment lookups.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    llm_provider: Literal[
        "anthropic",
        "openai",
        "grok",
        "ollama",
        "fake",
    ] = Field(
        default="anthropic",
        validation_alias="LLM_PROVIDER",
        description="Provider selected once at the application composition root.",
    )
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="ANTHROPIC_API_KEY",
        description="Anthropic credential required only when Anthropic is selected.",
    )
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
        description="OpenAI credential required only when OpenAI is selected.",
    )
    xai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="XAI_API_KEY",
        description="xAI credential required only when Grok is selected.",
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="OLLAMA_BASE_URL",
        min_length=1,
        description="Base URL of the local or private Ollama HTTP service.",
    )
    model_anthropic: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MODEL_ANTHROPIC", "MODEL_NAME"),
        min_length=1,
        description="Anthropic model; MODEL_NAME remains a legacy alias.",
    )
    model_openai: str | None = Field(
        default=None,
        validation_alias="MODEL_OPENAI",
        min_length=1,
        description="OpenAI model selected independently of application code.",
    )
    model_grok: str | None = Field(
        default=None,
        validation_alias="MODEL_GROK",
        min_length=1,
        description="xAI Grok model selected independently of application code.",
    )
    model_ollama: str | None = Field(
        default=None,
        validation_alias="MODEL_OLLAMA",
        min_length=1,
        description="Ollama model installed in the configured local service.",
    )
    temperature: float = Field(
        validation_alias="TEMPERATURE",
        ge=0.0,
        le=1.0,
        description="Sampling variability constrained to the provider range.",
    )
    max_tokens: int = Field(
        validation_alias="MAX_TOKENS",
        gt=0,
        description="Positive upper bound for generated response tokens.",
    )
    log_level: Literal[
        "CRITICAL",
        "ERROR",
        "WARNING",
        "INFO",
        "DEBUG",
    ] = Field(
        validation_alias="LOG_LEVEL",
        description="Validated logging verbosity chosen at deployment time.",
    )
    checkpointing_enabled: bool = Field(
        default=False,
        validation_alias="CHECKPOINTING_ENABLED",
        description=(
            "Enable graph checkpoints when a checkpointer is injected at startup."
        ),
    )
    postgres_enabled: bool = Field(
        default=False,
        validation_alias="POSTGRES_ENABLED",
        description="Select PostgreSQL rather than process-local audit storage.",
    )
    postgres_host: str | None = Field(
        default=None,
        validation_alias="POSTGRES_HOST",
        min_length=1,
        description="PostgreSQL server hostname supplied by deployment.",
    )
    postgres_port: int | None = Field(
        default=None,
        validation_alias="POSTGRES_PORT",
        ge=1,
        le=65_535,
        description="PostgreSQL server TCP port supplied by deployment.",
    )
    postgres_database: str | None = Field(
        default=None,
        validation_alias="POSTGRES_DATABASE",
        min_length=1,
        description="Database containing the append-only audit table.",
    )
    postgres_user: str | None = Field(
        default=None,
        validation_alias="POSTGRES_USER",
        min_length=1,
        description="Database role used only by the audit adapter.",
    )
    postgres_password: SecretStr | None = Field(
        default=None,
        validation_alias="POSTGRES_PASSWORD",
        description="Database credential hidden from diagnostic representations.",
    )
    jwt_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias="JWT_SECRET_KEY",
        min_length=32,
        description="Deployment-owned secret used to sign access tokens.",
    )
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = Field(
        default="HS256",
        validation_alias="JWT_ALGORITHM",
        description="Allowlisted HMAC algorithm used for JWT signatures.",
    )
    access_token_expire_minutes: int = Field(
        default=30,
        validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES",
        gt=0,
        description="Positive access-token lifetime selected by deployment.",
    )
    mlflow_enabled: bool = Field(
        default=False,
        validation_alias="MLFLOW_ENABLED",
        description="Enable experiment tracking without changing application logic.",
    )
    mlflow_tracking_uri: str | None = Field(
        default=None,
        validation_alias="MLFLOW_TRACKING_URI",
        min_length=1,
        description="MLflow backend URI owned by deployment infrastructure.",
    )
    mlflow_experiment_name: str = Field(
        default="autonomous-ai-company",
        validation_alias="MLFLOW_EXPERIMENT_NAME",
        min_length=1,
        description="Experiment grouping all company workflow runs.",
    )
    mlflow_artifact_location: str | None = Field(
        default=None,
        validation_alias="MLFLOW_ARTIFACT_LOCATION",
        min_length=1,
        description="Optional artifact root assigned when creating the experiment.",
    )
    otel_enabled: bool = Field(
        default=False,
        validation_alias="OTEL_ENABLED",
        description="Enable distributed tracing without changing workflow behavior.",
    )
    otel_service_name: str = Field(
        default="autonomous-ai-company",
        validation_alias="OTEL_SERVICE_NAME",
        min_length=1,
        description="Stable service identity attached to exported spans.",
    )
    otel_exporter: Literal["console", "otlp"] = Field(
        default="console",
        validation_alias="OTEL_EXPORTER",
        description="Allowlisted trace exporter selected by deployment.",
    )
    otel_otlp_endpoint: str | None = Field(
        default=None,
        validation_alias="OTEL_OTLP_ENDPOINT",
        min_length=1,
        description="Optional OTLP/HTTP collector endpoint supplied by deployment.",
    )
    metrics_enabled: bool = Field(
        default=False,
        validation_alias="METRICS_ENABLED",
        description="Enable Prometheus metrics without changing application logic.",
    )
    metrics_namespace: str = Field(
        default="autonomous_ai_company",
        validation_alias="METRICS_NAMESPACE",
        pattern=r"^[a-zA-Z_:][a-zA-Z0-9_:]*$",
        description="Stable prefix separating this application's metric names.",
    )
    metrics_subsystem: str = Field(
        default="",
        validation_alias="METRICS_SUBSYSTEM",
        pattern=r"^(?:[a-zA-Z_:][a-zA-Z0-9_:]*)?$",
        description="Optional bounded subsystem prefix for deployed metrics.",
    )

    @property
    def model_name(self) -> str:
        """Return the model belonging to the selected provider.

        This compatibility property preserves the original Claude adapter API
        while keeping each provider's deployment setting explicit.
        """

        model_by_provider = {
            "anthropic": self.model_anthropic,
            "openai": self.model_openai,
            "grok": self.model_grok,
            "ollama": self.model_ollama,
            "fake": "fake",
        }
        model_name = model_by_provider[self.llm_provider]
        assert model_name is not None
        return model_name

    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_base_url(cls, value: str) -> str:
        """Accept only explicit HTTP(S) Ollama endpoints without trailing slashes."""

        normalized = value.rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("OLLAMA_BASE_URL must use http:// or https://")
        return normalized

    @model_validator(mode="after")
    def require_selected_provider_configuration(self) -> "Settings":
        """Require only the credential and model used by the selected adapter."""

        if self.llm_provider == "fake":
            return self
        model_by_provider = {
            "anthropic": self.model_anthropic,
            "openai": self.model_openai,
            "grok": self.model_grok,
            "ollama": self.model_ollama,
        }
        credential_by_provider = {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "grok": self.xai_api_key,
            "ollama": True,
        }
        missing: list[str] = []
        if model_by_provider[self.llm_provider] is None:
            missing.append(f"MODEL_{self.llm_provider.upper()}")
        if credential_by_provider[self.llm_provider] is None:
            credential_name = {
                "anthropic": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "grok": "XAI_API_KEY",
            }[self.llm_provider]
            missing.append(credential_name)
        if missing:
            names = ", ".join(missing)
            raise ValueError(
                f"Provider '{self.llm_provider}' requires configuration: {names}"
            )
        return self

    @model_validator(mode="after")
    def require_otlp_endpoint(self) -> "Settings":
        """Require an endpoint only for an enabled OTLP exporter."""

        if (
            self.otel_enabled
            and self.otel_exporter == "otlp"
            and self.otel_otlp_endpoint is None
        ):
            raise ValueError("OTEL_OTLP_ENDPOINT is required for the OTLP exporter")
        return self

    @model_validator(mode="after")
    def require_enabled_mlflow_configuration(self) -> "Settings":
        """Require a tracking backend only when MLflow is enabled."""

        if self.mlflow_enabled and self.mlflow_tracking_uri is None:
            raise ValueError("MLFLOW_TRACKING_URI is required when MLflow is enabled")
        return self

    @model_validator(mode="after")
    def require_enabled_postgres_configuration(self) -> "Settings":
        """Require a complete PostgreSQL connection only when it is enabled."""

        if not self.postgres_enabled:
            return self
        required_values = {
            "POSTGRES_HOST": self.postgres_host,
            "POSTGRES_PORT": self.postgres_port,
            "POSTGRES_DATABASE": self.postgres_database,
            "POSTGRES_USER": self.postgres_user,
            "POSTGRES_PASSWORD": self.postgres_password,
        }
        missing = [name for name, value in required_values.items() if value is None]
        if missing:
            names = ", ".join(missing)
            raise ValueError(f"PostgreSQL audit storage requires: {names}")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one validated settings object for consistent process-wide use.

    Configuration is immutable in a running deployment, so caching avoids
    reparsing the environment while giving tests an explicit cache to clear.
    """

    try:
        return Settings()
    except ValidationError as error:
        raise ConfigurationError("Runtime configuration is invalid") from error
