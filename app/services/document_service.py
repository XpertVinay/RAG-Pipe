"""Document service handling file validation, access verification, database queries, and audit logging."""

import hashlib
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.config import get_settings
from app.core.auth import utc_now
from app.core.exceptions import FileValidationError
from app.core.security import validate_file_upload, verify_safe_path
from app.models.document import AuditLog, Document
from app.models.room import Room, RoomDocument, RoomMember
from app.models.user import User

settings = get_settings()

MIME_MAP = {
    "pdf": "application/pdf",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def get_document_mime_type(file_type: str) -> str:
    """Return appropriate MIME media type for given file extension."""
    return MIME_MAP.get(file_type.lower().lstrip("."), "application/octet-stream")


async def verify_document_access(
    doc: Document,
    user: Optional[User],
    db: AsyncSession,
    action_label: str = "view this document",
) -> None:
    """Verify that user has read access to document, considering ownership, admin role, public status, or room membership."""
    # 1. Document is explicitly public
    if getattr(doc, "is_shared", False):
        return

    # 2. Direct owner or admin
    if user and (doc.user_id == user.id or getattr(user, "role", "user") == "admin"):
        return

    # 3. Check if document belongs to a public room (where Room.is_public is True or Room.user_id is NULL)
    rd_pub = await db.execute(
        select(Room)
        .join(RoomDocument, Room.id == RoomDocument.room_id)
        .where(
            RoomDocument.document_id == doc.id,
            or_(Room.is_public.is_(True), Room.user_id.is_(None)),
        )
    )
    if rd_pub.scalar_one_or_none() is not None:
        return

    # 4. Document is private: authentication is mandatory
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication required to {action_label}.",
        )

    # 5. Check if document belongs to a room owned by or shared with this user
    rd_user = await db.execute(
        select(Room)
        .join(RoomDocument, Room.id == RoomDocument.room_id)
        .outerjoin(RoomMember, RoomMember.room_id == Room.id)
        .where(
            RoomDocument.document_id == doc.id,
            or_(Room.user_id == user.id, RoomMember.user_id == user.id),
        )
    )
    if rd_user.scalar_one_or_none() is not None:
        return

    # Otherwise denied
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Permission denied to {action_label}.",
    )


async def verify_document_deletion_access(
    doc: Document,
    current_user: Optional[User],
    db: AsyncSession,
) -> None:
    """Verify user has permission to delete the document."""
    if doc.user_id is None:
        return

    is_owner = current_user and doc.user_id == current_user.id
    is_admin = current_user and getattr(current_user, "role", "user") == "admin"

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


def build_document_list_queries(
    status_filter: Optional[str],
    scope: Optional[str],
    current_user: Optional[User],
) -> Tuple[Select, Select]:
    """Build select query and count query for document listing with user and scope filters and strict RBAC isolation."""
    query = select(Document)
    count_query = select(func.count(Document.id))

    if status_filter:
        query = query.where(Document.status == status_filter)
        count_query = count_query.where(Document.status == status_filter)

    if current_user:
        is_admin = getattr(current_user, "role", "user") == "admin"

        # Subquery for documents attached to rooms accessible to this user
        room_doc_subquery = (
            select(RoomDocument.document_id)
            .join(Room, Room.id == RoomDocument.room_id)
            .outerjoin(RoomMember, RoomMember.room_id == Room.id)
            .where(
                or_(
                    Room.user_id == current_user.id,
                    RoomMember.user_id == current_user.id,
                    Room.is_public.is_(True),
                    Room.user_id.is_(None),
                )
            )
        )

        if scope == "mine":
            query = query.where(Document.user_id == current_user.id)
            count_query = count_query.where(Document.user_id == current_user.id)
        elif scope == "shared":
            # Shared: Public documents OR documents in shared rooms, excluding documents owned by current_user
            shared_condition = or_(
                Document.is_shared.is_(True),
                Document.id.in_(room_doc_subquery),
            )
            # Only show documents from other users or public
            query = query.where(shared_condition, or_(Document.user_id != current_user.id, Document.user_id.is_(None)))
            count_query = count_query.where(shared_condition, or_(Document.user_id != current_user.id, Document.user_id.is_(None)))
        else:  # "all"
            if not is_admin:
                user_condition = or_(
                    Document.user_id == current_user.id,
                    Document.is_shared.is_(True),
                    Document.id.in_(room_doc_subquery),
                )
                query = query.where(user_condition)
                count_query = count_query.where(user_condition)
    else:
        # Anonymous visitor: only explicitly public documents or documents in public rooms
        pub_room_subquery = (
            select(RoomDocument.document_id)
            .join(Room, Room.id == RoomDocument.room_id)
            .where(or_(Room.is_public.is_(True), Room.user_id.is_(None)))
        )
        unauth_condition = or_(
            Document.is_shared.is_(True),
            Document.id.in_(pub_room_subquery),
        )
        query = query.where(unauth_condition)
        count_query = count_query.where(unauth_condition)

    return query, count_query


async def process_document_upload(
    file: UploadFile,
    current_user: User,
    client_ip: str,
    user_agent: str,
    db: AsyncSession,
    is_shared: bool = False,
) -> Tuple[Document, bool, str]:
    """Validate, deduplicate, persist on disk, and create or reuse DB records for an uploaded document.
    
    Returns:
        Tuple[Document, should_enqueue: bool, reason: str]
    """
    content = await file.read()
    content_length = len(content)

    sanitized_name, extension = validate_file_upload(file, content_length, content_bytes=content)

    if content_length == 0:
        raise FileValidationError(f"File '{file.filename}' is empty.")

    file_hash = hashlib.sha256(content).hexdigest()

    # Deduplication check: verify if identical file (same hash, size, and extension) already exists for this user
    existing_res = await db.execute(
        select(Document)
        .where(
            Document.file_hash == file_hash,
            Document.file_size == content_length,
            Document.file_type == extension,
            Document.user_id == current_user.id,
        )
        .order_by(Document.created_at.desc())
    )
    existing_doc = existing_res.scalars().first()

    if existing_doc:
        # Case A: Document is already completed and indexed
        if existing_doc.status == "completed":
            return existing_doc, False, "duplicate_completed"

        # Case B: Document is currently queued or actively processing in worker container
        if existing_doc.status in ("processing", "queued"):
            return existing_doc, False, "duplicate_processing"

        # Case C: Previous ingestion failed; reuse record and re-queue cleanly
        if existing_doc.status == "failed":
            existing_doc.status = "queued"
            existing_doc.error_message = None
            existing_doc.filename = sanitized_name
            existing_doc.updated_at = utc_now()
            target_path = Path(existing_doc.storage_path)
            try:
                with open(target_path, "wb") as f:
                    f.write(content)
            except Exception:
                pass
            await db.flush()
            return existing_doc, True, "requeued"

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

    doc = Document(
        id=doc_id,
        user_id=current_user.id,
        uploader_username=current_user.username,
        uploader_email=current_user.email,
        client_ip=client_ip,
        user_agent=user_agent,
        audit_metadata=audit_meta,
        is_persistent_vector=True,
        is_shared=is_shared,
        filename=sanitized_name,
        file_type=extension,
        file_size=content_length,
        storage_path=str(safe_path),
        file_hash=file_hash,
        status="queued",
    )
    db.add(doc)
    await db.flush()

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
    return doc, True, "new"
