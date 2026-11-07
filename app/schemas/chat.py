"""Pydantic schemas for chat conversations, messages, citations, and streaming."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Citation(BaseModel):
    """Citation reference returned from RAG retrieval."""
    document_id: str
    filename: str
    chunk_id: str
    page: Optional[int] = None
    excerpt: str
    relevance_score: Optional[float] = None


class ChatRequest(BaseModel):
    """Payload for asking a question."""
    message: str = Field(..., min_length=1, max_length=4000, description="The user query text")
    conversation_id: Optional[str] = Field(None, description="Optional conversation UUID to continue context")
    room_id: Optional[str] = Field(None, description="Optional room workspace UUID to scope documents and context")
    project_id: Optional[str] = Field(None, description="Optional project UUID within the room")
    document_ids: Optional[List[str]] = Field(None, description="Optional filter to only query specific documents")
    provider: Optional[Literal["ollama", "openai", "anthropic", "openai-compatible", "gemini", "google"]] = None
    model: Optional[str] = Field(None, max_length=100)
    temperature: Optional[float] = Field(0.2, ge=0.0, le=2.0)
    top_k: Optional[int] = Field(4, ge=1, le=20)

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Message cannot be empty or purely whitespace.")
        if len(cleaned) > 4000:
            raise ValueError("Message cannot exceed 4000 characters.")
        return cleaned

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned if cleaned else None


class VisualizationArtifact(BaseModel):
    """Rendered chart or graphical artifact generated via secure code execution."""
    has_image: bool = False
    image_base64: Optional[str] = None
    code: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    error: Optional[str] = None
    execution_time_ms: Optional[float] = None
    status: str = "success"


class MessageResponse(BaseModel):
    """Message item representation."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: str
    content: str
    citations: List[Citation] = Field(default_factory=list)
    metadata_info: Optional[Dict[str, Any]] = Field(default_factory=dict)
    visualization: Optional[VisualizationArtifact] = None
    created_at: datetime


class ConversationResponse(BaseModel):
    """Conversation thread summary."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    room_id: Optional[str] = None
    project_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    message_count: Optional[int] = None


class ConversationDetailResponse(ConversationResponse):
    """Conversation thread with full message history."""
    messages: List[MessageResponse] = Field(default_factory=list)


class StreamEvent(BaseModel):
    """Server-Sent Event payload."""
    event: Literal["status", "token", "citations", "meta", "visualization", "error", "done"]
    data: Any
