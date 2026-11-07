"""Pydantic schemas for Projects, Room Items (Projects & Chats), and PII Breach Consent."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ProjectCreateRequest(BaseModel):
    """Payload to create a new Project within a Room workspace."""
    name: str = Field(..., min_length=1, max_length=255, description="Project title")
    description: Optional[str] = Field(None, max_length=4000, description="Project scope or objective")
    status: Optional[str] = Field("active", description="active, in_progress, completed, archived, pending_call, call_initiated")
    tags: Optional[List[str]] = Field(default_factory=list, description="Categorization tags")
    client_name: Optional[str] = Field(None, max_length=255, description="Client or requester full name")
    email: Optional[str] = Field(None, max_length=255, description="Client contact email")
    phone: Optional[str] = Field(None, max_length=50, description="Client contact phone number")
    communication_channel: Optional[str] = Field("Gmeet", description="Gmeet, Teams, Zoom, others")
    request_type: Optional[str] = Field("standard", description="standard or app_creation")
    transcripts: Optional[str] = Field(None, description="Conversation transcripts compiled from chat")
    meeting_link: Optional[str] = Field(None, max_length=500, description="Call or meeting link")
    conversation_id: Optional[str] = Field(None, description="Source conversation ID for transcript compilation")


class ProjectUpdateRequest(BaseModel):
    """Payload to update an existing Project."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=4000)
    status: Optional[str] = Field(None, description="active, in_progress, completed, archived, pending_call, call_initiated")
    tags: Optional[List[str]] = None
    client_name: Optional[str] = Field(None, max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    communication_channel: Optional[str] = Field(None, description="Gmeet, Teams, Zoom, others")
    request_type: Optional[str] = None
    transcripts: Optional[str] = None
    meeting_link: Optional[str] = None
    call_notes: Optional[str] = None
    call_initiated_at: Optional[datetime] = None


class ProjectResponse(BaseModel):
    """Standard serialized Project representation."""
    id: str
    room_id: str
    user_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    status: str
    request_type: str = "standard"
    client_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    communication_channel: Optional[str] = "Gmeet"
    transcripts: Optional[str] = None
    meeting_link: Optional[str] = None
    call_initiated_at: Optional[datetime] = None
    call_notes: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    conversation_count: int = 0

    class Config:
        from_attributes = True


class AppCreationProjectRequest(BaseModel):
    """Request payload to create an application project from an LLM prompt/conversation."""
    name: str = Field(..., min_length=1, max_length=255, description="Application or Project title")
    description: Optional[str] = Field(None, max_length=4000, description="Application specifications or summary")
    client_name: str = Field(..., min_length=1, max_length=255, description="Requester Full Name")
    email: str = Field(..., min_length=3, max_length=255, description="Requester Email")
    phone: Optional[str] = Field(None, max_length=50, description="Requester Phone number")
    communication_channel: str = Field("Gmeet", description="Communication channel: Gmeet, Teams, Zoom, others")
    room_id: Optional[str] = Field(None, description="Room Workspace ID")
    conversation_id: Optional[str] = Field(None, description="Associated Chat Conversation ID")
    meeting_link: Optional[str] = Field(None, max_length=500, description="Custom or preset meeting link")
    tags: Optional[List[str]] = Field(default_factory=list)


class InitiateCallRequest(BaseModel):
    """Payload to initiate a consultation call for an application project."""
    communication_channel: Optional[str] = Field(None, description="Override communication channel (Gmeet, Teams, Zoom, others)")
    meeting_link: Optional[str] = Field(None, max_length=500, description="Custom meeting link if provided")
    call_notes: Optional[str] = Field(None, description="Preliminary call notes")


class InitiateCallResponse(BaseModel):
    """Response returned when initiating a call with transcripts."""
    project_id: str
    name: str
    request_type: str
    client_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    communication_channel: str
    meeting_link: str
    transcripts: Optional[str]
    call_initiated_at: datetime
    status: str
    message: str


class RoomItemResponse(BaseModel):
    """Polymorphic listing item representing either a Project or a Chat inside a Room."""
    id: str
    item_type: Literal["project", "chat"]
    title: str
    description: Optional[str] = None
    room_id: str
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    status: Optional[str] = None
    request_type: Optional[str] = None
    communication_channel: Optional[str] = None
    client_name: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class RoomItemsFilterResponse(BaseModel):
    """Unified response containing projects and/or chats filtered by user selection."""
    room_id: str
    filter_type: Literal["all", "projects", "chats"]
    total_projects: int
    total_chats: int
    items: List[RoomItemResponse]


class PIIConsentRequest(BaseModel):
    """Payload for user consent regarding PII in shared room."""
    consent_mode: Literal["mask", "unmasked"] = Field(
        ...,
        description="'mask' to share with all PII contextually masked (recommended), or 'unmasked' with explicit consent",
    )
    confirm_acknowledgment: bool = Field(
        ...,
        description="User confirmation that they understand data sharing implications",
    )


class PIIConsentResponse(BaseModel):
    """Response after recording user consent for PII sharing."""
    room_id: str
    pii_consent_status: str
    message: str
    updated_at: datetime


class ShareLinkResponse(BaseModel):
    """Shareable web link details for a room workspace."""
    room_id: str
    share_token: str
    share_url: str
    is_public: bool
    is_revoked: bool
    pii_consent_status: str
    created_at: datetime


class RoomPIIScanResponse(BaseModel):
    """Detailed PII breach inspection report for a room."""
    room_id: str
    has_pii_breach: bool
    breach_count: int
    risk_level: str
    alert_message: Optional[str] = None
    pii_consent_status: str
    detected_categories: List[str]
    preview_masked_snippets: List[str]
