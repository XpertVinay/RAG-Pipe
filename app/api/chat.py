"""API endpoints for conversation management, querying, and real-time SSE streaming."""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import rag_agent_app
from app.agent.state import AgentState
from app.agent.streaming import stream_rag_agent
from app.config import get_settings
from app.core.logging import logger
from app.database import get_db
from app.models.conversation import Conversation, Message
from app.schemas.chat import (
    ChatRequest,
    Citation,
    ConversationDetailResponse,
    ConversationResponse,
    MessageResponse,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])
settings = get_settings()


@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    title: Optional[str] = Query("New Chat"),
    db: AsyncSession = Depends(get_db),
):
    """Create a new chat conversation thread."""
    conv = Conversation(id=str(uuid.uuid4()), title=title[:250])
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return ConversationResponse.model_validate(conv)


@router.get("/conversations", response_model=List[ConversationResponse])
async def list_conversations(
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List recent conversations."""
    res = await db.execute(
        select(Conversation)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    convs = res.scalars().all()
    return [ConversationResponse.model_validate(c) for c in convs]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    """Get conversation thread details with message history."""
    res = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    return ConversationDetailResponse.model_validate(conv)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_200_OK)
async def delete_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a conversation thread and its messages."""
    res = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    await db.delete(conv)
    await db.commit()
    return {"message": "Conversation deleted.", "conversation_id": conversation_id}


@router.post("/query", response_model=MessageResponse)
async def ask_query(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Standard non-streaming question answering endpoint."""
    conv_id = request.conversation_id
    if not conv_id:
        conv = Conversation(id=str(uuid.uuid4()), title=request.message[:40] + "...")
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
        "document_ids": request.document_ids,
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

    assistant_msg = Message(
        conversation_id=conv_id,
        role="assistant",
        content=answer,
        citations=citations,
        metadata_info={"provider": request.provider, "model": request.model},
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
        created_at=assistant_msg.created_at,
    )


@router.post("/stream")
async def stream_query(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Server-Sent Events (SSE) streaming endpoint for real-time RAG responses."""
    conv_id = request.conversation_id
    if not conv_id:
        conv = Conversation(id=str(uuid.uuid4()), title=request.message[:40] + "...")
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
            document_ids=request.document_ids,
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
