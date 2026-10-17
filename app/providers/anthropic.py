"""Anthropic chat provider implementation."""

from typing import Any, Dict, List, Optional
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_anthropic import ChatAnthropic

from app.config import get_settings
from app.core.exceptions import ProviderUnavailableError
from app.core.logging import logger
from app.providers.base import BaseChatProvider

settings = get_settings()


class AnthropicChatProvider(BaseChatProvider):
    """Anthropic Claude chat model provider."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY

    def get_chat_model(
        self,
        model_name: Optional[str] = None,
        temperature: float = 0.2,
        streaming: bool = True,
        **kwargs: Any,
    ) -> BaseChatModel:
        if not self.api_key:
            raise ProviderUnavailableError("Anthropic API key is missing. Set ANTHROPIC_API_KEY in .env.")

        model = model_name or "claude-3-5-sonnet-20241022"
        try:
            return ChatAnthropic(
                api_key=self.api_key,
                model=model,
                temperature=temperature,
                streaming=streaming,
                **kwargs,
            )
        except Exception as e:
            logger.error(f"Failed to initialize ChatAnthropic with model '{model}': {e}")
            raise ProviderUnavailableError(f"Anthropic chat provider error: {str(e)}")

    async def check_health(self) -> Dict[str, Any]:
        if not self.api_key:
            return {
                "status": "unconfigured",
                "available": False,
                "message": "Anthropic API key not set.",
            }
        return {"status": "configured", "available": True}

    async def list_available_models(self) -> List[str]:
        return [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
        ]
