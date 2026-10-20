"""SQLAlchemy models for multi-file Rooms and RoomDocument associations."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class Room(Base):
    """Room workspace model grouping multiple uploaded documents and chat messages."""

    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="Document Workspace")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    share_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True, index=True)
    share_revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    pii_consent_status: Mapped[str] = mapped_column(String(30), default="clean", index=True)  # clean, breach_detected, consent_masked, consent_unmasked
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    room_documents: Mapped[List["RoomDocument"]] = relationship(
        "RoomDocument",
        back_populates="room",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    projects: Mapped[List["Project"]] = relationship(
        "Project",
        back_populates="room",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    conversations: Mapped[List["Conversation"]] = relationship(
        "Conversation",
        back_populates="room",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    members: Mapped[List["RoomMember"]] = relationship(
        "RoomMember",
        back_populates="room",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class RoomMember(Base):
    """Room membership model for granular RBAC sharing (viewer, editor, owner)."""

    __tablename__ = "room_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(30), default="viewer")  # "viewer", "editor", "owner"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    room: Mapped["Room"] = relationship("Room", back_populates="members")
    user: Mapped["User"] = relationship("User", lazy="joined")


class RoomDocument(Base):
    """Association table linking uploaded Documents to a Room."""

    __tablename__ = "room_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    room: Mapped["Room"] = relationship("Room", back_populates="room_documents")
    document: Mapped["Document"] = relationship("Document", lazy="joined")

