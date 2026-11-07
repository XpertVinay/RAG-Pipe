"""FastAPI router for Memory Management, Distribution Inspection, and Document Revaluation."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_user, require_admin_or_staff
from app.database import get_db
from app.memory.manager import memory_manager
from app.memory.revaluation import revaluation_engine
from app.memory.schemas import (
    MemoryCreate,
    MemoryDistributionStats,
    MemoryResponse,
    MemoryRevaluationRequest,
    MemoryRevaluationResult,
)
from app.models.memory import MemoryItem, MemoryScope, MemoryType
from app.models.user import User
from app.memory.quick_eval import CompactMemoryEvalResponse, quick_memory_evaluator

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("", response_model=List[MemoryResponse])
async def list_memories(
    scope: Optional[str] = Query(None, description="'global' or 'user_specific'"),
    memory_type: Optional[str] = Query(None, description="'short_term' or 'long_term'"),
    document_id: Optional[str] = Query(None),
    room_id: Optional[str] = Query(None),
    include_expired: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_admin_or_staff),
    db: AsyncSession = Depends(get_db),
):
    """List memory items filtered by scope, type, and ownership (restricted to admin and staff)."""
    query = select(MemoryItem)

    # Scoping filter
    if scope:
        query = query.where(MemoryItem.scope == scope)

    if memory_type:
        query = query.where(MemoryItem.memory_type == memory_type)

    if document_id:
        query = query.where(MemoryItem.document_id == document_id)

    if room_id:
        query = query.where(MemoryItem.room_id == room_id)

    # If staff (not admin) viewing user_specific, filter to own user memories
    if getattr(current_user, "role", "user") != "admin":
        if scope == MemoryScope.USER_SPECIFIC.value:
            query = query.where(MemoryItem.user_id == current_user.id)

    query = query.order_by(MemoryItem.importance.desc(), MemoryItem.updated_at.desc()).limit(limit)
    res = await db.execute(query)
    items = res.scalars().all()

    output = []
    for item in items:
        if not include_expired and item.is_expired():
            continue
        try:
            resp = MemoryResponse(
                id=item.id,
                scope=item.scope,
                memory_type=item.memory_type,
                user_id=item.user_id,
                room_id=item.room_id,
                document_id=item.document_id,
                document_hash=item.document_hash,
                key=item.key,
                content=item.content,
                importance=item.importance,
                metadata_payload=item.metadata_payload or {},
                created_at=item.created_at,
                updated_at=item.updated_at,
                expires_at=item.expires_at,
                revaluated_at=item.revaluated_at,
                revaluation_interval_seconds=item.revaluation_interval_seconds,
                access_count=item.access_count,
                is_expired=item.is_expired(),
                needs_revaluation=item.needs_revaluation(),
            )
            output.append(resp)
        except Exception as e:
            # Skip invalid memory item gracefully and continue
            continue

    return output


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_or_update_memory(
    payload: MemoryCreate,
    current_user: User = Depends(require_admin_or_staff),
    db: AsyncSession = Depends(get_db),
):
    """Store or update a memory item with low-memory footprint and automatic TTL (admin & staff only)."""
    # Enforce user_id for user_specific memories
    effective_user_id = payload.user_id
    if payload.scope == MemoryScope.USER_SPECIFIC.value:
        if not effective_user_id and current_user:
            effective_user_id = current_user.id

    saved = await memory_manager.store_memory(
        scope=payload.scope,
        memory_type=payload.memory_type,
        key=payload.key,
        content=payload.content,
        user_id=effective_user_id,
        room_id=payload.room_id,
        document_id=payload.document_id,
        document_hash=payload.document_hash,
        ttl_seconds=payload.ttl_seconds,
        revaluation_interval_seconds=payload.revaluation_interval_seconds or 86400,
        importance=payload.importance,
        metadata_payload=payload.metadata_payload,
        db=db,
    )

    return MemoryResponse(
        id=saved.id,
        scope=saved.scope,
        memory_type=saved.memory_type,
        user_id=saved.user_id,
        room_id=saved.room_id,
        document_id=saved.document_id,
        document_hash=saved.document_hash,
        key=saved.key,
        content=saved.content,
        importance=saved.importance,
        metadata_payload=saved.metadata_payload or {},
        created_at=saved.created_at,
        updated_at=saved.updated_at,
        expires_at=saved.expires_at,
        revaluated_at=saved.revaluated_at,
        revaluation_interval_seconds=saved.revaluation_interval_seconds,
        access_count=saved.access_count,
        is_expired=saved.is_expired(),
        needs_revaluation=saved.needs_revaluation(),
    )


@router.get("/stats", response_model=MemoryDistributionStats)
async def get_memory_distribution_stats(
    current_user: User = Depends(require_admin_or_staff),
    db: AsyncSession = Depends(get_db),
):
    """Return complete distribution matrix and low-memory performance stats (admin & staff only)."""
    return await memory_manager.get_distribution_stats(db=db)


@router.post("/revaluate", response_model=MemoryRevaluationResult)
async def trigger_revaluation(
    request: MemoryRevaluationRequest,
    current_user: User = Depends(require_admin_or_staff),
    db: AsyncSession = Depends(get_db),
):
    """Trigger on-demand document revaluation and update stale memory context (admin & staff only)."""
    if request.document_id:
        count = await revaluation_engine.revaluate_for_document(request.document_id, db)
        return MemoryRevaluationResult(
            scanned_count=count,
            revaluated_count=count,
            updated_keys=[f"document:{request.document_id}"],
            expired_pruned_count=0,
            message=f"Revaluated {count} memories for document {request.document_id}.",
        )

    # Scan all
    scan_res = await revaluation_engine.scan_and_revaluate_all(db=db, limit=100)
    return MemoryRevaluationResult(
        scanned_count=scan_res["scanned_count"],
        revaluated_count=scan_res["revaluated_count"],
        updated_keys=scan_res["updated_keys"],
        expired_pruned_count=scan_res["expired_pruned_count"],
        message=f"Scanned {scan_res['scanned_count']} memories; revaluated {scan_res['revaluated_count']} stale contexts.",
    )


@router.delete("/prune", status_code=status.HTTP_200_OK)
async def prune_expired_memories(
    current_user: User = Depends(require_admin_or_staff),
    db: AsyncSession = Depends(get_db),
):
    """Purge all expired memories to minimize disk and memory consumption (admin & staff only)."""
    pruned = await memory_manager.prune_expired(db=db)
    return {"message": f"Successfully pruned {pruned} expired memories.", "pruned_count": pruned}


@router.delete("/{memory_id}", status_code=status.HTTP_200_OK)
async def delete_memory(
    memory_id: str,
    current_user: User = Depends(require_admin_or_staff),
    db: AsyncSession = Depends(get_db),
):
    """Delete a specific memory item (admin & staff only)."""
    res = await db.execute(select(MemoryItem).where(MemoryItem.id == memory_id))
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Memory item not found.")

    if item.user_id and getattr(current_user, "role", "user") != "admin":
        if item.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Forbidden.")

    await db.delete(item)
    await db.commit()
    # Also invalidate in L1
    memory_manager.l1_cache._evict_key(
        memory_manager.l1_cache._make_cache_key(item.scope, item.key, item.user_id)
    )
    return {"message": "Memory deleted.", "id": memory_id}


@router.get("/quick-eval", response_model=CompactMemoryEvalResponse)
async def get_compact_memory_eval(
    room_id: Optional[str] = Query(None, description="Room workspace ID"),
    project_id: Optional[str] = Query(None, description="Project ID"),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate compact + meaning-rich short-term and long-term memory synthesis for instant evaluation in new chats/rooms."""
    user_id = current_user.id if current_user else None
    return await quick_memory_evaluator.evaluate_room_context(
        db=db,
        room_id=room_id,
        project_id=project_id,
        user_id=user_id,
    )

