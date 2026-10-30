"""API endpoints for document upload, listing, details, deletion, and reprocessing."""

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_user
from app.core.logging import logger
from app.core.rate_limit import RateLimiter
from app.database import get_db
from app.services.event_broadcaster import event_broadcaster
from app.ingestion.pipeline import ingestion_pipeline
from app.models.document import AuditLog, Document, DocumentChunk
from app.models.user import User
from app.schemas.document import (
    AuditLogResponse,
    DocumentAuditTrailResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentShareRequest,
    DocumentUploadResult,
    EvidenceLookupResponse,
)
from app.services.document_service import (
    build_document_list_queries,
    get_document_mime_type,
    process_document_upload,
    verify_document_access,
    verify_document_deletion_access,
)
from app.config import get_settings
from app.services.evidence_service import evidence_extractor

settings = get_settings()
router = APIRouter(prefix="/documents", tags=["documents"])
document_upload_rate_limiter = RateLimiter(max_requests=getattr(settings, "RATE_LIMIT_UPLOAD_MAX", 15), window_seconds=60)


from app.services.queue_service import queue_service

@router.post(
    "/upload",
    response_model=DocumentUploadResult,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(document_upload_rate_limiter)],
)
async def upload_documents(
    background_tasks: BackgroundTasks,
    request: Request,
    files: List[UploadFile] = File(...),
    is_shared: bool = Query(False, description="Whether uploaded documents are public to all users"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload one or more documents (authentication required) and create verifiable audit trail."""
    uploaded_docs: List[DocumentResponse] = []
    failed_files: List[dict] = []

    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "127.0.0.1")
    )
    user_agent = request.headers.get("user-agent", "")[:500]

    any_duplicate_completed = False
    any_duplicate_processing = False
    docs_to_enqueue: List[str] = []

    for file in files:
        try:
            doc, should_enqueue, reason = await process_document_upload(
                file=file,
                current_user=current_user,
                client_ip=client_ip,
                user_agent=user_agent,
                db=db,
                is_shared=is_shared,
            )
            if should_enqueue:
                docs_to_enqueue.append(doc.id)
            if reason == "duplicate_completed":
                any_duplicate_completed = True
            elif reason == "duplicate_processing":
                any_duplicate_processing = True
            uploaded_docs.append(DocumentResponse.model_validate(doc))
        except Exception as e:
            logger.warning(f"Upload failed for file '{file.filename}': {e}", exc_info=True)
            failed_files.append({"filename": file.filename or "unknown", "error": str(e)})

    # CRITICAL: Commit database transaction BEFORE publishing to RabbitMQ
    # so background worker immediately finds the committed document record in PostgreSQL!
    await db.commit()

    for doc_id in docs_to_enqueue:
        await queue_service.enqueue_document_job(doc_id, background_tasks=background_tasks)
        await event_broadcaster.broadcast_document_status(
            document_id=doc_id,
            status="queued",
            user_id=current_user.id,
        )

    if any_duplicate_completed and len(uploaded_docs) == 1:
        message = f"File '{files[0].filename}' is already uploaded and indexed. Reused existing document (skipped duplicate embedding)."
    elif any_duplicate_processing and len(uploaded_docs) == 1:
        message = f"File '{files[0].filename}' is already actively being indexed by the background worker."
    else:
        message = f"Uploaded {len(uploaded_docs)} file(s) for indexing by @{current_user.username}."
        if any_duplicate_completed:
            message += " (Existing indexed file(s) reused to prevent duplicate vector embedding)"
        if any_duplicate_processing:
            message += " (Active background jobs monitored)"
    if failed_files:
        message += f" ({len(failed_files)} file(s) failed validation)"

    return DocumentUploadResult(
        message=message,
        uploaded=uploaded_docs,
        failed=failed_files,
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    status_filter: Optional[str] = Query(None, alias="status"),
    scope: Optional[str] = Query("all", description="Document scope: 'mine', 'shared', or 'all'"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """List documents with per-user ownership and persistent shared filtering options."""
    query, count_query = build_document_list_queries(status_filter, scope, current_user)
    query = query.order_by(Document.created_at.desc()).offset(skip).limit(limit)

    total_res = await db.execute(count_query)
    total = total_res.scalar_one()

    results = await db.execute(query)
    docs = results.scalars().all()

    doc_items = [DocumentResponse.model_validate(d) for d in docs]
    return DocumentListResponse(
        total=total,
        items=doc_items,
        documents=doc_items,
    )


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document_details(document_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve details and indexed chunks of a specific document."""
    res = await db.execute(select(Document).where(Document.id == document_id))
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    return DocumentDetailResponse.model_validate(doc)


# High-concurrency in-memory document metadata cache with bounded size and TTL
_DOCUMENT_META_CACHE: Dict[str, Tuple[dict, float]] = {}
_DOC_CACHE_MAX_SIZE = 5000


def get_cached_doc_meta(doc_id: str) -> Optional[dict]:
    """Retrieve document metadata from in-memory cache if still valid."""
    entry = _DOCUMENT_META_CACHE.get(doc_id)
    if entry:
        meta, expires_at = entry
        if time.time() < expires_at:
            return meta
        _DOCUMENT_META_CACHE.pop(doc_id, None)
    return None


def set_cached_doc_meta(doc: Document) -> None:
    """Store document metadata in in-memory cache."""
    ttl = float(getattr(settings, "DOC_META_CACHE_TTL_SECONDS", 120))
    if len(_DOCUMENT_META_CACHE) > _DOC_CACHE_MAX_SIZE:
        now = time.time()
        expired = [k for k, (_, exp) in _DOCUMENT_META_CACHE.items() if now >= exp]
        for k in expired:
            _DOCUMENT_META_CACHE.pop(k, None)
        if len(_DOCUMENT_META_CACHE) > _DOC_CACHE_MAX_SIZE:
            _DOCUMENT_META_CACHE.clear()
    _DOCUMENT_META_CACHE[doc.id] = (
        {
            "id": doc.id,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "storage_path": doc.storage_path,
            "user_id": doc.user_id,
            "is_shared": getattr(doc, "is_shared", False),
        },
        time.time() + ttl,
    )


def invalidate_doc_meta_cache(doc_id: str) -> None:
    """Invalidate cached document metadata on modification or deletion."""
    _DOCUMENT_META_CACHE.pop(doc_id, None)


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: str,
    request: Request,
    token: Optional[str] = Query(None),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Serve the raw document file inline with proper content-type, ETag, and high-concurrency connection release."""
    meta = get_cached_doc_meta(document_id)
    if meta is None:
        res = await db.execute(select(Document).where(Document.id == document_id))
        doc = res.scalar_one_or_none()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found.")
        set_cached_doc_meta(doc)
        storage_path = doc.storage_path
        filename = doc.filename
        file_type = doc.file_type
        await verify_document_access(doc, current_user, db, "view this document")
    else:
        storage_path = meta["storage_path"]
        filename = meta["filename"]
        file_type = meta["file_type"]
        user_id = meta["user_id"]
        is_shared = meta["is_shared"]

        # Fast in-memory permission check
        has_access = False
        if is_shared:
            has_access = True
        elif current_user and (user_id == current_user.id or getattr(current_user, "role", "user") == "admin"):
            has_access = True

        if not has_access:
            # Fall back to DB check for room-level membership
            res = await db.execute(select(Document).where(Document.id == document_id))
            doc = res.scalar_one_or_none()
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found.")
            await verify_document_access(doc, current_user, db, "view this document")

    # CRITICAL: Release database session immediately so the connection returns
    # to the pool BEFORE file streaming begins!
    if db.is_active:
        await db.close()

    file_path = Path(storage_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Document file not found on disk.")

    # High-performance conditional request handling (HTTP 304 Not Modified)
    stat = file_path.stat()
    etag = f'"{stat.st_mtime_ns}-{stat.st_size}"'
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and if_none_match.strip('"') == etag.strip('"'):
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={
                "ETag": etag,
                "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
            },
        )

    media_type = get_document_mime_type(file_type)

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
            "ETag": etag,
        },
    )


@router.get("/{document_id}/evidence", response_model=EvidenceLookupResponse)
async def get_document_evidence(
    document_id: str,
    request: Request,
    page: int = Query(1, ge=1),
    chunk_id: Optional[str] = Query(None),
    query: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve realtime document evidence: page text, highlighted matching lines, and metadata."""
    res = await db.execute(select(Document).where(Document.id == document_id))
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    await verify_document_access(doc, current_user, db, "view this document evidence")

    chunk_obj: Optional[DocumentChunk] = None
    if chunk_id:
        c_res = await db.execute(
            select(DocumentChunk).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.id == chunk_id,
            )
        )
        chunk_obj = c_res.scalars().first()
        if not chunk_obj and "_c" in chunk_id:
            try:
                c_idx = int(chunk_id.split("_c")[-1])
                c_res2 = await db.execute(
                    select(DocumentChunk).where(
                        DocumentChunk.document_id == document_id,
                        DocumentChunk.chunk_index == c_idx,
                    )
                )
                chunk_obj = c_res2.scalars().first()
            except Exception:
                chunk_obj = None

    active_token = token or request.query_params.get("token") or (
        request.headers.get("Authorization", "")[7:].strip()
        if request.headers.get("Authorization", "").startswith("Bearer ")
        else None
    )

    return evidence_extractor.build_evidence_response(
        doc=doc,
        page=page,
        chunk_obj=chunk_obj,
        query=query,
        token=active_token,
    )


@router.delete("/{document_id}", status_code=status.HTTP_200_OK)
async def delete_document(
    document_id: str,
    purge_vectors: bool = Query(False, description="Whether to also purge persistent vector embeddings from Chroma"),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document record, preserving persistent vector embeddings for other users unless purge_vectors=True."""
    res = await db.execute(select(Document).where(Document.id == document_id))
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    await verify_document_deletion_access(doc, current_user, db)

    try:
        audit_del = AuditLog(
            id=str(uuid.uuid4()),
            user_id=current_user.id if current_user else None,
            username=current_user.username if current_user else "anonymous",
            user_email=current_user.email if current_user else None,
            action="document_delete",
            entity_type="document",
            entity_id=document_id,
            details={
                "filename": doc.filename,
                "file_size": doc.file_size,
                "purge_vectors": purge_vectors,
            },
        )
        db.add(audit_del)
        await db.flush()
    except Exception as e:
        logger.warning(f"Error recording audit log for document delete: {e}")

    success = await ingestion_pipeline.delete_document(db, document_id, purge_vectors=purge_vectors)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found.")

    invalidate_doc_meta_cache(document_id)

    msg = (
        "Document and associated vectors completely deleted."
        if purge_vectors
        else "Document record deleted. Vector embeddings remain persistent for shared platform RAG."
    )
    return {"message": msg, "document_id": document_id, "persistent_vectors_retained": not purge_vectors}


@router.post("/{document_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def reprocess_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger re-ingestion of an existing document."""
    res = await db.execute(select(Document).where(Document.id == document_id))
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    if doc.user_id is not None:
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to reprocess this document.",
            )
        if doc.user_id != current_user.id and getattr(current_user, "role", "user") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied to reprocess this document.",
            )

    # Prevent enqueuing duplicate job if document is already actively being processed by worker
    if doc.status == "processing":
        last_activity = doc.updated_at or doc.created_at
        now = datetime.now(timezone.utc)
        if last_activity:
            if last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=timezone.utc)
            timeout_sec = getattr(settings, "DOCUMENT_PROCESSING_TIMEOUT_SECONDS", 600)
            elapsed = (now - last_activity).total_seconds()
            if elapsed < timeout_sec:
                return {
                    "message": f"Document '{doc.filename}' is already actively being processed by the background worker ({int(elapsed)}s elapsed).",
                    "document_id": document_id,
                    "already_processing": True,
                }

    doc.status = "queued"
    doc.error_message = None

    try:
        audit_rep = AuditLog(
            id=str(uuid.uuid4()),
            user_id=current_user.id if current_user else None,
            username=current_user.username if current_user else "anonymous",
            user_email=current_user.email if current_user else None,
            action="document_reprocess",
            entity_type="document",
            entity_id=document_id,
            details={"filename": doc.filename},
        )
        db.add(audit_rep)
    except Exception:
        pass

    await db.commit()
    queue_res = await queue_service.enqueue_document_job(document_id, background_tasks=background_tasks)
    await event_broadcaster.broadcast_document_status(
        document_id=doc.id,
        status="queued",
        filename=doc.filename,
        user_id=doc.user_id,
    )
    return {
        "message": f"Document re-ingestion queued via {queue_res.get('mechanism', 'queue')}.",
        "document_id": document_id,
        "queue_details": queue_res,
    }


@router.get("/events/stream")
async def stream_document_events(
    request: Request,
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Server-Sent Events (SSE) endpoint to push real-time document processing and chunking updates.

    Eliminates repetitive interval polling from client browsers.
    Supports JWT via Authorization Bearer header, URL query param (?token=...), or cookie.
    """
    queue = await event_broadcaster.subscribe()

    async def event_generator():
        try:
            # Initial handshake event confirming SSE stream connection
            init_payload = {
                "status": "connected",
                "user_id": current_user.id if current_user else None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            yield f"event: connected\ndata: {json.dumps(init_payload)}\n\n"

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    # Filter events: if document is owned by a user, only send to that user unless shared
                    event_user_id = event.get("user_id")
                    if current_user and event_user_id and event_user_id != current_user.id:
                        if not event.get("is_shared", False):
                            continue

                    yield f"event: document_status\ndata: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive ping every 15s to maintain HTTP stream across proxies/gateways
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await event_broadcaster.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/queue/status")
async def get_queue_status():
    """Retrieve RabbitMQ queue health, broker connectivity, and workload statistics."""
    return await queue_service.check_health()


@router.get("/readiness/check")
async def check_documents_readiness(
    room_id: Optional[str] = Query(None),
    document_ids: Optional[str] = Query(None, description="Comma-separated list of document IDs"),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Check readiness status of documents for LLM prompts (queued/processing vs completed)."""
    from app.services.conversation_service import resolve_room_and_document_ids

    doc_id_list = [d.strip() for d in document_ids.split(",") if d.strip()] if document_ids else None
    _, resolved_doc_ids = await resolve_room_and_document_ids(
        db, None, room_id, doc_id_list, user=current_user
    )

    if not resolved_doc_ids or resolved_doc_ids == ["__none__"]:
        return {
            "all_ready": True,
            "total": 0,
            "ready_count": 0,
            "pending_count": 0,
            "failed_count": 0,
            "can_prompt": True,
            "documents": [],
            "message": "No documents attached to current scope. General LLM prompts ready.",
        }

    stmt = select(Document).where(Document.id.in_(resolved_doc_ids))
    results = await db.execute(stmt)
    docs = results.scalars().all()

    # Automatically identify and recover stale / orphaned processing documents
    timeout_sec = getattr(settings, "DOCUMENT_PROCESSING_TIMEOUT_SECONDS", 600)
    now = datetime.now(timezone.utc)
    has_stale = False

    for d in docs:
        last_activity = d.updated_at or d.created_at
        if last_activity:
            if last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=timezone.utc)
            elapsed = (now - last_activity).total_seconds()

            if d.status == "queued":
                if elapsed > timeout_sec:
                    d.status = "failed"
                    d.error_message = (
                        f"Document queuing timed out after {int(elapsed // 60)}m. Please click reprocess to retry."
                    )
                    has_stale = True
                elif elapsed > 15:
                    # Self-healing: if stuck in queued without a worker picking it up, re-enqueue
                    d.updated_at = now
                    has_stale = True
                    logger.info(
                        f"Auto-healing queued document {d.id} ({d.filename}): idle for {int(elapsed)}s. Re-dispatching to worker queue."
                    )
                    await queue_service.enqueue_document_job(d.id)
            elif d.status == "processing":
                if elapsed > timeout_sec:
                    d.status = "failed"
                    d.error_message = (
                        f"Document processing timed out after {int(elapsed // 60)}m (exceeded {timeout_sec // 60}m limit) "
                        "or worker was interrupted. Please click reprocess to retry."
                    )
                    has_stale = True
                    logger.warning(
                        f"Auto-recovered stale document {d.id} ({d.filename}): marked as failed after {int(elapsed)}s."
                    )

    if has_stale:
        await db.commit()

    total = len(docs)
    ready = [d for d in docs if d.status == "completed"]
    pending = [d for d in docs if d.status in ("queued", "processing")]
    failed = [d for d in docs if d.status == "failed"]

    all_ready = len(ready) == total and total > 0
    can_prompt = len(ready) > 0 or total == 0

    return {
        "all_ready": all_ready,
        "total": total,
        "ready_count": len(ready),
        "pending_count": len(pending),
        "failed_count": len(failed),
        "can_prompt": can_prompt,
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "status": d.status,
                "is_ready": d.status == "completed",
                "chunk_count": d.chunk_count,
                "error_message": d.error_message,
            }
            for d in docs
        ],
        "message": (
            "All documents ready for LLM prompts."
            if all_ready
            else (
                f"{len(pending)} document(s) currently being processed in RabbitMQ queue. LLM ready when completed."
                if pending
                else (
                    f"{len(failed)} document(s) encountered indexing errors or timed out."
                    if failed
                    else "Ready."
                )
            )
        ),
    }


@router.get("/{document_id}/audit", response_model=DocumentAuditTrailResponse)
async def get_document_audit_trail(
    document_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve complete verified audit trail and uploader details for a document."""
    res = await db.execute(select(Document).where(Document.id == document_id))
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    audit_res = await db.execute(
        select(AuditLog)
        .where(AuditLog.entity_id == document_id)
        .order_by(AuditLog.created_at.desc())
    )
    events = audit_res.scalars().all()

    return DocumentAuditTrailResponse(
        document_id=doc.id,
        filename=doc.filename,
        uploader_id=doc.user_id,
        uploader_username=doc.uploader_username,
        uploader_email=doc.uploader_email,
        client_ip=doc.client_ip,
        user_agent=doc.user_agent,
        uploaded_at=doc.created_at,
        events=[AuditLogResponse.model_validate(e) for e in events],
    )


@router.patch("/{document_id}/share", response_model=DocumentResponse)
async def toggle_document_share(
    document_id: str,
    share_req: DocumentShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Toggle document public sharing (only owner or admin)."""
    res = await db.execute(select(Document).where(Document.id == document_id))
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    is_owner = doc.user_id == current_user.id
    is_admin = getattr(current_user, "role", "user") == "admin"
    if not (is_owner or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: only document owner or admin can update sharing settings.",
        )

    doc.is_shared = share_req.is_shared
    await db.commit()
    await db.refresh(doc)
    invalidate_doc_meta_cache(document_id)
    return DocumentResponse.model_validate(doc)

