"""API endpoints for conversation management, querying, and real-time SSE streaming with Room & Auth integration."""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import rag_agent_app
from app.agent.state import AgentState
from app.agent.streaming import stream_rag_agent
from app.config import get_settings
from app.core.auth import get_optional_user
from app.core.logging import logger
from app.core.rate_limit import RateLimiter
from app.database import get_db
from app.models.conversation import Conversation, Message
from app.models.room import Room, RoomDocument
from app.models.user import User
from app.schemas.chat import (
    ChatRequest,
    Citation,
    ConversationDetailResponse,
    ConversationResponse,
    MessageResponse,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])
settings = get_settings()

chat_rate_limiter = RateLimiter(max_requests=60, window_seconds=60)


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
    if room and room.user_id is not None:
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to access this workspace.",
            )
        if room.user_id != user.id and getattr(user, "role", "user") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this workspace.",
            )


async def resolve_room_and_document_ids(
    db: AsyncSession,
    conversation_id: Optional[str],
    room_id: Optional[str],
    requested_doc_ids: Optional[List[str]],
) -> tuple[Optional[str], Optional[List[str]]]:
    """Resolve active room and auto-populate attached document IDs if not explicitly passed."""
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

    return effective_room_id, (effective_docs if effective_docs else None)


@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    title: Optional[str] = Query("New Chat"),
    room_id: Optional[str] = Query(None),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new chat conversation thread, optionally associated with a room or user."""
    if room_id:
        await check_room_query_access(room_id, current_user, db)

    conv = Conversation(
        id=str(uuid.uuid4()),
        room_id=room_id,
        user_id=current_user.id if current_user else None,
        title=title[:250],
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return ConversationResponse.model_validate(conv)


@router.get("/conversations", response_model=List[ConversationResponse])
async def list_conversations(
    limit: int = Query(30, ge=1, le=100),
    room_id: Optional[str] = Query(None),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """List recent conversations, filtered by room or authenticated user."""
    if room_id:
        await check_room_query_access(room_id, current_user, db)

    query = select(Conversation)

    if room_id:
        query = query.where(Conversation.room_id == room_id)
    elif current_user:
        query = query.where(or_(Conversation.user_id == current_user.id, Conversation.user_id == None))

    query = query.order_by(Conversation.updated_at.desc()).limit(limit)
    res = await db.execute(query)
    convs = res.scalars().all()
    return [ConversationResponse.model_validate(c) for c in convs]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Get conversation thread details with full message history."""
    res = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    check_conversation_access(conv, current_user)
    return ConversationDetailResponse.model_validate(conv)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_200_OK)
async def delete_conversation(
    conversation_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a conversation thread and its messages."""
    res = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    check_conversation_access(conv, current_user)

    await db.delete(conv)
    await db.commit()
    return {"message": "Conversation deleted.", "conversation_id": conversation_id}


@router.post(
    "/query",
    response_model=MessageResponse,
    dependencies=[Depends(chat_rate_limiter)],
)
async def ask_query(
    request: ChatRequest,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Standard non-streaming question answering endpoint with room context resolution."""
    conv_id = request.conversation_id
    effective_room_id, doc_ids = await resolve_room_and_document_ids(
        db, conv_id, request.room_id, request.document_ids
    )

    if effective_room_id:
        await check_room_query_access(effective_room_id, current_user, db)

    if conv_id:
        c_check = await db.execute(select(Conversation).where(Conversation.id == conv_id))
        conv_obj = c_check.scalar_one_or_none()
        if conv_obj:
            check_conversation_access(conv_obj, current_user)
    else:
        conv = Conversation(
            id=str(uuid.uuid4()),
            room_id=effective_room_id,
            user_id=current_user.id if current_user else None,
            title=request.message[:40] + "...",
        )
        db.add(conv)
        await db.flush()
        conv_id = conv.id

    # Record user message
    user_msg = Message(
        conversation_id=conv_id,
        role="user",
        content=request.message,
    )
    db.add(user_msg)
    await db.flush()

    # Load recent conversation history
    hist_res = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
        .limit(10)
    )
    messages = hist_res.scalars().all()
    chat_history = [{"role": m.role, "content": m.content} for m in messages]

    # Run LangGraph RAG Agent
    state: AgentState = {
        "query": request.message,
        "original_query": request.message,
        "chat_history": chat_history,
        "document_ids": doc_ids,
        "provider": request.provider,
        "model": request.model,
        "temperature": request.temperature or 0.2,
        "top_k": request.top_k or 4,
        "intent": "qa",
        "documents": [],
        "citations": [],
        "retrieval_retry_count": 0,
        "max_retries": 2,
        "is_relevant": False,
        "generation_grounded": True,
        "answer": "",
        "error": None,
        "status_update": "Starting query",
    }

    final_state = await rag_agent_app.ainvoke(state)
    answer = final_state.get("answer", "No answer generated.")
    citations = [
        c.model_dump() if isinstance(c, Citation) else c
        for c in final_state.get("citations", [])
    ]

    intent = final_state.get("intent", "qa")
    documents = final_state.get("documents", [])
    is_relevant = final_state.get("is_relevant", False)
    retrieval_retry_count = final_state.get("retrieval_retry_count", 0)
    generation_grounded = final_state.get("generation_grounded", True)

    if intent == "greeting":
        response_type = "greeting"
    elif not documents or not is_relevant:
        response_type = "insufficient_info"
    elif citations:
        response_type = "grounded"
    else:
        response_type = "general"

    meta_payload = {
        "provider": request.provider,
        "model": request.model,
        "response_type": response_type,
        "intent": intent,
        "retrieval_retry_count": retrieval_retry_count,
        "generation_grounded": generation_grounded,
        "citation_count": len(citations),
        "room_id": effective_room_id,
    }

    assistant_msg = Message(
        conversation_id=conv_id,
        role="assistant",
        content=answer,
        citations=citations,
        metadata_info=meta_payload,
    )
    db.add(assistant_msg)
    await db.commit()
    await db.refresh(assistant_msg)

    return MessageResponse(
        id=assistant_msg.id,
        conversation_id=conv_id,
        role="assistant",
        content=assistant_msg.content,
        citations=[Citation(**c) for c in citations],
        metadata_info=meta_payload,
        created_at=assistant_msg.created_at,
    )


@router.post(
    "/stream",
    dependencies=[Depends(chat_rate_limiter)],
)
async def stream_query(
    request: ChatRequest,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Server-Sent Events (SSE) streaming endpoint for real-time RAG responses."""
    conv_id = request.conversation_id
    effective_room_id, doc_ids = await resolve_room_and_document_ids(
        db, conv_id, request.room_id, request.document_ids
    )

    if effective_room_id:
        await check_room_query_access(effective_room_id, current_user, db)

    if conv_id:
        c_check = await db.execute(select(Conversation).where(Conversation.id == conv_id))
        conv_obj = c_check.scalar_one_or_none()
        if conv_obj:
            check_conversation_access(conv_obj, current_user)
    else:
        conv = Conversation(
            id=str(uuid.uuid4()),
            room_id=effective_room_id,
            user_id=current_user.id if current_user else None,
            title=request.message[:40] + "...",
        )
        db.add(conv)
        await db.commit()
        conv_id = conv.id

    # Record user message in DB
    user_msg = Message(
        conversation_id=conv_id,
        role="user",
        content=request.message,
    )
    db.add(user_msg)
    await db.commit()

    # Load history
    hist_res = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
        .limit(10)
    )
    history = [{"role": m.role, "content": m.content} for m in hist_res.scalars().all()]

    return StreamingResponse(
        stream_rag_agent(
            query=request.message,
            conversation_id=conv_id,
            chat_history=history,
            document_ids=doc_ids,
            provider=request.provider,
            model=request.model,
            temperature=request.temperature or 0.2,
            top_k=request.top_k or 4,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
