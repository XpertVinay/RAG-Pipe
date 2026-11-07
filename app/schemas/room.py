"""Pydantic schemas for Room workspaces, attached documents, and database references."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.document import DocumentResponse


class RoomCreateRequest(BaseModel):
    """Payload to create a new workspace room."""
    name: str = Field(..., min_length=2, max_length=150, description="Name of the room")
    description: Optional[str] = Field(None, max_length=500, description="Optional room topic description")
    is_public: bool = Field(False, description="Whether this room is public to all users")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 2:
            raise ValueError("Workspace room name must be at least 2 characters.")
        if len(cleaned) > 150:
            raise ValueError("Workspace room name cannot exceed 150 characters.")
        return cleaned

    @field_validator("description")
    @classmethod
    def validate_desc(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned if cleaned else None


class RoomUpdateRequest(BaseModel):
    """Payload to update an existing workspace room."""
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    description: Optional[str] = Field(None, max_length=500)
    is_public: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = v.strip()
        if len(cleaned) < 2:
            raise ValueError("Workspace room name must be at least 2 characters.")
        if len(cleaned) > 150:
            raise ValueError("Workspace room name cannot exceed 150 characters.")
        return cleaned

    @field_validator("description")
    @classmethod
    def validate_desc(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned if cleaned else None


class RoomShareRequest(BaseModel):
    """Payload to update room visibility."""
    is_public: bool = Field(..., description="Whether the workspace is accessible to all users")


class RoomMemberAddRequest(BaseModel):
    """Payload to add or invite a member to a room."""
    username_or_email: str = Field(..., min_length=3, max_length=100)
    role: str = Field("viewer", description="Member role: 'viewer', 'editor', or 'owner'")

    @field_validator("username_or_email")
    @classmethod
    def validate_member(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 3:
            raise ValueError("Member username or email must be at least 3 characters.")
        if len(cleaned) > 100:
            raise ValueError("Member username or email cannot exceed 100 characters.")
        return cleaned

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if cleaned not in ("viewer", "editor", "owner"):
            raise ValueError("Member role must be one of: 'viewer', 'editor', 'owner'.")
        return cleaned


class RoomMemberResponse(BaseModel):
    """Room member information for RBAC sharing."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    room_id: str
    user_id: str
    username: str
    email: str
    full_name: Optional[str] = None
    role: str
    created_at: datetime


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
    is_public: bool = False
    user_role: Optional[str] = None
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
    is_public: bool = False
    user_role: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    documents: List[DocumentResponse] = Field(default_factory=list)
    references: List[RoomReferenceItem] = Field(default_factory=list)
    members: List[RoomMemberResponse] = Field(default_factory=list)
    active_conversation_id: Optional[str] = None
    message_count: int = 0
