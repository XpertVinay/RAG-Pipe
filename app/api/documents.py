"""API endpoints for document upload, listing, details, deletion, and reprocessing."""

import hashlib
import re
import shutil
import uuid
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from pypdf import PdfReader
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.auth import get_current_user, get_optional_user, utc_now
from app.core.exceptions import EntityNotFoundError, FileValidationError
from app.core.logging import logger
from app.core.rate_limit import RateLimiter
from app.core.security import validate_file_upload, verify_safe_path
from app.database import get_db
from app.ingestion.pipeline import ingestion_pipeline
from app.models.document import Document, DocumentChunk, AuditLog
from app.models.room import Room, RoomDocument
from app.models.user import User
from app.schemas.document import (
    AuditLogResponse,
    DocumentAuditTrailResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResult,
    EvidenceHighlightLine,
    EvidenceLookupResponse,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])
settings = get_settings()

document_upload_rate_limiter = RateLimiter(max_requests=15, window_seconds=60)


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

    for file in files:
        try:
            # Read first chunk or entire file into memory to compute size and hash
            content = await file.read()
            content_length = len(content)

            sanitized_name, extension = validate_file_upload(file, content_length, content_bytes=content)

            if content_length == 0:
                raise FileValidationError(f"File '{file.filename}' is empty.")

            file_hash = hashlib.sha256(content).hexdigest()

            # Save file to storage directory safely
            doc_id = str(uuid.uuid4())
            target_filename = f"{doc_id}_{sanitized_name}"
            target_path = settings.UPLOAD_DIR / target_filename
            safe_path = verify_safe_path(target_path, settings.UPLOAD_DIR)

            with open(safe_path, "wb") as f:
                f.write(content)

            audit_meta = {
                "uploader": {
                    "id": current_user.id,
                    "username": current_user.username,
                    "email": current_user.email,
                    "full_name": current_user.full_name,
                    "role": current_user.role,
                },
                "client_ip": client_ip,
                "user_agent": user_agent,
                "uploaded_at": utc_now().isoformat(),
            }

            # Insert document row into database with full uploader identity & audit metadata
            doc = Document(
                id=doc_id,
                user_id=current_user.id,
                uploader_username=current_user.username,
                uploader_email=current_user.email,
                client_ip=client_ip,
                user_agent=user_agent,
                audit_metadata=audit_meta,
                is_persistent_vector=True,
                is_shared=True,
                filename=sanitized_name,
                file_type=extension,
                file_size=content_length,
                storage_path=str(safe_path),
                file_hash=file_hash,
                status="queued",
            )
            db.add(doc)
            await db.flush()

            # Create immutable audit log record for document creation
            audit_entry = AuditLog(
                id=str(uuid.uuid4()),
                user_id=current_user.id,
                username=current_user.username,
                user_email=current_user.email,
                action="document_upload",
                entity_type="document",
                entity_id=doc_id,
                client_ip=client_ip,
                user_agent=user_agent,
                details={
                    "filename": sanitized_name,
                    "file_size": content_length,
                    "file_type": extension,
                    "file_hash": file_hash,
                },
            )
            db.add(audit_entry)

            # Schedule background ingestion
            background_tasks.add_task(ingestion_pipeline.process_document, doc_id)

            uploaded_docs.append(DocumentResponse.model_validate(doc))

        except Exception as e:
            logger.warning(f"Upload failed for file '{file.filename}': {e}")
            failed_files.append({"filename": file.filename or "unknown", "error": str(e)})

    await db.commit()

    message = f"Uploaded {len(uploaded_docs)} file(s) for indexing by @{current_user.username}."
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
    query = select(Document)
    count_query = select(func.count(Document.id))

    if status_filter:
        query = query.where(Document.status == status_filter)
        count_query = count_query.where(Document.status == status_filter)

    if scope == "mine":
        if current_user:
            query = query.where(Document.user_id == current_user.id)
            count_query = count_query.where(Document.user_id == current_user.id)
        else:
            query = query.where(Document.id == "__none__")
            count_query = count_query.where(Document.id == "__none__")
    elif scope == "shared":
        if current_user:
            query = query.where(Document.is_shared.is_(True))
            count_query = count_query.where(Document.is_shared.is_(True))
        else:
            query = query.where(Document.id == "__none__")
            count_query = count_query.where(Document.id == "__none__")
    else:  # "all"
        if current_user:
            if getattr(current_user, "role", "user") == "admin":
                pass
            else:
                query = query.where(or_(Document.user_id == current_user.id, Document.is_shared.is_(True), Document.user_id.is_(None)))
                count_query = count_query.where(or_(Document.user_id == current_user.id, Document.is_shared.is_(True), Document.user_id.is_(None)))
        else:
            # Unauthenticated (logged out) visitor must NOT see user documents
            query = query.where(Document.user_id.is_(None))
            count_query = count_query.where(Document.user_id.is_(None))

    query = query.order_by(Document.created_at.desc()).offset(skip).limit(limit)

    total_res = await db.execute(count_query)
    total = total_res.scalar_one()

    results = await db.execute(query)
    docs = results.scalars().all()

    return DocumentListResponse(
        total=total,
        items=[DocumentResponse.model_validate(d) for d in docs],
    )


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document_details(document_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve details and indexed chunks of a specific document."""
    res = await db.execute(select(Document).where(Document.id == document_id))
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    return DocumentDetailResponse.model_validate(doc)


async def verify_document_access(
    doc: Document,
    user: Optional[User],
    db: AsyncSession,
    action_label: str = "view this document",
) -> None:
    """Verify that user has read access to document, considering ownership, admin role, or shared room membership."""
    if doc.user_id is None:
        # Document was uploaded in an open/anonymous session
        return

    # 1. Check if the document belongs to a public room (where Room.user_id is NULL)
    rd_pub = await db.execute(
        select(Room)
        .join(RoomDocument, Room.id == RoomDocument.room_id)
        .where(
            RoomDocument.document_id == doc.id,
            Room.user_id.is_(None),
        )
    )
    if rd_pub.scalar_one_or_none() is not None:
        return

    # 2. Document is private: authentication is mandatory
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication required to {action_label}.",
        )

    # 3. Direct owner or admin
    if doc.user_id == user.id or getattr(user, "role", "user") == "admin":
        return

    # 4. Check if document belongs to a room owned by this user
    rd_user = await db.execute(
        select(Room)
        .join(RoomDocument, Room.id == RoomDocument.room_id)
        .where(
            RoomDocument.document_id == doc.id,
            Room.user_id == user.id,
        )
    )
    if rd_user.scalar_one_or_none() is not None:
        return

    # Otherwise denied
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Permission denied to {action_label}.",
    )


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: str,
    token: Optional[str] = Query(None),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Serve the raw document file inline with proper content-type for previewing / landing on pages."""
    res = await db.execute(select(Document).where(Document.id == document_id))
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    await verify_document_access(doc, current_user, db, "view this document")

    file_path = Path(doc.storage_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Document file not found on disk.")

    mime_map = {
        "pdf": "application/pdf",
        "txt": "text/plain; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
        "csv": "text/csv; charset=utf-8",
        "html": "text/html; charset=utf-8",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    media_type = mime_map.get(doc.file_type.lower().lstrip("."), "application/octet-stream")

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{doc.filename}"',
            "Cache-Control": "public, max-age=3600",
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

    file_path = Path(doc.storage_path)
    total_pages = 1
    page_text = ""
    chunk_content = None
    chunk_index = None

    # Retrieve chunk if specified
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

        if chunk_obj:
            chunk_content = chunk_obj.content
            chunk_index = chunk_obj.chunk_index
            if not page or page == 1:
                page = chunk_obj.chunk_metadata.get("page", 1)

    # Extract page text from physical file
    if file_path.exists():
        ext = doc.file_type.lower().lstrip(".")
        if ext == "pdf":
            try:
                reader = PdfReader(str(file_path))
                total_pages = max(len(reader.pages), 1)
                target_page = min(max(page, 1), total_pages)
                page = target_page
                page_text = reader.pages[target_page - 1].extract_text() or ""
            except Exception as e:
                logger.warning(f"Error reading PDF page {page}: {e}")
                page_text = ""
        else:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    page_text = f.read()
            except Exception as e:
                logger.warning(f"Error reading file {file_path}: {e}")
                page_text = ""

    # If page_text is empty, fallback to chunk content
    if not page_text and chunk_content:
        page_text = chunk_content

    # Determine matched lines with scoring and highlighting
    match_phrases = []
    if chunk_content:
        for s in re.split(r"[\n.]+", chunk_content):
            s_clean = s.strip()
            if len(s_clean) >= 15:
                match_phrases.append(s_clean.lower())

    query_tokens = [t.lower() for t in re.findall(r"\w+", query or "") if len(t) > 3]

    raw_lines = page_text.split("\n")
    highlight_lines: List[EvidenceHighlightLine] = []

    for idx, line in enumerate(raw_lines, start=1):
        line_clean = line.strip()
        line_lower = line_clean.lower()
        is_match = False
        score = 0.0

        if line_clean:
            # 1. Exact or partial chunk phrase match
            for phrase in match_phrases:
                if phrase in line_lower or line_lower in phrase:
                    is_match = True
                    score = max(score, 0.95)
                    break

            # 2. Query token overlap
            if query_tokens:
                overlap = sum(1 for tok in query_tokens if tok in line_lower)
                if overlap >= 2 or (len(query_tokens) == 1 and overlap == 1):
                    is_match = True
                    score = max(score, round(overlap / len(query_tokens), 2))

        highlight_lines.append(
            EvidenceHighlightLine(
                line_number=idx,
                text=line,
                is_match=is_match,
                score=score,
            )
        )

    active_token = token or request.query_params.get("token") or (
        request.headers.get("Authorization", "")[7:].strip()
        if request.headers.get("Authorization", "").startswith("Bearer ")
        else None
    )
    token_qs = f"?token={active_token}" if active_token else ""
    file_url = f"/api/documents/{doc.id}/file{token_qs}#page={page}"

    return EvidenceLookupResponse(
        document_id=doc.id,
        filename=doc.filename,
        file_type=doc.file_type,
        page=page,
        total_pages=total_pages,
        page_text=page_text,
        file_url=file_url,
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        chunk_content=chunk_content,
        query=query,
        highlight_lines=highlight_lines,
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

    if doc.user_id is not None:
        is_owner = current_user and doc.user_id == current_user.id
        is_admin = current_user and getattr(current_user, "role", "user") == "admin"

        # Check if the document belongs to a public room or a room owned by current_user
        rd_res = await db.execute(
            select(Room)
            .join(RoomDocument, Room.id == RoomDocument.room_id)
            .where(RoomDocument.document_id == doc.id)
        )
        rooms_linked = rd_res.scalars().all()
        is_room_manager = any(
            r.user_id is None or (current_user and r.user_id == current_user.id)
            for r in rooms_linked
        )

        if not (is_owner or is_admin or is_room_manager):
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required to delete this document.",
                )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied to delete this document.",
            )

    # Log audit event for document deletion
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

    doc.status = "queued"
    doc.error_message = None

    # Log audit event for reprocess
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

    background_tasks.add_task(ingestion_pipeline.process_document, document_id)

    return {"message": "Document re-ingestion queued.", "document_id": document_id}


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
