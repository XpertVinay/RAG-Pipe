"""API endpoints for conversation management, querying, and real-time SSE streaming with Room & Auth integration."""

import asyncio
import json
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.guardrail_service import guardrail_service

from app import database
from app.agent.graph import rag_agent_app
from app.agent.state import AgentState
from app.agent.streaming import stream_rag_agent
from app.config import get_settings
from app.core.auth import get_current_user, get_optional_user
from app.core.logging import logger
from app.core.rate_limit import RateLimiter
from app.database import get_db
from app.models.conversation import Conversation, Message
from app.models.memory import MemoryItem
from app.models.user import User
from app.schemas.chat import (
    ChatRequest,
    Citation,
    ConversationDetailResponse,
    ConversationResponse,
    MessageResponse,
    VisualizationArtifact,
)
from app.services.conversation_service import (
    check_conversation_access,
    check_document_processing_readiness,
    check_room_query_access,
    classify_response_type,
    get_recent_chat_history,
    resolve_room_and_document_ids,
)

router = APIRouter(prefix="/chat", tags=["chat"])
settings = get_settings()

chat_rate_limiter = RateLimiter(max_requests=getattr(settings, "RATE_LIMIT_CHAT_MAX", 60), window_seconds=60)


@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    title: Optional[str] = Query("New Chat"),
    room_id: Optional[str] = Query(None),
    project_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new chat conversation thread, optionally associated with a room, project, or user."""
    if room_id:
        await check_room_query_access(room_id, current_user, db)

    conv = Conversation(
        id=str(uuid.uuid4()),
        room_id=room_id,
        project_id=project_id,
        user_id=current_user.id,
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
    project_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List recent conversations, filtered by room, project, or authenticated user."""
    if room_id:
        await check_room_query_access(room_id, current_user, db)

    query = select(Conversation)

    if room_id:
        query = query.where(Conversation.room_id == room_id)
    elif getattr(current_user, "role", "user") == "admin":
        pass  # Admin can view all
    else:
        query = query.where(or_(Conversation.user_id == current_user.id, Conversation.user_id.is_(None)))

    if project_id:
        query = query.where(Conversation.project_id == project_id)

    query = query.order_by(Conversation.updated_at.desc()).limit(limit)
    res = await db.execute(query)
    convs = res.scalars().all()
    return [ConversationResponse.model_validate(c) for c in convs]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get conversation thread details with full message history."""
    res = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    check_conversation_access(conv, current_user)
    return ConversationDetailResponse.model_validate(conv)


@router.delete("/data/all", status_code=status.HTTP_200_OK)
@router.delete("/conversations/all", status_code=status.HTTP_200_OK)
async def delete_all_chat_and_memory_data(
    room_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete all conversations, messages, and associated conversational memories (STM/LTM)."""
    # 1. Collect conversation IDs matching room/user
    conv_query = select(Conversation)
    has_room_filter = False
    if room_id:
        try:
            await check_room_query_access(room_id, current_user, db)
            has_room_filter = True
        except HTTPException:
            logger.warning(f"Room {room_id} access check failed during clear all; proceeding with user-scoped wipe.")
            has_room_filter = False

    if has_room_filter:
        if getattr(current_user, "role", "user") == "admin":
            conv_query = conv_query.where(Conversation.room_id == room_id)
        else:
            conv_query = conv_query.where(
                or_(
                    Conversation.room_id == room_id,
                    Conversation.user_id == current_user.id,
                )
            )
    else:
        if getattr(current_user, "role", "user") == "admin":
            pass  # Admin can clear all
        else:
            conv_query = conv_query.where(
                or_(Conversation.user_id == current_user.id, Conversation.user_id.is_(None))
            )

    conv_res = await db.execute(conv_query)
    convs = conv_res.scalars().all()
    conv_ids = [c.id for c in convs]

    del_conv_count = len(conv_ids)
    if conv_ids:
        await db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))
        await db.execute(delete(Conversation).where(Conversation.id.in_(conv_ids)))

    # 2. Delete associated memories
    mem_stmt = delete(MemoryItem)
    if has_room_filter:
        if getattr(current_user, "role", "user") == "admin":
            mem_stmt = mem_stmt.where(MemoryItem.room_id == room_id)
        else:
            mem_stmt = mem_stmt.where(
                or_(MemoryItem.room_id == room_id, MemoryItem.user_id == current_user.id)
            )
    elif getattr(current_user, "role", "user") != "admin":
        mem_stmt = mem_stmt.where(MemoryItem.user_id == current_user.id)

    mem_res = await db.execute(mem_stmt)
    del_mem_count = mem_res.rowcount or 0

    await db.commit()

    # Clear hot L1 cache
    try:
        from app.memory.manager import memory_manager
        memory_manager.l1_cache.clear()
    except Exception as e:
        logger.warning(f"Error clearing L1 memory cache during data wipe: {e}")

    return {
        "message": "All conversations, messages, and conversational memory have been permanently deleted.",
        "deleted_conversations": del_conv_count,
        "deleted_memories": del_mem_count,
    }


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_200_OK)
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
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
    request_obj: Request = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Standard non-streaming question answering endpoint with room context resolution."""
    if current_user and not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account access is suspended due to safety policy violations. Reported to authorities.",
        )

    conv_id = request.conversation_id
    effective_room_id, doc_ids = await resolve_room_and_document_ids(
        db, conv_id, request.room_id, request.document_ids, user=current_user
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

    from app.services.pii_service import pii_service
    pii_scan = pii_service.scan_and_mask(request.message)
    user_msg_meta = {}
    if pii_scan.has_pii:
        user_msg_meta = {
            "has_pii_breach": True,
            "breach_count": pii_scan.breach_count,
            "risk_level": pii_scan.risk_level,
            "alert": pii_scan.alert_message,
            "masked_preview": pii_scan.masked_text,
        }

    # Record user message
    user_msg = Message(
        conversation_id=conv_id,
        role="user",
        content=request.message,
        metadata_info=user_msg_meta,
    )
    db.add(user_msg)
    await db.commit()

    # Enforce strict safety guardrails (Illegal, Dangerous, Unethical)
    client_ip = request_obj.client.host if request_obj and request_obj.client else None
    guard_res = await guardrail_service.evaluate_and_enforce(
        query=request.message,
        user=current_user,
        client_ip=client_ip,
        db=db,
    )
    if guard_res.is_blocked:
        meta_payload = {
            "provider": request.provider,
            "model": request.model,
            "response_type": "guardrail_violation",
            "intent": "guardrail_blocked",
            "guardrail_blocked": True,
            "category": guard_res.category,
            "sub_category": guard_res.sub_category,
            "matched_term": guard_res.matched_term,
            "strike_count": guard_res.strike_count,
            "max_strikes": guard_res.max_strikes,
            "is_restricted": guard_res.is_restricted,
            "reported_to_authority": guard_res.reported_to_authority,
            "incident_id": guard_res.incident_id,
            "guardrail_alert": guard_res.caution_notice,
            "retrieval_retry_count": 0,
            "generation_grounded": True,
            "citation_count": 0,
            "consulted_memories_count": 0,
            "consulted_memories": [],
            "room_id": effective_room_id,
            "visualization": None,
        }
        assistant_msg = Message(
            conversation_id=conv_id,
            role="assistant",
            content=guard_res.refusal_message,
            citations=[],
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
            citations=[],
            metadata_info=meta_payload,
            visualization=None,
            created_at=assistant_msg.created_at,
        )

    readiness = await check_document_processing_readiness(db, doc_ids)
    if readiness["only_pending"]:
        pending_names = ", ".join([f"'{d['filename']}'" for d in readiness["pending_docs"]])
        answer = (
            f"⏳ The document(s) in this workspace ({pending_names}) are currently being processed "
            f"in the RabbitMQ queue. Please wait a moment until ingestion is complete, then send your prompt to get responses from the LLM."
        )
        meta_payload = {
            "provider": request.provider,
            "model": request.model,
            "response_type": "queue_pending",
            "intent": "qa",
            "retrieval_retry_count": 0,
            "generation_grounded": False,
            "citation_count": 0,
            "consulted_memories_count": 0,
            "consulted_memories": [],
            "room_id": effective_room_id,
            "visualization": None,
            "queue_pending": True,
            "pending_documents": readiness["pending_docs"],
        }
        assistant_msg = Message(
            conversation_id=conv_id,
            role="assistant",
            content=answer,
            citations=[],
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
            citations=[],
            metadata_info=meta_payload,
            visualization=None,
            created_at=assistant_msg.created_at,
        )

    active_doc_ids = readiness["ready_doc_ids"] if readiness["has_scoped_docs"] else doc_ids

    chat_history = await get_recent_chat_history(db, conv_id, limit=10)

    # Run LangGraph RAG Agent
    state: AgentState = {
        "query": request.message,
        "original_query": request.message,
        "chat_history": chat_history,
        "document_ids": active_doc_ids,
        "user_id": current_user.id if current_user else None,
        "room_id": effective_room_id,
        "memory_context": None,
        "consulted_memories": [],
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
        "needs_visualization": False,
        "visualization": None,
        "answer": "",
        "error": None,
        "status_update": "Starting query",
    }

    final_state = await rag_agent_app.ainvoke(state)
    answer = final_state.get("answer", "No answer generated.")
    visualization_data = final_state.get("visualization")
    citations = [
        c.model_dump() if isinstance(c, Citation) else c
        for c in final_state.get("citations", [])
    ]

    intent = final_state.get("intent", "qa")
    documents = final_state.get("documents", [])
    is_relevant = final_state.get("is_relevant", False)
    retrieval_retry_count = final_state.get("retrieval_retry_count", 0)
    generation_grounded = final_state.get("generation_grounded", True)
    consulted_memories = final_state.get("consulted_memories", [])

    response_type = classify_response_type(intent, documents, is_relevant, citations)

    user_role = getattr(current_user, "role", "user") if current_user else "user"
    is_admin_or_staff = user_role in ("admin", "staff", "staffs")
    visible_consulted_memories = consulted_memories if is_admin_or_staff else []

    is_app_create = final_state.get("is_app_creation", False) or (intent == "app_creation")
    suggested_app_name = final_state.get("suggested_app_name") or "Custom Application Project"
    if is_app_create:
        response_type = "app_creation"

    meta_payload = {
        "provider": request.provider,
        "model": request.model,
        "response_type": response_type,
        "intent": intent,
        "is_app_creation": is_app_create,
        "suggested_app_name": suggested_app_name,
        "communication_channels": ["Gmeet", "Teams", "Zoom", "others"],
        "retrieval_retry_count": retrieval_retry_count,
        "generation_grounded": generation_grounded,
        "citation_count": len(citations),
        "consulted_memories_count": len(visible_consulted_memories),
        "consulted_memories": visible_consulted_memories,
        "room_id": effective_room_id,
        "visualization": visualization_data,
        "pii_breach_alert": pii_scan.alert_message if pii_scan.has_pii else None,
        "pii_masked_preview": pii_scan.masked_text if pii_scan.has_pii else None,
        "pii_breach_count": pii_scan.breach_count,
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

    if current_user:
        try:
            from app.memory.manager import memory_manager
            await memory_manager.record_chat_turn_memory(
                user_id=current_user.id,
                room_id=effective_room_id,
                conversation_id=conv_id,
                query=request.message,
                answer=answer,
                project_id=getattr(conv, "project_id", None) or request.project_id,
                db=db,
            )
        except Exception as mem_err:
            logger.warning(f"Note during chat STM/LTM memory persistence: {mem_err}")

    vis_obj = None
    if visualization_data:
        try:
            vis_obj = VisualizationArtifact.model_validate(visualization_data)
        except Exception:
            pass

    return MessageResponse(
        id=assistant_msg.id,
        conversation_id=conv_id,
        role="assistant",
        content=assistant_msg.content,
        citations=[Citation(**c) for c in citations],
        metadata_info=meta_payload,
        visualization=vis_obj,
        created_at=assistant_msg.created_at,
    )


@router.post(
    "/stream",
    dependencies=[Depends(chat_rate_limiter)],
)
async def stream_query(
    request: ChatRequest,
    request_obj: Request = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Server-Sent Events (SSE) streaming endpoint for real-time RAG responses."""
    if current_user and not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account access is suspended due to safety policy violations. Reported to authorities.",
        )

    conv_id = request.conversation_id
    effective_room_id, doc_ids = await resolve_room_and_document_ids(
        db, conv_id, request.room_id, request.document_ids, user=current_user
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
            user_id=current_user.id,
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

    # Enforce strict safety guardrails (Illegal, Dangerous, Unethical)
    client_ip = request_obj.client.host if request_obj and request_obj.client else None
    guard_res = await guardrail_service.evaluate_and_enforce(
        query=request.message,
        user=current_user,
        client_ip=client_ip,
        db=db,
    )
    if guard_res.is_blocked:
        meta_payload = {
            "provider": request.provider,
            "model": request.model,
            "response_type": "guardrail_violation",
            "intent": "guardrail_blocked",
            "guardrail_blocked": True,
            "category": guard_res.category,
            "sub_category": guard_res.sub_category,
            "matched_term": guard_res.matched_term,
            "strike_count": guard_res.strike_count,
            "max_strikes": guard_res.max_strikes,
            "is_restricted": guard_res.is_restricted,
            "reported_to_authority": guard_res.reported_to_authority,
            "incident_id": guard_res.incident_id,
            "guardrail_alert": guard_res.caution_notice,
            "room_id": effective_room_id,
        }
        answer = guard_res.refusal_message

        async def stream_guardrail_refusal():
            yield f"event: status\ndata: {json.dumps({'message': 'Safety Guardrail triggered: Prohibited inquiry blocked.'})}\n\n"
            yield f"event: meta\ndata: {json.dumps(meta_payload)}\n\n"
            chunk_size = 4
            for i in range(0, len(answer), chunk_size):
                yield f"event: token\ndata: {json.dumps({'token': answer[i:i+chunk_size]})}\n\n"
                await asyncio.sleep(0.01)
            yield f"event: done\ndata: {json.dumps({'answer': answer, 'citations': [], **meta_payload})}\n\n"

            async with database.AsyncSessionLocal() as s_db:
                msg = Message(
                    conversation_id=conv_id,
                    role="assistant",
                    content=answer,
                    citations=[],
                    metadata_info=meta_payload,
                )
                s_db.add(msg)
                await s_db.commit()

        return StreamingResponse(
            stream_guardrail_refusal(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    readiness = await check_document_processing_readiness(db, doc_ids)
    if readiness["only_pending"]:
        pending_names = ", ".join([f"'{d['filename']}'" for d in readiness["pending_docs"]])
        answer = (
            f"⏳ The document(s) in this workspace ({pending_names}) are currently being processed "
            f"in the RabbitMQ queue. Please wait a moment until ingestion is complete, then send your prompt to get responses from the LLM."
        )

        async def stream_pending_queue():
            meta = {
                "provider": request.provider,
                "model": request.model,
                "response_type": "queue_pending",
                "queue_pending": True,
                "pending_documents": readiness["pending_docs"],
                "room_id": effective_room_id,
            }
            yield f"event: status\ndata: {json.dumps({'message': 'Documents processing in RabbitMQ queue...'})}\n\n"
            yield f"event: meta\ndata: {json.dumps(meta)}\n\n"
            chunk_size = 4
            for i in range(0, len(answer), chunk_size):
                yield f"event: token\ndata: {json.dumps({'token': answer[i:i+chunk_size]})}\n\n"
                await asyncio.sleep(0.01)
            yield f"event: done\ndata: {json.dumps({'answer': answer, 'citations': [], **meta})}\n\n"

            # Persist assistant message in DB
            async with database.AsyncSessionLocal() as s_db:
                msg = Message(
                    conversation_id=conv_id,
                    role="assistant",
                    content=answer,
                    citations=[],
                    metadata_info=meta,
                )
                s_db.add(msg)
                await s_db.commit()

        return StreamingResponse(
            stream_pending_queue(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    active_doc_ids = readiness["ready_doc_ids"] if readiness["has_scoped_docs"] else doc_ids
    history = await get_recent_chat_history(db, conv_id, limit=10)

    return StreamingResponse(
        stream_rag_agent(
            query=request.message,
            conversation_id=conv_id,
            chat_history=history,
            document_ids=active_doc_ids,
            user_id=current_user.id if current_user else None,
            room_id=effective_room_id,
            provider=request.provider,
            model=request.model,
            temperature=request.temperature or 0.2,
            top_k=request.top_k or 4,
            user_role=getattr(current_user, "role", "user") if current_user else "user",
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
