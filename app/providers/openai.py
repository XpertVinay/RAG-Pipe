"""OpenAI and OpenAI-compatible chat and embedding provider."""

from typing import Any, Dict, List, Optional
import httpx
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.config import get_settings
from app.core.exceptions import ProviderUnavailableError
from app.core.logging import logger
from app.providers.base import BaseChatProvider, BaseEmbeddingProvider

settings = get_settings()


class OpenAIChatProvider(BaseChatProvider):
    """OpenAI and OpenAI-compatible chat model provider."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.base_url = base_url or settings.OPENAI_BASE_URL

    def get_chat_model(
        self,
        model_name: Optional[str] = None,
        temperature: float = 0.2,
        streaming: bool = True,
        **kwargs: Any,
    ) -> BaseChatModel:
        if not self.api_key and "api.openai.com" in self.base_url:
            raise ProviderUnavailableError("OpenAI API key is missing. Set OPENAI_API_KEY in .env.")

        model = model_name or "gpt-4o-mini"
        try:
            return ChatOpenAI(
                api_key=self.api_key or "not-needed",
                base_url=self.base_url,
                model=model,
                temperature=temperature,
                streaming=streaming,
                **kwargs,
            )
        except Exception as e:
            logger.error(f"Failed to initialize ChatOpenAI with model '{model}': {e}")
            raise ProviderUnavailableError(f"OpenAI chat provider error: {str(e)}")

    async def check_health(self) -> Dict[str, Any]:
        configured = bool(self.api_key) or "localhost" in self.base_url
        if not configured:
            return {
                "status": "unconfigured",
                "available": False,
                "message": "OpenAI API key not set.",
            }
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(f"{self.base_url.rstrip('/')}/models", headers=headers)
                if resp.status_code == 200:
                    return {"status": "healthy", "available": True, "base_url": self.base_url}
                return {
                    "status": "degraded",
                    "available": False,
                    "message": f"Endpoint responded with HTTP {resp.status_code}",
                }
        except Exception as e:
            return {"status": "unhealthy", "available": False, "message": str(e)}

    async def list_available_models(self) -> List[str]:
        return ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"]


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI embedding provider."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.base_url = base_url or settings.OPENAI_BASE_URL

    def get_embeddings(
        self,
        model_name: Optional[str] = None,
        **kwargs: Any,
    ) -> Embeddings:
        if not self.api_key and "api.openai.com" in self.base_url:
            raise ProviderUnavailableError("OpenAI API key is missing for embeddings.")

        model = model_name or "text-embedding-3-small"
        try:
            return OpenAIEmbeddings(
                api_key=self.api_key or "not-needed",
                base_url=self.base_url,
                model=model,
                **kwargs,
            )
        except Exception as e:
            logger.error(f"Failed to initialize OpenAIEmbeddings with model '{model}': {e}")
            raise ProviderUnavailableError(f"OpenAI embeddings error: {str(e)}")

    async def check_health(self) -> Dict[str, Any]:
        if not self.api_key and "localhost" not in self.base_url:
            return {"status": "unconfigured", "available": False}
        return {"status": "healthy", "available": True}
