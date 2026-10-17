import os
from typing import Any, Dict, List, Optional
import httpx
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama, OllamaEmbeddings

from app.config import get_settings
from app.core.exceptions import ProviderUnavailableError
from app.core.logging import logger
from app.providers.base import BaseChatProvider, BaseEmbeddingProvider

settings = get_settings()


def get_effective_ollama_url(base_url: Optional[str] = None) -> str:
    """Resolve reachable Ollama URL whether running on host or inside Docker."""
    url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
    is_docker = os.path.exists("/.dockerenv") or os.environ.get("RUNNING_IN_DOCKER") == "true"
    if not is_docker and "host.docker.internal" in url:
        return url.replace("host.docker.internal", "localhost")
    if is_docker and ("localhost" in url or "127.0.0.1" in url):
        return url.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")
    return url


class OllamaChatProvider(BaseChatProvider):
    """Local Ollama chat inference provider."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = get_effective_ollama_url(base_url)
        self.timeout = settings.OLLAMA_TIMEOUT

    def get_chat_model(
        self,
        model_name: Optional[str] = None,
        temperature: float = 0.2,
        streaming: bool = True,
        **kwargs: Any,
    ) -> BaseChatModel:
        model = model_name or settings.DEFAULT_CHAT_MODEL
        try:
            return ChatOllama(
                base_url=self.base_url,
                model=model,
                temperature=temperature,
                streaming=streaming,
                timeout=self.timeout,
                **kwargs,
            )
        except Exception as e:
            logger.error(f"Failed to initialize ChatOllama model '{model}': {e}")
            raise ProviderUnavailableError(f"Ollama chat provider error: {str(e)}")

    async def check_health(self) -> Dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    models = [m.get("name") for m in data.get("models", [])]
                    return {
                        "status": "healthy",
                        "available": True,
                        "url": self.base_url,
                        "models": models,
                    }
                return {
                    "status": "degraded",
                    "available": False,
                    "message": f"Ollama returned HTTP status {response.status_code}",
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "available": False,
                "message": f"Could not reach Ollama server at {self.base_url}: {str(e)}",
            }

    async def list_available_models(self) -> List[str]:
        health = await self.check_health()
        return health.get("models", [settings.DEFAULT_CHAT_MODEL])


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    """Local Ollama embedding provider."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = get_effective_ollama_url(base_url)

    def get_embeddings(
        self,
        model_name: Optional[str] = None,
        **kwargs: Any,
    ) -> Embeddings:
        model = model_name or settings.DEFAULT_EMBEDDING_MODEL
        try:
            return OllamaEmbeddings(
                base_url=self.base_url,
                model=model,
                **kwargs,
            )
        except Exception as e:
            logger.error(f"Failed to initialize OllamaEmbeddings model '{model}': {e}")
            raise ProviderUnavailableError(f"Ollama embedding provider error: {str(e)}")

    async def check_health(self) -> Dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    return {"status": "healthy", "available": True}
                return {"status": "unhealthy", "available": False}
        except Exception as e:
            return {"status": "unhealthy", "available": False, "message": str(e)}
