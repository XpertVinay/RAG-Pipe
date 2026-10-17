"""API endpoints for managing LLM providers and runtime settings."""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional

from app.config import get_settings
from app.providers.factory import ModelFactory
from app.schemas.health import SettingsResponse

router = APIRouter(prefix="/api/settings", tags=["settings"])
settings = get_settings()


class UpdateRuntimeSettingsRequest(BaseModel):
    """Schema for updating active runtime preferences."""
    default_chat_provider: Optional[str] = None
    default_chat_model: Optional[str] = None
    retrieval_top_k: Optional[int] = Field(None, ge=1, le=20)
    similarity_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)


@router.get("", response_model=SettingsResponse)
async def get_system_settings():
    """Retrieve system settings and capabilities of all configured providers."""
    providers_info = await ModelFactory.get_providers_info()

    return SettingsResponse(
        default_chat_provider=settings.DEFAULT_CHAT_PROVIDER,
        default_chat_model=settings.DEFAULT_CHAT_MODEL,
        default_embedding_provider=settings.DEFAULT_EMBEDDING_PROVIDER,
        default_embedding_model=settings.DEFAULT_EMBEDDING_MODEL,
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        retrieval_top_k=settings.RETRIEVAL_TOP_K,
        similarity_threshold=settings.SIMILARITY_THRESHOLD,
        langsmith_tracing=settings.LANGCHAIN_TRACING_V2,
        available_chat_providers=providers_info.get("chat", []),
        available_embedding_providers=providers_info.get("embedding", []),
    )


@router.post("")
async def update_runtime_settings(request: UpdateRuntimeSettingsRequest):
    """Update runtime defaults for the active session."""
    if request.default_chat_provider:
        settings.DEFAULT_CHAT_PROVIDER = request.default_chat_provider
    if request.default_chat_model:
        settings.DEFAULT_CHAT_MODEL = request.default_chat_model
    if request.retrieval_top_k is not None:
        settings.RETRIEVAL_TOP_K = request.retrieval_top_k
    if request.similarity_threshold is not None:
        settings.SIMILARITY_THRESHOLD = request.similarity_threshold

    return {
        "message": "Settings updated successfully.",
        "active_chat_provider": settings.DEFAULT_CHAT_PROVIDER,
        "active_chat_model": settings.DEFAULT_CHAT_MODEL,
        "retrieval_top_k": settings.RETRIEVAL_TOP_K,
        "similarity_threshold": settings.SIMILARITY_THRESHOLD,
    }
