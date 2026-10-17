"""Room Workspace API endpoints for multi-file grouping and database references."""

import hashlib
import uuid
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.auth import get_optional_user
from app.core.exceptions import EntityNotFoundError, FileValidationError
from app.core.logging import logger
from app.core.rate_limit import RateLimiter
from app.core.security import validate_file_upload, verify_safe_path
from app.database import get_db
from app.ingestion.pipeline import ingestion_pipeline
from app.models.conversation import Conversation, Message
from app.models.document import Document, DocumentChunk
from app.models.room import Room, RoomDocument
from app.models.user import User
from app.schemas.document import DocumentResponse
from app.schemas.room import (
    RoomCreateRequest,
    RoomDetailResponse,
    RoomReferenceItem,
    RoomSummaryResponse,
    RoomUpdateRequest,
)

router = APIRouter(prefix="/api/rooms", tags=["rooms"])
settings = get_settings()

room_upload_rate_limiter = RateLimiter(max_requests=15, window_seconds=60)


def check_room_access(room: Room, user: Optional[User]) -> None:
    """Enforce ownership access control for room workspaces (prevent IDOR)."""
    if room.user_id is not None:
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to access this workspace.",
            )
        if room.user_id != user.id and getattr(user, "role", "user") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: you do not have permission to access or modify this workspace.",
            )


async def get_or_create_room_conversation(db: AsyncSession, room: Room) -> Conversation:
    """Find the primary active conversation thread for a room or create one."""
    res = await db.execute(
        select(Conversation)
        .where(Conversation.room_id == room.id)
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    conv = res.scalar_one_or_none()
    if not conv:
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


@router.post("", response_model=RoomDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_room(
    request: RoomCreateRequest,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new multi-file room workspace."""
    room = Room(
        id=str(uuid.uuid4()),
        user_id=current_user.id if current_user else None,
        name=request.name.strip(),
        description=request.description.strip() if request.description else None,
    )
    db.add(room)
    await db.commit()
    await db.refresh(room)

    # Initialize a conversation thread for this room
    conv = await get_or_create_room_conversation(db, room)

    return RoomDetailResponse(
        id=room.id,
        name=room.name,
        description=room.description,
        created_at=room.created_at,
        updated_at=room.updated_at,
        documents=[],
        references=[],
        active_conversation_id=conv.id,
        message_count=0,
    )


@router.get("", response_model=List[RoomSummaryResponse])
async def list_rooms(
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """List all workspace rooms (filtered by user if authenticated)."""
    query = select(Room)
    if current_user:
        query = query.where(Room.user_id == current_user.id)
    query = query.order_by(Room.updated_at.desc())

    res = await db.execute(query)
    rooms = res.scalars().all()
    if not rooms:
        return []

    room_ids = [r.id for r in rooms]

    # Batch count documents per room (1 query for all rooms)
    doc_counts_res = await db.execute(
        select(RoomDocument.room_id, func.count(RoomDocument.id))
        .where(RoomDocument.room_id.in_(room_ids))
        .group_by(RoomDocument.room_id)
    )
    doc_counts = dict(doc_counts_res.all())

    # Batch count messages across all room conversations (1 query for all rooms)
    msg_counts_res = await db.execute(
        select(Conversation.room_id, func.count(Message.id))
        .join(Message, Message.conversation_id == Conversation.id)
        .where(Conversation.room_id.in_(room_ids))
        .group_by(Conversation.room_id)
    )
    msg_counts = dict(msg_counts_res.all())

    summaries: List[RoomSummaryResponse] = []
    for r in rooms:
        summaries.append(
            RoomSummaryResponse(
                id=r.id,
                name=r.name,
                description=r.description,
                created_at=r.created_at,
                updated_at=r.updated_at,
                document_count=doc_counts.get(r.id, 0),
                message_count=msg_counts.get(r.id, 0),
            )
        )

    return summaries


@router.get("/{room_id}", response_model=RoomDetailResponse)
async def get_room_details(
    room_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full room details with attached documents, key references, and active conversation ID."""
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    check_room_access(room, current_user)

    # Get attached documents
    rd_res = await db.execute(select(RoomDocument).where(RoomDocument.room_id == room_id))
    room_docs = rd_res.scalars().all()
    doc_ids = [rd.document_id for rd in room_docs]

    docs: List[Document] = []
    if doc_ids:
        docs_res = await db.execute(select(Document).where(Document.id.in_(doc_ids)))
        docs = docs_res.scalars().all()

    # Get or create active conversation
    conv = await get_or_create_room_conversation(db, room)

    # Count messages
    msg_count_res = await db.execute(
        select(func.count(Message.id)).where(Message.conversation_id == conv.id)
    )
    message_count = msg_count_res.scalar_one()

    # Extract important document references from database
    references = await extract_room_references(db, doc_ids)

    return RoomDetailResponse(
        id=room.id,
        name=room.name,
        description=room.description,
        created_at=room.created_at,
        updated_at=room.updated_at,
        documents=[DocumentResponse.model_validate(d) for d in docs],
        references=references,
        active_conversation_id=conv.id,
        message_count=message_count,
    )


@router.put("/{room_id}", response_model=RoomDetailResponse)
async def update_room(
    room_id: str,
    request: RoomUpdateRequest,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Update room name or description."""
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    check_room_access(room, current_user)

    if request.name is not None:
        room.name = request.name.strip()
    if request.description is not None:
        room.description = request.description.strip()

    await db.commit()
    await db.refresh(room)
    return await get_room_details(room_id, current_user=current_user, db=db)


@router.delete("/{room_id}", status_code=status.HTTP_200_OK)
async def delete_room(
    room_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a room and its room-document mappings."""
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    check_room_access(room, current_user)

    await db.delete(room)
    await db.commit()
    return {"message": "Room deleted successfully.", "room_id": room_id}


@router.post(
    "/{room_id}/upload",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(room_upload_rate_limiter)],
)
async def upload_files_to_room(
    room_id: str,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload multiple files directly into a designated Room workspace."""
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    check_room_access(room, current_user)

    uploaded_docs: List[DocumentResponse] = []
    failed_files: List[dict] = []

    for file in files:
        try:
            content = await file.read()
            content_length = len(content)
            sanitized_name, extension = validate_file_upload(file, content_length, content_bytes=content)

            if content_length == 0:
                raise FileValidationError(f"File '{file.filename}' is empty.")

            file_hash = hashlib.sha256(content).hexdigest()
            doc_id = str(uuid.uuid4())
            target_filename = f"{doc_id}_{sanitized_name}"
            target_path = settings.UPLOAD_DIR / target_filename
            safe_path = verify_safe_path(target_path, settings.UPLOAD_DIR)

            with open(safe_path, "wb") as f:
                f.write(content)

            doc = Document(
                id=doc_id,
                user_id=current_user.id if current_user else None,
                filename=sanitized_name,
                file_type=extension,
                file_size=content_length,
                storage_path=str(safe_path),
                file_hash=file_hash,
                status="queued",
            )
            db.add(doc)
            await db.flush()

            # Attach to Room
            room_doc = RoomDocument(
                id=str(uuid.uuid4()),
                room_id=room_id,
                document_id=doc_id,
            )
            db.add(room_doc)
            await db.flush()

            background_tasks.add_task(ingestion_pipeline.process_document, doc_id)
            uploaded_docs.append(DocumentResponse.model_validate(doc))

        except Exception as e:
            logger.warning(f"Upload to room {room_id} failed for file '{file.filename}': {e}")
            failed_files.append({"filename": file.filename or "unknown", "error": str(e)})

    await db.commit()

    return {
        "message": f"Uploaded {len(uploaded_docs)} file(s) to room '{room.name}'.",
        "room_id": room_id,
        "uploaded": uploaded_docs,
        "failed": failed_files,
    }


@router.post("/{room_id}/documents/{document_id}", status_code=status.HTTP_200_OK)
async def attach_document_to_room(
    room_id: str,
    document_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Link an existing document into a room."""
    # Check room exists and caller has access
    r_res = await db.execute(select(Room).where(Room.id == room_id))
    room = r_res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    check_room_access(room, current_user)

    # Check document exists
    d_res = await db.execute(select(Document).where(Document.id == document_id))
    doc = d_res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Prevent attaching another user's private document
    if doc.user_id is not None:
        if not current_user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
        if doc.user_id != current_user.id and getattr(current_user, "role", "user") != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied to access this document.")

    # Check if already linked
    link_res = await db.execute(
        select(RoomDocument).where(
            RoomDocument.room_id == room_id, RoomDocument.document_id == document_id
        )
    )
    if not link_res.scalar_one_or_none():
        link = RoomDocument(
            id=str(uuid.uuid4()),
            room_id=room_id,
            document_id=document_id,
        )
        db.add(link)
        await db.commit()

    return {"message": "Document attached to room successfully.", "room_id": room_id, "document_id": document_id}


@router.delete("/{room_id}/documents/{document_id}", status_code=status.HTTP_200_OK)
async def detach_document_from_room(
    room_id: str,
    document_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Detach a document from a room."""
    r_res = await db.execute(select(Room).where(Room.id == room_id))
    room = r_res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    check_room_access(room, current_user)

    link_res = await db.execute(
        select(RoomDocument).where(
            RoomDocument.room_id == room_id, RoomDocument.document_id == document_id
        )
    )
    link = link_res.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Document link not found in this room.")

    await db.delete(link)
    await db.commit()
    return {"message": "Document detached from room.", "room_id": room_id, "document_id": document_id}


@router.get("/{room_id}/references", response_model=List[RoomReferenceItem])
async def get_room_references(
    room_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve key reference passages from database for all documents in this room."""
    r_res = await db.execute(select(Room).where(Room.id == room_id))
    room = r_res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    check_room_access(room, current_user)

    rd_res = await db.execute(select(RoomDocument.document_id).where(RoomDocument.room_id == room_id))
    doc_ids = [r[0] for r in rd_res.all()]
    return await extract_room_references(db, doc_ids)
