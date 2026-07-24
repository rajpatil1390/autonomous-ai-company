"""No-network tests for the xAI Grok compatibility adapter."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

from pydantic import SecretStr

from autonomous_ai_company.config import Settings
from autonomous_ai_company.llm.grok_client import GrokClient, XAI_BASE_URL


def grok_settings() -> Mock:
    """Return centralized xAI values without reading the environment."""

    settings = Mock(spec=Settings)
    settings.xai_api_key = SecretStr("xai-key")
    settings.model_grok = "grok-model"
    settings.max_tokens = 100
    settings.temperature = 0.3
    return settings


def test_grok_reuses_openai_compatible_transport_and_telemetry() -> None:
    """Only endpoint, credential, model, and provider label should differ."""

    settings = grok_settings()
    sdk_client = Mock()
    sdk_client.chat.completions.create = AsyncMock(
        return_value=Mock(
            choices=[Mock(message=Mock(content="Grok answer"), finish_reason="stop")],
            model="grok-model",
            id="grok-request",
            _request_id=None,
            usage=None,
            system_fingerprint=None,
        )
    )
    with patch(
        "autonomous_ai_company.llm.openai_client.AsyncOpenAI",
        return_value=sdk_client,
    ) as sdk:
        client = GrokClient(
            settings=settings,
            timeout_seconds=8.0,
            max_retries=1,
        )
        result = asyncio.run(client.generate("Explain"))

    sdk.assert_called_once_with(
        api_key="xai-key",
        max_retries=1,
        base_url=XAI_BASE_URL,
        timeout=8.0,
    )
    assert client._settings is settings
    assert result.provider == "grok"
    assert result.text == "Grok answer"
    assert result.input_tokens is None
    assert result.total_tokens is None


def test_grok_loads_centralized_settings_when_not_injected() -> None:
    """Direct construction should retain the standard configuration boundary."""

    settings = grok_settings()
    with (
        patch(
            "autonomous_ai_company.llm.grok_client.get_settings",
            return_value=settings,
        ) as loader,
        patch("autonomous_ai_company.llm.openai_client.AsyncOpenAI"),
    ):
        GrokClient()

    loader.assert_called_once_with()
