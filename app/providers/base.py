"""Abstract base classes for LLM and Embedding providers."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.embeddings import Embeddings


class BaseChatProvider(ABC):
    """Abstract interface for chat model providers."""

    @abstractmethod
    def get_chat_model(
        self,
        model_name: Optional[str] = None,
        temperature: float = 0.2,
        streaming: bool = True,
        **kwargs: Any,
    ) -> BaseChatModel:
        """Instantiate and return a LangChain chat model."""
        pass

    @abstractmethod
    async def check_health(self) -> Dict[str, Any]:
        """Perform a health check on the provider."""
        pass

    @abstractmethod
    async def list_available_models(self) -> List[str]:
        """List available models from the provider."""
        pass


class BaseEmbeddingProvider(ABC):
    """Abstract interface for text embedding providers."""

    @abstractmethod
    def get_embeddings(
        self,
        model_name: Optional[str] = None,
        **kwargs: Any,
    ) -> Embeddings:
        """Instantiate and return LangChain Embeddings."""
        pass

    @abstractmethod
    async def check_health(self) -> Dict[str, Any]:
        """Perform a health check on the embedding provider."""
        pass
