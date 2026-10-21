import os
import socket
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import httpx
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama, OllamaEmbeddings

from app.config import get_settings
from app.core.exceptions import ProviderUnavailableError
from app.core.logging import logger
from app.providers.base import BaseChatProvider, BaseEmbeddingProvider

settings = get_settings()

_cached_effective_url: Optional[str] = None


def _probe_socket(url: str, timeout: float = 2.0) -> bool:
    """Fast non-blocking check if target host:port is reachable."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 11434
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def get_effective_ollama_url(base_url: Optional[str] = None) -> str:
    """Resolve reachable Ollama URL whether running in Docker, on host, or container network."""
    global _cached_effective_url
    if _cached_effective_url and not base_url:
        return _cached_effective_url

    configured_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
    is_docker = os.path.exists("/.dockerenv") or os.environ.get("RUNNING_IN_DOCKER") == "true"

    # Normalize localhost in docker if needed
    normalized_url = configured_url
    if is_docker and ("localhost" in configured_url or "127.0.0.1" in configured_url):
        normalized_url = configured_url.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")
    elif not is_docker and "host.docker.internal" in configured_url:
        normalized_url = configured_url.replace("host.docker.internal", "localhost")

    # If normalized configured URL is directly reachable, use it
    if _probe_socket(normalized_url):
        logger.info(f"Ollama connected directly via configured URL: '{normalized_url}'")
        if not base_url:
            _cached_effective_url = normalized_url
        return normalized_url

    # Check candidates for resilient local LLM resolution
    candidates: List[str] = [
        "http://1acer.com:11434",
    ]
    if is_docker:
        candidates.extend([
            "http://ollama:11434",               # Docker network service name
            "http://host.docker.internal:11434",  # Docker Desktop or Linux host-gateway
            "http://172.17.0.1:11434",            # Standard Linux docker0 host bridge
        ])
    else:
        candidates.extend([
            "http://localhost:11434",
            "http://127.0.0.1:11434",
        ])

    for cand in candidates:
        if cand != normalized_url and _probe_socket(cand):
            logger.info(
                f"Auto-resolved reachable Ollama URL at '{cand}' (configured '{configured_url}' was unreachable)"
            )
            if not base_url:
                _cached_effective_url = cand
            return cand

    # Default to normalized URL if probing candidates failed
    logger.warning(f"Ollama socket probe failed for all candidates. Falling back to: '{normalized_url}'")
    return normalized_url


class OllamaChatProvider(BaseChatProvider):
    """Local Ollama chat inference provider optimized for local LLM inference."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = get_effective_ollama_url(base_url)
        self.timeout = float(getattr(settings, "OLLAMA_TIMEOUT", 300.0))
        self.keep_alive = getattr(settings, "OLLAMA_KEEP_ALIVE", "60m")
        self._cached_models: Optional[List[str]] = None

    def get_chat_model(
        self,
        model_name: Optional[str] = None,
        temperature: float = 0.2,
        streaming: bool = True,
        **kwargs: Any,
    ) -> BaseChatModel:
        model = model_name or settings.DEFAULT_CHAT_MODEL
        self.base_url = get_effective_ollama_url(self.base_url)
        keep_alive = kwargs.pop("keep_alive", self.keep_alive)
        num_thread = kwargs.pop("num_thread", getattr(settings, "OLLAMA_NUM_THREADS", None))
        extra_params: Dict[str, Any] = {}
        if num_thread is not None:
            extra_params["num_thread"] = num_thread
        client_kwargs = dict(kwargs.pop("client_kwargs", {}))
        if "timeout" not in client_kwargs:
            client_kwargs["timeout"] = httpx.Timeout(self.timeout, connect=10.0)
        sync_client_kwargs = dict(kwargs.pop("sync_client_kwargs", client_kwargs))
        if "timeout" not in sync_client_kwargs:
            sync_client_kwargs["timeout"] = httpx.Timeout(self.timeout, connect=10.0)
        async_client_kwargs = dict(kwargs.pop("async_client_kwargs", client_kwargs))
        if "timeout" not in async_client_kwargs:
            async_client_kwargs["timeout"] = httpx.Timeout(self.timeout, connect=10.0)

        try:
            return ChatOllama(
                base_url=self.base_url,
                model=model,
                temperature=temperature,
                streaming=streaming,
                client_kwargs=client_kwargs,
                sync_client_kwargs=sync_client_kwargs,
                async_client_kwargs=async_client_kwargs,
                keep_alive=keep_alive,
                **extra_params,
                **kwargs,
            )
        except Exception as e:
            logger.error(f"Failed to initialize ChatOllama model '{model}': {e}")
            raise ProviderUnavailableError(f"Ollama chat provider error: {str(e)}")

    async def check_health(self) -> Dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/api/tags"
        try:
            timeout = httpx.Timeout(connect=1.0, read=2.0, write=2.0, pool=1.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    models = [m.get("name") for m in data.get("models", [])]
                    self._cached_models = models
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
        if self._cached_models:
            return self._cached_models
        health = await self.check_health()
        return health.get("models", [settings.DEFAULT_CHAT_MODEL])


def _parse_keep_alive_seconds(val: Any) -> Optional[int]:
    """Parse string durations like '60m', '1h', or '3600' into integer seconds for OllamaEmbeddings."""
    if val is None:
        return None
    if isinstance(val, int):
        return val
    val_str = str(val).strip().lower()
    if val_str.endswith("s"):
        return int(val_str[:-1])
    if val_str.endswith("m"):
        return int(val_str[:-1]) * 60
    if val_str.endswith("h"):
        return int(val_str[:-1]) * 3600
    if val_str.endswith("d"):
        return int(val_str[:-1]) * 86400
    try:
        return int(val_str)
    except ValueError:
        return 3600


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    """Local Ollama embedding provider optimized for local embeddings with custom batching and timeout."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = get_effective_ollama_url(base_url)
        self.timeout = float(getattr(settings, "OLLAMA_TIMEOUT", 300.0))
        self.keep_alive = getattr(settings, "OLLAMA_KEEP_ALIVE", "60m")

    def get_embeddings(
        self,
        model_name: Optional[str] = None,
        **kwargs: Any,
    ) -> Embeddings:
        model = model_name or settings.DEFAULT_EMBEDDING_MODEL
        self.base_url = get_effective_ollama_url(self.base_url)
        try:
            client_kwargs = dict(kwargs.pop("client_kwargs", {}))
            if "timeout" not in client_kwargs:
                client_kwargs["timeout"] = self.timeout

            sync_client_kwargs = dict(kwargs.pop("sync_client_kwargs", client_kwargs))
            if "timeout" not in sync_client_kwargs:
                sync_client_kwargs["timeout"] = self.timeout

            raw_keep_alive = kwargs.pop("keep_alive", self.keep_alive)
            keep_alive_sec = _parse_keep_alive_seconds(raw_keep_alive)

            num_thread = kwargs.pop("num_thread", getattr(settings, "OLLAMA_NUM_THREADS", None))
            extra_params: Dict[str, Any] = {}
            if num_thread is not None:
                extra_params["num_thread"] = num_thread

            return OllamaEmbeddings(
                base_url=self.base_url,
                model=model,
                client_kwargs=client_kwargs,
                sync_client_kwargs=sync_client_kwargs,
                keep_alive=keep_alive_sec,
                **extra_params,
                **kwargs,
            )
        except Exception as e:
            logger.error(f"Failed to initialize OllamaEmbeddings model '{model}': {e}")
            raise ProviderUnavailableError(f"Ollama embedding provider error: {str(e)}")

    async def check_health(self) -> Dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/api/tags"
        try:
            timeout = httpx.Timeout(connect=1.0, read=2.0, write=2.0, pool=1.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    return {"status": "healthy", "available": True}
                return {"status": "unhealthy", "available": False}
        except Exception as e:
            return {"status": "unhealthy", "available": False, "message": str(e)}
