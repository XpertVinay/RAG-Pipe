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
    created_at: datetime
    updated_at: datetime


class DocumentDetailResponse(DocumentResponse):
    """Document detailed schema including chunks."""
    chunks: List[DocumentChunkSchema] = Field(default_factory=list)


class DocumentListResponse(BaseModel):
    """Paginated or listed documents response."""
    total: int
    items: List[DocumentResponse]


class DocumentUploadResult(BaseModel):
    """Result of uploading one or multiple documents."""
    message: str
    uploaded: List[DocumentResponse]
    failed: List[Dict[str, str]] = Field(default_factory=list)
