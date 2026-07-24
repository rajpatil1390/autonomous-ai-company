"""Configure xAI Grok through the shared OpenAI-compatible adapter."""

from autonomous_ai_company.config import Settings, get_settings
from autonomous_ai_company.llm.openai_client import OpenAICompatibleClient


GROK_PROVIDER_NAME = "grok"
XAI_BASE_URL = "https://api.x.ai/v1"


class GrokClient(OpenAICompatibleClient):
    """Bind xAI credentials and endpoint without duplicating SDK behavior."""

    def __init__(
        self,
        timeout_seconds: float | None = None,
        *,
        settings: Settings | None = None,
        max_retries: int = 0,
    ) -> None:
        """Initialize the xAI-compatible client from centralized settings."""

        resolved_settings = settings if settings is not None else get_settings()
        assert resolved_settings.xai_api_key is not None
        assert resolved_settings.model_grok is not None
        self._settings = resolved_settings
        super().__init__(
            api_key=resolved_settings.xai_api_key.get_secret_value(),
            model_name=resolved_settings.model_grok,
            provider_name=GROK_PROVIDER_NAME,
            max_tokens=resolved_settings.max_tokens,
            temperature=resolved_settings.temperature,
            base_url=XAI_BASE_URL,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
