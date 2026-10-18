"""Pydantic schemas for document ingestion and management."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class DocumentChunkSchema(BaseModel):
    """Schema for individual document chunks."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    chunk_index: int
    content: str
    chunk_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DocumentResponse(BaseModel):
    """Document summary schema."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_type: str
    file_size: int
    status: str
    chunk_count: int
    error_message: Optional[str] = None
    user_id: Optional[str] = None
    uploader_username: Optional[str] = None
    uploader_email: Optional[str] = None
    client_ip: Optional[str] = None
    audit_metadata: Dict[str, Any] = Field(default_factory=dict)
    is_persistent_vector: bool = True
    is_shared: bool = True
    created_at: datetime
    updated_at: datetime


class DocumentDetailResponse(DocumentResponse):
    """Document detailed schema including chunks."""
    chunks: List[DocumentChunkSchema] = Field(default_factory=list)


class AuditLogResponse(BaseModel):
    """Schema for audit log record."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: Optional[str] = None
    username: Optional[str] = None
    user_email: Optional[str] = None
    action: str
    entity_type: str
    entity_id: str
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DocumentAuditTrailResponse(BaseModel):
    """Complete document audit trail with uploader info and lifecycle events."""
    document_id: str
    filename: str
    uploader_id: Optional[str] = None
    uploader_username: Optional[str] = None
    uploader_email: Optional[str] = None
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None
    uploaded_at: datetime
    events: List[AuditLogResponse] = Field(default_factory=list)


class DocumentListResponse(BaseModel):
    """Paginated or listed documents response."""
    total: int
    items: List[DocumentResponse]


class DocumentUploadResult(BaseModel):
    """Result of uploading one or multiple documents."""
    message: str
    uploaded: List[DocumentResponse]
    failed: List[Dict[str, str]] = Field(default_factory=list)


class EvidenceHighlightLine(BaseModel):
    """Line with evidence match attribution."""
    line_number: int
    text: str
    is_match: bool
    score: float = 0.0


class EvidenceLookupResponse(BaseModel):
    """Provenance and realtime evidence lookup with page navigation and line highlighting."""
    document_id: str
    filename: str
    file_type: str
    page: int
    total_pages: int
    page_text: str
    file_url: str
    chunk_id: Optional[str] = None
    chunk_index: Optional[int] = None
    chunk_content: Optional[str] = None
    query: Optional[str] = None
    highlight_lines: List[EvidenceHighlightLine] = Field(default_factory=list)
