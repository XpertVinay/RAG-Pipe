"""Model factory for dynamic LLM and Embedding provider resolution."""

from typing import Any, Dict, List, Optional
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel

from app.config import get_settings
from app.core.exceptions import ProviderUnavailableError
from app.core.logging import logger
from app.providers.anthropic import AnthropicChatProvider
from app.providers.base import BaseChatProvider, BaseEmbeddingProvider
from app.providers.gemini import GeminiChatProvider, GeminiEmbeddingProvider
from app.providers.ollama import OllamaChatProvider, OllamaEmbeddingProvider
from app.providers.openai import OpenAIChatProvider, OpenAIEmbeddingProvider
from app.schemas.health import ProviderInfo

settings = get_settings()


class ModelFactory:
    """Factory to instantiate and check chat and embedding providers."""

    _chat_providers: Dict[str, BaseChatProvider] = {}
    _embedding_providers: Dict[str, BaseEmbeddingProvider] = {}

    @classmethod
    def _init_providers(cls) -> None:
        if not cls._chat_providers:
            cls._chat_providers = {
                "ollama": OllamaChatProvider(),
                "openai": OpenAIChatProvider(),
                "openai-compatible": OpenAIChatProvider(
                    api_key=settings.OPENAI_API_KEY,
                    base_url=settings.OPENAI_BASE_URL,
                ),
                "anthropic": AnthropicChatProvider(),
                "gemini": GeminiChatProvider(),
                "google": GeminiChatProvider(),
            }

        if not cls._embedding_providers:
            cls._embedding_providers = {
                "ollama": OllamaEmbeddingProvider(),
                "openai": OpenAIEmbeddingProvider(),
                "gemini": GeminiEmbeddingProvider(),
                "google": GeminiEmbeddingProvider(),
            }

    @classmethod
    def get_chat_model(
        cls,
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
        temperature: float = 0.2,
        streaming: bool = True,
        **kwargs: Any,
    ) -> BaseChatModel:
        """Resolve and instantiate the requested chat model."""
        cls._init_providers()
        name = (provider_name or settings.DEFAULT_CHAT_PROVIDER).lower()
        provider = cls._chat_providers.get(name)

        if not provider:
            raise ProviderUnavailableError(
                f"Unknown or unsupported chat provider: '{name}'. Supported: {list(cls._chat_providers.keys())}"
            )

        logger.info(f"Instantiating chat model with provider='{name}', model='{model_name or 'default'}'")
        return provider.get_chat_model(
            model_name=model_name,
            temperature=temperature,
            streaming=streaming,
            **kwargs,
        )

    _cached_embeddings: Dict[str, Embeddings] = {}

    @classmethod
    def get_embeddings(
        cls,
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
        **kwargs: Any,
    ) -> Embeddings:
        """Resolve, instantiate, and cache the requested embedding model."""
        cls._init_providers()
        name = (provider_name or settings.DEFAULT_EMBEDDING_PROVIDER).lower()
        model = (model_name or "").lower()
        cache_key = f"{name}:{model}"

        # Return cached instance if no custom kwargs are passed
        if not kwargs and cache_key in cls._cached_embeddings:
            return cls._cached_embeddings[cache_key]

        provider = cls._embedding_providers.get(name)
        if not provider:
            raise ProviderUnavailableError(
                f"Unknown or unsupported embedding provider: '{name}'. Supported: {list(cls._embedding_providers.keys())}"
            )

        logger.info(f"Instantiating embeddings with provider='{name}', model='{model_name or 'default'}'")
        emb = provider.get_embeddings(model_name=model_name, **kwargs)
        if not kwargs:
            cls._cached_embeddings[cache_key] = emb
        return emb

    @classmethod
    async def get_providers_info(cls) -> Dict[str, List[ProviderInfo]]:
        """Collect capabilities and health of all registered providers."""
        cls._init_providers()
        chat_info: List[ProviderInfo] = []
        for name, provider in cls._chat_providers.items():
            if name == "google":
                continue
            try:
                health = await provider.check_health()
                models = await provider.list_available_models()
                chat_info.append(
                    ProviderInfo(
                        name=name,
                        configured=health.get("available", False) or bool(health.get("configured", False)),
                        available=health.get("available", False),
                        models=models,
                        default_model=settings.DEFAULT_CHAT_MODEL if name == "ollama" else ("gemini-2.5-flash" if name == "gemini" else (models[0] if models else None)),
                        note=health.get("message"),
                    )
                )
            except Exception as e:
                chat_info.append(
                    ProviderInfo(
                        name=name,
                        configured=False,
                        available=False,
                        models=[],
                        note=str(e),
                    )
                )

        embedding_info: List[ProviderInfo] = []
        for name, provider in cls._embedding_providers.items():
            if name == "google":
                continue
            try:
                health = await provider.check_health()
                if name == "ollama":
                    emb_models = [settings.DEFAULT_EMBEDDING_MODEL]
                    default_emb = settings.DEFAULT_EMBEDDING_MODEL
                elif name == "gemini":
                    emb_models = ["models/gemini-embedding-001", "models/gemini-embedding-2-preview"]
                    default_emb = "models/gemini-embedding-001"
                else:
                    emb_models = ["text-embedding-3-small"]
                    default_emb = "text-embedding-3-small"

                embedding_info.append(
                    ProviderInfo(
                        name=name,
                        configured=health.get("available", False) or bool(health.get("configured", False)),
                        available=health.get("available", False),
                        models=emb_models,
                        default_model=default_emb,
                    )
                )
            except Exception as e:
                embedding_info.append(
                    ProviderInfo(
                        name=name,
                        configured=False,
                        available=False,
                        models=[],
                        note=str(e),
                    )
                )

        return {"chat": chat_info, "embedding": embedding_info}
