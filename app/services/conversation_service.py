"""Conversation and Chat service managing thread access, room resolution, and history retrieval."""

from typing import Any, Dict, List, Optional, Tuple
from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.models.room import Room, RoomDocument, RoomMember
from app.models.user import User
from app.services.room_service import check_room_access


def check_conversation_access(conv: Conversation, user: Optional[User]) -> None:
    """Enforce ownership access control for conversation threads."""
    if conv.user_id is not None:
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to access this conversation.",
            )
        if conv.user_id != user.id and getattr(user, "role", "user") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: you do not have permission to view or modify this conversation.",
            )


async def check_room_query_access(room_id: Optional[str], user: Optional[User], db: AsyncSession) -> None:
    """Ensure user is authorized to query within the given room workspace."""
    if not room_id:
        return
    r_res = await db.execute(select(Room).where(Room.id == room_id))
    room = r_res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room workspace not found.")
    await check_room_access(room, user, db, required_role="viewer")


async def resolve_room_and_document_ids(
    db: AsyncSession,
    conversation_id: Optional[str],
    room_id: Optional[str],
    requested_doc_ids: Optional[List[str]],
    user: Optional[User] = None,
) -> Tuple[Optional[str], Optional[List[str]]]:
    """Resolve active room and auto-populate attached document IDs, enforcing strict RBAC isolation."""
    effective_room_id = room_id
    effective_docs = list(requested_doc_ids) if requested_doc_ids else []

    if conversation_id and not effective_room_id:
        c_res = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
        c_obj = c_res.scalar_one_or_none()
        if c_obj and c_obj.room_id:
            effective_room_id = c_obj.room_id

    # If scoped to a room and no explicit doc filter given, pull room documents
    if effective_room_id and not effective_docs:
        rd_res = await db.execute(select(RoomDocument.document_id).where(RoomDocument.room_id == effective_room_id))
        effective_docs = [r[0] for r in rd_res.all()]

    is_admin = user and getattr(user, "role", "user") == "admin"
    if not is_admin:
        room_subquery = (
            select(RoomDocument.document_id)
            .join(Room, Room.id == RoomDocument.room_id)
            .outerjoin(RoomMember, RoomMember.room_id == Room.id)
            .where(
                or_(
                    Room.is_public.is_(True),
                    Room.user_id.is_(None),
                    *([Room.user_id == user.id, RoomMember.user_id == user.id] if user else []),
                )
            )
        )
        permitted_cond = or_(
            Document.is_shared.is_(True),
            Document.id.in_(room_subquery),
            *([Document.user_id == user.id] if user else []),
        )

        if effective_docs:
            val_res = await db.execute(
                select(Document.id).where(
                    Document.id.in_(effective_docs),
                    permitted_cond,
                )
            )
            allowed = set(val_res.scalars().all())
            effective_docs = [d for d in effective_docs if d in allowed]
            if not effective_docs:
                effective_docs = ["__none__"]
        elif not effective_room_id:
            all_res = await db.execute(select(Document.id).where(permitted_cond))
            user_doc_ids = all_res.scalars().all()
            effective_docs = list(user_doc_ids) if user_doc_ids else ["__none__"]

    return effective_room_id, (effective_docs if effective_docs else None)


def classify_response_type(
    intent: str,
    documents: List[Any],
    is_relevant: bool,
    citations: List[Any],
) -> str:
    """Determine response classification tag based on RAG state."""
    if intent == "greeting":
        return "greeting"
    if not documents or not is_relevant:
        return "insufficient_info"
    if citations:
        return "grounded"
    return "general"


async def get_recent_chat_history(
    db: AsyncSession,
    conversation_id: str,
    limit: int = 10,
) -> List[Dict[str, str]]:
    """Retrieve chronologically ordered recent messages formatted for LLM agent context."""
    hist_res = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = list(reversed(hist_res.scalars().all()))
    return [{"role": m.role, "content": m.content} for m in messages]

