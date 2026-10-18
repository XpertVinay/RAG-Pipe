"""Pydantic schemas for Two-Tier Hierarchical Memory System."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MemoryItemBase(BaseModel):
    """Base schema for memory payload."""
    scope: str = Field(..., description="'global' or 'user_specific'")
    memory_type: str = Field(..., description="'short_term' or 'long_term'")
    key: str = Field(..., max_length=120, description="Unique semantic key descriptor")
    content: str = Field(..., description="Distilled high-density fact or context string")
    importance: float = Field(default=0.5, ge=0.0, le=1.0, description="Salience/priority score")
    metadata_payload: Optional[Dict[str, Any]] = Field(default_factory=dict)


class MemoryCreate(MemoryItemBase):
    """Payload to create or update a memory item."""
    user_id: Optional[str] = None
    room_id: Optional[str] = None
    document_id: Optional[str] = None
    document_hash: Optional[str] = None
    ttl_seconds: Optional[int] = Field(default=None, description="Time-To-Live in seconds before expiration")
    revaluation_interval_seconds: Optional[int] = Field(default=86400, description="Seconds between document revaluations")


class MemoryResponse(MemoryItemBase):
    """Response schema representing a persisted memory item."""
    id: str
    user_id: Optional[str] = None
    room_id: Optional[str] = None
    document_id: Optional[str] = None
    document_hash: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime] = None
    revaluated_at: Optional[datetime] = None
    revaluation_interval_seconds: int = 86400
    access_count: int = 0
    is_expired: bool = False
    needs_revaluation: bool = False

    class Config:
        from_attributes = True


class ScopeDistributionItem(BaseModel):
    """Metrics for a single cell in the memory distribution matrix."""
    count: int = 0
    estimated_bytes: int = 0
    sample_keys: List[str] = Field(default_factory=list)


class MemoryDistributionStats(BaseModel):
    """Complete distribution matrix and low-memory performance metrics."""
    global_short_term: ScopeDistributionItem
    global_long_term: ScopeDistributionItem
    user_short_term: ScopeDistributionItem
    user_long_term: ScopeDistributionItem
    total_memories: int
    active_memories: int
    expired_memories: int
    needs_revaluation_count: int
    in_memory_l1_bytes: int
    in_memory_l1_items: int
    in_memory_l1_max_items: int
    cache_hits: int
    cache_misses: int


class MemoryRevaluationRequest(BaseModel):
    """Request to trigger document or context revaluation."""
    document_id: Optional[str] = None
    user_id: Optional[str] = None
    scope: Optional[str] = None
    force_all: bool = False


class MemoryRevaluationResult(BaseModel):
    """Result of memory revaluation workflow."""
    scanned_count: int
    revaluated_count: int
    updated_keys: List[str]
    expired_pruned_count: int
    message: str
