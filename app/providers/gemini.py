"""Google Gemini chat and embedding provider implementation."""

from typing import Any, Dict, List, Optional
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from app.config import get_settings
from app.core.exceptions import ProviderUnavailableError
from app.core.logging import logger
from app.providers.base import BaseChatProvider, BaseEmbeddingProvider

settings = get_settings()


class GeminiChatProvider(BaseChatProvider):
    """Google Gemini chat model provider using gemini-2.5-flash as default."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key if api_key is not None else (settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY)

    def get_chat_model(
        self,
        model_name: Optional[str] = None,
        temperature: float = 0.2,
        streaming: bool = True,
        **kwargs: Any,
    ) -> BaseChatModel:
        api_key = kwargs.pop("api_key", None)
        if api_key is None:
            api_key = self.api_key if self.api_key is not None else (settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY)
        if not api_key:
            raise ProviderUnavailableError(
                "Gemini API key is missing. Set GEMINI_API_KEY (or GOOGLE_API_KEY) in .env."
            )

        model = model_name or "gemini-2.5-flash"
        try:
            return ChatGoogleGenerativeAI(
                google_api_key=api_key,
                model=model,
                temperature=temperature,
                streaming=streaming,
                **kwargs,
            )
        except Exception as e:
            logger.error(f"Failed to initialize ChatGoogleGenerativeAI with model '{model}': {e}")
            raise ProviderUnavailableError(f"Gemini chat provider error: {str(e)}")

    async def check_health(self) -> Dict[str, Any]:
        api_key = self.api_key if self.api_key is not None else (settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY)
        if not api_key:
            return {
                "status": "unconfigured",
                "available": False,
                "message": "Gemini API key not set.",
            }
        return {"status": "configured", "available": True}

    async def list_available_models(self) -> List[str]:
        return [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ]


class GeminiEmbeddingProvider(BaseEmbeddingProvider):
    """Google Gemini text embedding provider."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key if api_key is not None else (settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY)

    def get_embeddings(
        self,
        model_name: Optional[str] = None,
        **kwargs: Any,
    ) -> Embeddings:
        api_key = kwargs.pop("api_key", None)
        if api_key is None:
            api_key = self.api_key if self.api_key is not None else (settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY)
        if not api_key:
            raise ProviderUnavailableError(
                "Gemini API key is missing for embeddings. Set GEMINI_API_KEY in .env."
            )

        model = model_name or "models/gemini-embedding-001"
        try:
            return GoogleGenerativeAIEmbeddings(
                google_api_key=api_key,
                model=model,
                **kwargs,
            )
        except Exception as e:
            logger.error(f"Failed to initialize GoogleGenerativeAIEmbeddings with model '{model}': {e}")
            raise ProviderUnavailableError(f"Gemini embeddings error: {str(e)}")

    async def list_available_models(self) -> List[str]:
        return [
            "models/gemini-embedding-001",
            "models/gemini-embedding-2-preview",
            "models/gemini-embedding-2",
        ]

    async def check_health(self) -> Dict[str, Any]:
        api_key = self.api_key if self.api_key is not None else (settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY)
        if not api_key:
            return {
                "status": "unconfigured",
                "available": False,
                "message": "Gemini API key not set.",
            }
        return {"status": "healthy", "available": True}
