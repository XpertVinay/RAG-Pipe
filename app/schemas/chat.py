"""Pydantic schemas for chat conversations, messages, citations, and streaming."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


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
    document_ids: Optional[List[str]] = Field(None, description="Optional filter to only query specific documents")
    provider: Optional[Literal["ollama", "openai", "anthropic", "openai-compatible", "gemini", "google"]] = None
    model: Optional[str] = None
    temperature: Optional[float] = Field(0.2, ge=0.0, le=2.0)
    top_k: Optional[int] = Field(4, ge=1, le=20)


class MessageResponse(BaseModel):
    """Message item representation."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: str
    content: str
    citations: List[Citation] = Field(default_factory=list)
    metadata_info: Optional[Dict[str, Any]] = Field(default_factory=dict)
    created_at: datetime


class ConversationResponse(BaseModel):
    """Conversation thread summary."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: Optional[int] = None


class ConversationDetailResponse(ConversationResponse):
    """Conversation thread with full message history."""
    messages: List[MessageResponse] = Field(default_factory=list)


class StreamEvent(BaseModel):
    """Server-Sent Event payload."""
    event: Literal["status", "token", "citations", "meta", "error", "done"]
    data: Any
