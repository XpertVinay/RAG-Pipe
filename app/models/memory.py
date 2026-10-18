"""SQLAlchemy ORM model for Two-Tier Hierarchical Memory (Short-Term & Long-Term, Global & User-Specific)."""

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class MemoryScope(str, enum.Enum):
    """Scope distribution for memory."""
    GLOBAL = "global"
    USER_SPECIFIC = "user_specific"


class MemoryType(str, enum.Enum):
    """Horizon distribution for memory."""
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"


class MemoryItem(Base):
    """Persisted memory entry supporting expiration, document revaluation, and dual-scoping."""

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scope: Mapped[str] = mapped_column(String(20), default=MemoryScope.GLOBAL.value, index=True)
    memory_type: Mapped[str] = mapped_column(String(20), default=MemoryType.SHORT_TERM.value, index=True)

    # Scoping relations
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    room_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True, index=True
    )
    document_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Core content - compact semantic distillation
    key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[float] = mapped_column(Float, default=0.5)

    # Document binding & revaluation tracking
    document_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    metadata_payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    # Lifecycle, Expiry (TTL) and Revaluation
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revaluation_interval_seconds: Mapped[int] = mapped_column(Integer, default=86400)  # Default: 24h
    access_count: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", lazy="joined")
    document: Mapped[Optional["Document"]] = relationship("Document", lazy="joined")
    room: Mapped[Optional["Room"]] = relationship("Room", lazy="joined")

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        """Check if memory item has expired based on current UTC time."""
        if self.expires_at is None:
            return False
        curr = now or utc_now()
        # Normalise timezone
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if curr.tzinfo is None:
            curr = curr.replace(tzinfo=timezone.utc)
        return curr > exp

    def needs_revaluation(self, current_doc_hash: Optional[str] = None, now: Optional[datetime] = None) -> bool:
        """Check if memory item requires revaluation based on document hash change or elapsed interval."""
        # 1. Document hash check: if document exists and hash changed, document was updated!
        if self.document_id and current_doc_hash and self.document_hash:
            if current_doc_hash != self.document_hash:
                return True

        # 2. Time-based revaluation interval check
        if self.revaluation_interval_seconds and self.revaluation_interval_seconds > 0:
            curr = now or utc_now()
            last_eval = self.revaluated_at or self.updated_at or self.created_at
            if last_eval.tzinfo is None:
                last_eval = last_eval.replace(tzinfo=timezone.utc)
            if curr.tzinfo is None:
                curr = curr.replace(tzinfo=timezone.utc)
            delta = (curr - last_eval).total_seconds()
            if delta >= self.revaluation_interval_seconds:
                return True

        return False
