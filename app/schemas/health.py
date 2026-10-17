"""Health and settings schemas."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ServiceHealth(BaseModel):
    """Health status of an individual subsystem."""
    status: str
    message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class SystemHealthResponse(BaseModel):
    """Overall system health status."""
    status: str
    version: str
    environment: str
    components: Dict[str, ServiceHealth]


class ProviderInfo(BaseModel):
    """Details regarding an LLM or Embedding provider."""
    name: str
    configured: bool
    available: bool
    models: List[str] = Field(default_factory=list)
    default_model: Optional[str] = None
    note: Optional[str] = None


class SettingsResponse(BaseModel):
    """Current system settings for LLMs, retrieval, and providers."""
    default_chat_provider: str
    default_chat_model: str
    default_embedding_provider: str
    default_embedding_model: str
    chunk_size: int
    chunk_overlap: int
    retrieval_top_k: int
    similarity_threshold: float
    langsmith_tracing: bool
    available_chat_providers: List[ProviderInfo]
    available_embedding_providers: List[ProviderInfo]
