"""Pydantic schemas for Room workspaces, attached documents, and database references."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.document import DocumentResponse


class RoomCreateRequest(BaseModel):
    """Payload to create a new workspace room."""
    name: str = Field(..., min_length=1, max_length=150, description="Name of the room")
    description: Optional[str] = Field(None, max_length=500, description="Optional room topic description")


class RoomUpdateRequest(BaseModel):
    """Payload to update an existing workspace room."""
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=500)


class RoomReferenceItem(BaseModel):
    """Document reference retrieved from database for quick-starting chat context."""
    document_id: str
    filename: str
    chunk_index: int
    page: Optional[int] = 1
    excerpt: str
    summary_hint: Optional[str] = None


class RoomSummaryResponse(BaseModel):
    """Summary of a Room workspace."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    message_count: int = 0


class RoomDetailResponse(BaseModel):
    """Detailed representation of a Room with its documents, references, and conversation."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    documents: List[DocumentResponse] = Field(default_factory=list)
    references: List[RoomReferenceItem] = Field(default_factory=list)
    active_conversation_id: Optional[str] = None
    message_count: int = 0
