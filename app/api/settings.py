"""API endpoints for managing LLM providers and runtime settings."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.ingestion.vector_store import vector_store
from app.providers.factory import ModelFactory
from app.schemas.health import SettingsResponse
from app.services.config_service import config_service

router = APIRouter(prefix="/settings", tags=["settings"])
settings = get_settings()


class UpdateRuntimeSettingsRequest(BaseModel):
    """Schema for updating active runtime preferences."""
    default_chat_provider: Optional[str] = None
    default_chat_model: Optional[str] = Field(None, max_length=100)
    default_embedding_provider: Optional[str] = None
    default_embedding_model: Optional[str] = Field(None, max_length=100)
    retrieval_top_k: Optional[int] = Field(None, ge=1, le=20)
    similarity_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)

    @field_validator("default_chat_provider")
    @classmethod
    def validate_chat_provider(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = v.strip().lower()
        valid = {"ollama", "gemini", "google", "openai", "anthropic", "openai-compatible"}
        if cleaned not in valid:
            raise ValueError(f"Invalid chat provider '{cleaned}'. Valid choices: {', '.join(sorted(valid))}")
        return cleaned

    @field_validator("default_chat_model")
    @classmethod
    def validate_chat_model(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = v.strip()
        if len(cleaned) > 100:
            raise ValueError("Chat model name cannot exceed 100 characters.")
        return cleaned if cleaned else None

    @field_validator("default_embedding_provider")
    @classmethod
    def validate_embedding_provider(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = v.strip().lower()
        valid = {"ollama", "gemini", "google", "openai"}
        if cleaned not in valid:
            raise ValueError(f"Invalid embedding provider '{cleaned}'. Valid choices: {', '.join(sorted(valid))}")
        return cleaned

    @field_validator("default_embedding_model")
    @classmethod
    def validate_embedding_model(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = v.strip()
        if len(cleaned) > 100:
            raise ValueError("Embedding model name cannot exceed 100 characters.")
        return cleaned if cleaned else None


@router.get("", response_model=SettingsResponse)
async def get_system_settings(db: AsyncSession = Depends(get_db)):
    """Retrieve system settings from cache and database along with capabilities of all configured providers."""
    providers_info = await ModelFactory.get_providers_info()

    default_chat_provider = await config_service.get_setting("default_chat_provider", settings.DEFAULT_CHAT_PROVIDER, db)
    default_chat_model = await config_service.get_setting("default_chat_model", settings.DEFAULT_CHAT_MODEL, db)
    default_embedding_provider = await config_service.get_setting("default_embedding_provider", settings.DEFAULT_EMBEDDING_PROVIDER, db)
    default_embedding_model = await config_service.get_setting("default_embedding_model", settings.DEFAULT_EMBEDDING_MODEL, db)
    chunk_size = await config_service.get_setting("chunk_size", settings.CHUNK_SIZE, db)
    chunk_overlap = await config_service.get_setting("chunk_overlap", settings.CHUNK_OVERLAP, db)
    retrieval_top_k = await config_service.get_setting("retrieval_top_k", settings.RETRIEVAL_TOP_K, db)
    similarity_threshold = await config_service.get_setting("similarity_threshold", settings.SIMILARITY_THRESHOLD, db)

    return SettingsResponse(
        default_chat_provider=default_chat_provider,
        default_chat_model=default_chat_model,
        default_embedding_provider=default_embedding_provider,
        default_embedding_model=default_embedding_model,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        retrieval_top_k=retrieval_top_k,
        similarity_threshold=similarity_threshold,
        langsmith_tracing=settings.LANGCHAIN_TRACING_V2,
        available_chat_providers=providers_info.get("chat", []),
        available_embedding_providers=providers_info.get("embedding", []),
    )


@router.post("")
async def update_runtime_settings(request: UpdateRuntimeSettingsRequest, db: AsyncSession = Depends(get_db)):
    """Update runtime defaults for the active session, persisting to database and caching."""
    if request.default_chat_provider:
        await config_service.set_setting("default_chat_provider", request.default_chat_provider, db=db)
    if request.default_chat_model:
        await config_service.set_setting("default_chat_model", request.default_chat_model, db=db)
    if request.default_embedding_provider:
        await config_service.set_setting("default_embedding_provider", request.default_embedding_provider, db=db)
        vector_store._store = None
    if request.default_embedding_model:
        await config_service.set_setting("default_embedding_model", request.default_embedding_model, db=db)
        vector_store._store = None
    if request.retrieval_top_k is not None:
        await config_service.set_setting("retrieval_top_k", request.retrieval_top_k, db=db)
    if request.similarity_threshold is not None:
        await config_service.set_setting("similarity_threshold", request.similarity_threshold, db=db)

    return {
        "message": "Settings updated successfully.",
        "active_chat_provider": await config_service.get_setting("default_chat_provider", settings.DEFAULT_CHAT_PROVIDER, db),
        "active_chat_model": await config_service.get_setting("default_chat_model", settings.DEFAULT_CHAT_MODEL, db),
        "active_embedding_provider": await config_service.get_setting("default_embedding_provider", settings.DEFAULT_EMBEDDING_PROVIDER, db),
        "active_embedding_model": await config_service.get_setting("default_embedding_model", settings.DEFAULT_EMBEDDING_MODEL, db),
        "retrieval_top_k": await config_service.get_setting("retrieval_top_k", settings.RETRIEVAL_TOP_K, db),
        "similarity_threshold": await config_service.get_setting("similarity_threshold", settings.SIMILARITY_THRESHOLD, db),
    }
