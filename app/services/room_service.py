"""Room Workspace service managing access checks, conversation threads, reference excerpts, and file uploads."""

import hashlib
import uuid
from typing import Dict, List, Optional, Tuple
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.auth import utc_now
from app.core.exceptions import FileValidationError
from app.core.security import validate_file_upload, verify_safe_path
from app.models.conversation import Conversation, Message
from app.models.document import AuditLog, Document, DocumentChunk
from app.models.room import Room, RoomDocument, RoomMember
from app.models.user import User
from app.schemas.room import RoomReferenceItem

settings = get_settings()


async def check_room_access(
    room: Room,
    user: Optional[User],
    db: Optional[AsyncSession] = None,
    required_role: str = "viewer",
) -> str:
    """Enforce ownership and RBAC room membership access control (prevent IDOR)."""
    # 1. Admin has global override
    if user and getattr(user, "role", "user") == "admin":
        return "admin"

    # 2. Room owner
    if user and room.user_id is not None and room.user_id == user.id:
        return "owner"

    # 3. Check RoomMember table for invited members
    member_role: Optional[str] = None
    if user:
        if db is not None:
            m_res = await db.execute(
                select(RoomMember).where(
                    RoomMember.room_id == room.id,
                    RoomMember.user_id == user.id,
                )
            )
            member = m_res.scalar_one_or_none()
            if member:
                member_role = member.role
        elif getattr(room, "members", None):
            for m in room.members:
                if m.user_id == user.id:
                    member_role = m.role
                    break

    if member_role:
        if required_role == "viewer":
            return member_role
        if required_role == "editor" and member_role in ("editor", "owner"):
            return member_role
        if required_role == "owner" and member_role == "owner":
            return member_role
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: '{required_role}' privileges required for this room.",
        )

    # 4. Public room check
    if getattr(room, "is_public", False):
        if required_role == "viewer":
            return "viewer"
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to modify this public workspace.",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: only room owners or editors can modify this workspace.",
        )

    # 5. Open/unowned room (room.user_id is None)
    if room.user_id is None:
        if required_role == "viewer":
            return "viewer"
        return "editor"

    # 6. Otherwise: authentication or permission denied
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to access this workspace.",
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access denied: you do not have permission to access or modify this workspace.",
    )


async def get_room_active_conversation(db: AsyncSession, room: Room, create_if_absent: bool = False) -> Optional[Conversation]:
    """Find the primary active conversation thread for a room."""
    res = await db.execute(
        select(Conversation)
        .where(Conversation.room_id == room.id)
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    conv = res.scalar_one_or_none()
    if not conv and create_if_absent:
        conv = Conversation(
            id=str(uuid.uuid4()),
            room_id=room.id,
            user_id=room.user_id,
            title=f"{room.name} Discussion",
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
    return conv


async def get_or_create_room_conversation(db: AsyncSession, room: Room) -> Conversation:
    """Find the primary active conversation thread for a room or create one."""
    return await get_room_active_conversation(db, room, create_if_absent=True)



async def extract_room_references(db: AsyncSession, document_ids: List[str]) -> List[RoomReferenceItem]:
    """Extract key document excerpts and metadata from database in a single batched query."""
    if not document_ids:
        return []

    # 1. Fetch all documents in one batched query
    doc_res = await db.execute(select(Document).where(Document.id.in_(document_ids)))
    docs_by_id = {d.id: d for d in doc_res.scalars().all()}
    if not docs_by_id:
        return []

    # 2. Fetch top representative chunks (chunk_index < 3) in one batched query
    chunk_res = await db.execute(
        select(DocumentChunk)
        .where(
            DocumentChunk.document_id.in_(document_ids),
            DocumentChunk.chunk_index < 3,
        )
        .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index.asc())
    )
    chunks = chunk_res.scalars().all()

    references: List[RoomReferenceItem] = []
    for chunk in chunks:
        doc = docs_by_id.get(chunk.document_id)
        if not doc:
            continue
        meta = chunk.chunk_metadata or {}
        page = meta.get("page", 1)
        raw_excerpt = chunk.content.strip().replace("\n", " ")
        excerpt = (raw_excerpt[:240] + "...") if len(raw_excerpt) > 240 else raw_excerpt

        references.append(
            RoomReferenceItem(
                document_id=doc.id,
                filename=doc.filename,
                chunk_index=chunk.chunk_index,
                page=page,
                excerpt=excerpt,
                summary_hint=f"Section {chunk.chunk_index + 1} from {doc.filename}",
            )
        )

    return references


async def fetch_room_summary_counts(
    db: AsyncSession,
    room_ids: List[str],
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Batch fetch document counts and message counts for a list of rooms."""
    if not room_ids:
        return {}, {}

    doc_counts_res = await db.execute(
        select(RoomDocument.room_id, func.count(RoomDocument.id))
        .where(RoomDocument.room_id.in_(room_ids))
        .group_by(RoomDocument.room_id)
    )
    doc_counts = dict(doc_counts_res.all())

    msg_counts_res = await db.execute(
        select(Conversation.room_id, func.count(Message.id))
        .join(Message, Message.conversation_id == Conversation.id)
        .where(Conversation.room_id.in_(room_ids))
        .group_by(Conversation.room_id)
    )
    msg_counts = dict(msg_counts_res.all())

    return doc_counts, msg_counts


async def process_room_file_upload(
    file: UploadFile,
    room: Room,
    current_user: User,
    client_ip: str,
    user_agent: str,
    db: AsyncSession,
) -> Tuple[Document, bool, str]:
    """Validate, deduplicate, and persist an uploaded file for a specific room."""
    content = await file.read()
    content_length = len(content)
    sanitized_name, extension = validate_file_upload(file, content_length, content_bytes=content)

    if content_length == 0:
        raise FileValidationError(f"File '{file.filename}' is empty.")

    file_hash = hashlib.sha256(content).hexdigest()

    # 1. Check if identical file is already attached to this room
    existing_in_room_res = await db.execute(
        select(Document)
        .join(RoomDocument, RoomDocument.document_id == Document.id)
        .where(
            RoomDocument.room_id == room.id,
            Document.file_hash == file_hash,
            Document.file_size == content_length,
            Document.file_type == extension,
        )
        .order_by(Document.created_at.desc())
    )
    existing_in_room = existing_in_room_res.scalars().first()

    if existing_in_room:
        if existing_in_room.status == "completed":
            return existing_in_room, False, "duplicate_completed"
        if existing_in_room.status in ("processing", "queued"):
            return existing_in_room, False, "duplicate_processing"
        if existing_in_room.status == "failed":
            existing_in_room.status = "queued"
            existing_in_room.error_message = None
            existing_in_room.filename = sanitized_name
            existing_in_room.updated_at = utc_now()
            try:
                with open(Path(existing_in_room.storage_path), "wb") as f:
                    f.write(content)
            except Exception:
                pass
            await db.flush()
            return existing_in_room, True, "requeued"

    # 2. Check if current_user already has this document indexed in their personal library
    existing_user_doc_res = await db.execute(
        select(Document)
        .where(
            Document.file_hash == file_hash,
            Document.file_size == content_length,
            Document.file_type == extension,
            Document.user_id == current_user.id,
        )
        .order_by(Document.created_at.desc())
    )
    existing_user_doc = existing_user_doc_res.scalars().first()

    if existing_user_doc:
        room_doc = RoomDocument(
            id=str(uuid.uuid4()),
            room_id=room.id,
            document_id=existing_user_doc.id,
        )
        db.add(room_doc)
        await db.flush()

        if existing_user_doc.status == "completed":
            return existing_user_doc, False, "attached_existing_completed"
        if existing_user_doc.status in ("processing", "queued"):
            return existing_user_doc, False, "attached_existing_processing"
        if existing_user_doc.status == "failed":
            existing_user_doc.status = "queued"
            existing_user_doc.error_message = None
            existing_user_doc.updated_at = utc_now()
            await db.flush()
            return existing_user_doc, True, "requeued"

    # 3. Brand new file: create Document and RoomDocument records
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
        "room": {
            "id": room.id,
            "name": room.name,
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
        is_shared=False,
        filename=sanitized_name,
        file_type=extension,
        file_size=content_length,
        storage_path=str(safe_path),
        file_hash=file_hash,
        status="queued",
    )
    db.add(doc)
    await db.flush()

    room_doc = RoomDocument(
        id=str(uuid.uuid4()),
        room_id=room.id,
        document_id=doc_id,
    )
    db.add(room_doc)
    await db.flush()

    audit_entry = AuditLog(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        username=current_user.username,
        user_email=current_user.email,
        action="document_upload_room",
        entity_type="document",
        entity_id=doc_id,
        client_ip=client_ip,
        user_agent=user_agent,
        details={
            "filename": sanitized_name,
            "file_size": content_length,
            "file_type": extension,
            "room_id": room.id,
            "room_name": room.name,
        },
    )
    db.add(audit_entry)
    return doc, True, "new"
