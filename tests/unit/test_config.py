"""Tests for the environment-backed configuration boundary."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from autonomous_ai_company.config import Settings, get_settings
from autonomous_ai_company.exceptions import ConfigurationError


ENVIRONMENT_VARIABLES = (
    "LLM_PROVIDER",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "XAI_API_KEY",
    "OLLAMA_BASE_URL",
    "MODEL_NAME",
    "MODEL_ANTHROPIC",
    "MODEL_OPENAI",
    "MODEL_GROK",
    "MODEL_OLLAMA",
    "TEMPERATURE",
    "MAX_TOKENS",
    "LOG_LEVEL",
)

VALID_ENVIRONMENT = {
    "ANTHROPIC_API_KEY": "test-api-key",
    "MODEL_NAME": "test-model",
    "TEMPERATURE": "0.25",
    "MAX_TOKENS": "2048",
    "LOG_LEVEL": "INFO",
}


@pytest.fixture(autouse=True)
def isolated_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    """Prevent a developer's environment or cache from affecting test results."""

    monkeypatch.chdir(tmp_path)
    for variable in ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    get_settings.cache_clear()

    yield

    get_settings.cache_clear()


def set_valid_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a complete deployment configuration for focused tests."""

    for variable, value in VALID_ENVIRONMENT.items():
        monkeypatch.setenv(variable, value)


def test_settings_loads_and_converts_environment_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment strings should become the declared runtime types."""

    set_valid_environment(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.anthropic_api_key.get_secret_value() == "test-api-key"
    assert settings.model_name == "test-model"
    assert settings.temperature == 0.25
    assert settings.max_tokens == 2048
    assert settings.log_level == "INFO"
    assert settings.llm_provider == "anthropic"
    assert settings.model_anthropic == "test-model"


def test_settings_requires_every_configuration_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup should fail loudly when deployment configuration is incomplete."""

    set_valid_environment(monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("variable", "invalid_value"),
    [
        ("TEMPERATURE", "1.1"),
        ("MAX_TOKENS", "0"),
        ("LOG_LEVEL", "VERBOSE"),
    ],
)
def test_settings_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    invalid_value: str,
) -> None:
    """Invalid deployment values should be rejected before business code runs."""

    set_valid_environment(monkeypatch)
    monkeypatch.setenv(variable, invalid_value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_api_key_is_hidden_from_settings_representation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Diagnostic representations should not accidentally disclose credentials."""

    set_valid_environment(monkeypatch)

    settings = Settings(_env_file=None)

    assert "test-api-key" not in repr(settings)


def test_get_settings_returns_the_cached_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Callers should share one validated configuration during a process run."""

    set_valid_environment(monkeypatch)

    first = get_settings()
    second = get_settings()

    assert first is second


def test_get_settings_translates_validation_failure_with_cause() -> None:
    """The application boundary should hide Pydantic without losing its trace."""

    with pytest.raises(ConfigurationError) as captured:
        get_settings()

    assert isinstance(captured.value.__cause__, ValidationError)


@pytest.mark.parametrize(
    ("provider", "credential_name", "model_name"),
    [
        ("anthropic", "ANTHROPIC_API_KEY", "MODEL_ANTHROPIC"),
        ("openai", "OPENAI_API_KEY", "MODEL_OPENAI"),
        ("grok", "XAI_API_KEY", "MODEL_GROK"),
    ],
)
def test_settings_requires_selected_remote_provider_values(
    provider: str,
    credential_name: str,
    model_name: str,
) -> None:
    """Only the selected remote adapter should require its key and model."""

    common = {
        "LLM_PROVIDER": provider,
        "TEMPERATURE": 0.2,
        "MAX_TOKENS": 100,
        "LOG_LEVEL": "INFO",
    }
    with pytest.raises(ValidationError, match=model_name):
        Settings.model_validate(common)

    with pytest.raises(ValidationError, match=credential_name):
        Settings.model_validate({**common, model_name: "test-model"})

    settings = Settings.model_validate(
        {
            **common,
            credential_name: "test-key",
            model_name: "test-model",
        }
    )

    assert settings.llm_provider == provider
    assert settings.model_name == "test-model"


def test_settings_supports_ollama_and_fake_without_api_keys() -> None:
    """Local and injected test providers must not require remote credentials."""

    ollama = Settings.model_validate(
        {
            "LLM_PROVIDER": "ollama",
            "MODEL_OLLAMA": "llama-test",
            "OLLAMA_BASE_URL": "http://localhost:11434/",
            "TEMPERATURE": 0.2,
            "MAX_TOKENS": 100,
            "LOG_LEVEL": "INFO",
        }
    )
    fake = Settings.model_validate(
        {
            "LLM_PROVIDER": "fake",
            "TEMPERATURE": 0.2,
            "MAX_TOKENS": 100,
            "LOG_LEVEL": "INFO",
        }
    )

    assert ollama.model_name == "llama-test"
    assert ollama.ollama_base_url == "http://localhost:11434"
    assert fake.model_name == "fake"


def test_settings_rejects_invalid_provider_and_ollama_url() -> None:
    """Deployment typos must fail before any provider construction."""

    common = {"TEMPERATURE": 0.2, "MAX_TOKENS": 100, "LOG_LEVEL": "INFO"}
    with pytest.raises(ValidationError):
        Settings.model_validate({**common, "LLM_PROVIDER": "unknown"})
    with pytest.raises(ValidationError, match="http:// or https://"):
        Settings.model_validate(
            {
                **common,
                "LLM_PROVIDER": "ollama",
                "MODEL_OLLAMA": "llama-test",
                "OLLAMA_BASE_URL": "localhost:11434",
            }
        )
