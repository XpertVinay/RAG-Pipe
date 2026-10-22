"""Room Workspace API endpoints for multi-file grouping and database references."""

import uuid
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_user
from app.core.logging import logger
from app.core.rate_limit import RateLimiter
from app.database import get_db
from app.ingestion.pipeline import ingestion_pipeline
from app.services.queue_service import queue_service
from app.services.event_broadcaster import event_broadcaster
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.models.project import Project
from app.models.room import Room, RoomDocument, RoomMember
from app.models.user import User
from app.schemas.document import DocumentResponse
from app.schemas.project import (
    PIIConsentRequest,
    PIIConsentResponse,
    RoomItemResponse,
    RoomItemsFilterResponse,
    RoomPIIScanResponse,
    ShareLinkResponse,
)
from app.schemas.room import (
    RoomCreateRequest,
    RoomDetailResponse,
    RoomMemberAddRequest,
    RoomMemberResponse,
    RoomReferenceItem,
    RoomShareRequest,
    RoomSummaryResponse,
    RoomUpdateRequest,
)
from app.services.document_service import verify_document_access
from app.services.pii_service import pii_service
from app.services.room_service import (
    check_room_access,
    extract_room_references,
    fetch_room_summary_counts,
    get_or_create_room_conversation,
    get_room_active_conversation,
    process_room_file_upload,
)

router = APIRouter(prefix="/rooms", tags=["rooms"])
room_upload_rate_limiter = RateLimiter(max_requests=15, window_seconds=60)


@router.post("", response_model=RoomDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_room(
    request: RoomCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new multi-file room workspace."""
    room = Room(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        name=request.name.strip(),
        description=request.description.strip() if request.description else None,
        is_public=request.is_public,
    )
    db.add(room)
    await db.commit()
    await db.refresh(room)

    conv = await get_room_active_conversation(db, room, create_if_absent=False)

    return RoomDetailResponse(
        id=room.id,
        name=room.name,
        description=room.description,
        is_public=room.is_public,
        user_role="owner" if current_user else "viewer",
        created_at=room.created_at,
        updated_at=room.updated_at,
        documents=[],
        references=[],
        members=[],
        active_conversation_id=conv.id if conv else None,
        message_count=0,
    )


@router.get("", response_model=List[RoomSummaryResponse])
async def list_rooms(
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """List all workspace rooms accessible to the user (owned, member, or public)."""
    if current_user:
        if getattr(current_user, "role", "user") == "admin":
            query = select(Room)
        else:
            member_room_subquery = select(RoomMember.room_id).where(RoomMember.user_id == current_user.id)
            query = select(Room).where(
                or_(
                    Room.user_id == current_user.id,
                    Room.id.in_(member_room_subquery),
                    Room.is_public.is_(True),
                    Room.user_id.is_(None),
                )
            )
    else:
        query = select(Room).where(or_(Room.is_public.is_(True), Room.user_id.is_(None)))

    query = query.order_by(Room.updated_at.desc())
    res = await db.execute(query)
    rooms = res.scalars().all()
    if not rooms:
        return []

    room_ids = [r.id for r in rooms]
    doc_counts, msg_counts = await fetch_room_summary_counts(db, room_ids)

    # Determine user role per room for summary response
    member_map = {}
    if current_user:
        mem_res = await db.execute(
            select(RoomMember.room_id, RoomMember.role).where(
                RoomMember.user_id == current_user.id,
                RoomMember.room_id.in_(room_ids),
            )
        )
        member_map = dict(mem_res.all())

    summaries = []
    for r in rooms:
        if current_user:
            if getattr(current_user, "role", "user") == "admin":
                role = "admin"
            elif r.user_id == current_user.id:
                role = "owner"
            elif r.id in member_map:
                role = member_map[r.id]
            elif r.is_public:
                role = "viewer"
            else:
                role = "viewer"
        else:
            role = "viewer"

        summaries.append(
            RoomSummaryResponse(
                id=r.id,
                name=r.name,
                description=r.description,
                is_public=getattr(r, "is_public", False),
                user_role=role,
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
    """Get full room details with attached documents, key references, member list, and active conversation ID."""
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    user_role = await check_room_access(room, current_user, db, required_role="viewer")

    rd_res = await db.execute(select(RoomDocument).where(RoomDocument.room_id == room_id))
    room_docs = rd_res.scalars().all()
    doc_ids = [rd.document_id for rd in room_docs]

    docs: List[Document] = []
    if doc_ids:
        docs_res = await db.execute(select(Document).where(Document.id.in_(doc_ids)))
        docs = docs_res.scalars().all()

    conv = await get_room_active_conversation(db, room, create_if_absent=False)
    if conv:
        msg_count_res = await db.execute(
            select(func.count(Message.id)).where(Message.conversation_id == conv.id)
        )
        message_count = msg_count_res.scalar_one()
        active_conversation_id = conv.id
    else:
        message_count = 0
        active_conversation_id = None

    references = await extract_room_references(db, doc_ids)

    # Fetch room members
    mem_res = await db.execute(
        select(RoomMember, User)
        .join(User, RoomMember.user_id == User.id)
        .where(RoomMember.room_id == room_id)
        .order_by(RoomMember.created_at.asc())
    )
    member_rows = mem_res.all()
    members_resp = [
        RoomMemberResponse(
            id=m.id,
            room_id=m.room_id,
            user_id=u.id,
            username=u.username,
            email=u.email,
            full_name=u.full_name,
            role=m.role,
            created_at=m.created_at,
        )
        for m, u in member_rows
    ]

    return RoomDetailResponse(
        id=room.id,
        name=room.name,
        description=room.description,
        is_public=getattr(room, "is_public", False),
        user_role=user_role,
        created_at=room.created_at,
        updated_at=room.updated_at,
        documents=[DocumentResponse.model_validate(d) for d in docs],
        references=references,
        members=members_resp,
        active_conversation_id=active_conversation_id,
        message_count=message_count,
    )


@router.put("/{room_id}", response_model=RoomDetailResponse)
async def update_room(
    room_id: str,
    request: RoomUpdateRequest,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Update room name, description, or public visibility."""
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    await check_room_access(room, current_user, db, required_role="editor")

    if request.name is not None:
        room.name = request.name.strip()
    if request.description is not None:
        room.description = request.description.strip()
    if request.is_public is not None:
        await check_room_access(room, current_user, db, required_role="owner")
        room.is_public = request.is_public

    await db.commit()
    await db.refresh(room)
    return await get_room_details(room_id, current_user=current_user, db=db)


@router.delete("/{room_id}", status_code=status.HTTP_200_OK)
async def delete_room(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a room and its room-document mappings (owner or admin only)."""
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    await check_room_access(room, current_user, db, required_role="owner")

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
    request: Request,
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload multiple files directly into a designated Room workspace with verified user audit trail."""
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    await check_room_access(room, current_user, db, required_role="editor")

    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "127.0.0.1")
    )
    user_agent = request.headers.get("user-agent", "")[:500]

    uploaded_docs: List[DocumentResponse] = []
    failed_files: List[dict] = []

    any_duplicate_completed = False
    any_duplicate_processing = False
    docs_to_enqueue: List[str] = []

    for file in files:
        try:
            doc, should_enqueue, reason = await process_room_file_upload(
                file=file,
                room=room,
                current_user=current_user,
                client_ip=client_ip,
                user_agent=user_agent,
                db=db,
            )
            if should_enqueue:
                docs_to_enqueue.append(doc.id)
            if reason in ("duplicate_completed", "attached_existing_completed"):
                any_duplicate_completed = True
            elif reason in ("duplicate_processing", "attached_existing_processing"):
                any_duplicate_processing = True
            uploaded_docs.append(DocumentResponse.model_validate(doc))
        except Exception as e:
            logger.warning(f"Upload to room {room_id} failed for file '{file.filename}': {e}")
            failed_files.append({"filename": file.filename or "unknown", "error": str(e)})

    # CRITICAL: Commit to database FIRST before publishing to RabbitMQ!
    await db.commit()

    for doc_id in docs_to_enqueue:
        await queue_service.enqueue_document_job(doc_id, background_tasks=background_tasks)
        await event_broadcaster.broadcast_document_status(
            document_id=doc_id,
            status="queued",
            user_id=current_user.id,
            extra={"room_id": str(room_id)},
        )

    if any_duplicate_completed and len(uploaded_docs) == 1:
        message = f"File '{files[0].filename}' is already indexed. Attached to room '{room.name}' (skipped duplicate embedding)."
    elif any_duplicate_processing and len(uploaded_docs) == 1:
        message = f"File '{files[0].filename}' is already actively being processed by the worker."
    else:
        message = f"Uploaded {len(uploaded_docs)} file(s) to room '{room.name}'."
        if any_duplicate_completed:
            message += " (Reused existing indexed vectors to prevent duplicate processing)"
        if any_duplicate_processing:
            message += " (Active background jobs monitored)"
    if failed_files:
        message += f" ({len(failed_files)} file(s) failed)"

    return {
        "message": message,
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
    """Link an existing document into a room (editor or owner)."""
    r_res = await db.execute(select(Room).where(Room.id == room_id))
    room = r_res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    await check_room_access(room, current_user, db, required_role="editor")

    d_res = await db.execute(select(Document).where(Document.id == document_id))
    doc = d_res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Verify user has access to this document before attaching
    await verify_document_access(doc, current_user, db, "attach this document")

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
    """Detach a document from a room (editor or owner)."""
    r_res = await db.execute(select(Room).where(Room.id == room_id))
    room = r_res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    await check_room_access(room, current_user, db, required_role="editor")

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


@router.patch("/{room_id}/share", response_model=RoomDetailResponse)
async def share_room(
    room_id: str,
    share_req: RoomShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Toggle room public visibility (owner or admin only)."""
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    await check_room_access(room, current_user, db, required_role="owner")
    room.is_public = share_req.is_public
    await db.commit()
    await db.refresh(room)
    return await get_room_details(room_id, current_user=current_user, db=db)


@router.post("/{room_id}/members", response_model=RoomMemberResponse, status_code=status.HTTP_201_CREATED)
async def add_room_member(
    room_id: str,
    req: RoomMemberAddRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Invite or add a user to a room workspace with a specific role (owner or admin only)."""
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    await check_room_access(room, current_user, db, required_role="owner")

    target_identifier = req.username_or_email.strip()
    u_res = await db.execute(
        select(User).where(
            or_(
                User.username == target_identifier,
                User.email == target_identifier,
            )
        )
    )
    target_user = u_res.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail=f"User '{target_identifier}' not found.")

    if target_user.id == room.user_id:
        raise HTTPException(status_code=400, detail="User is already the owner of this workspace.")

    m_res = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == room_id,
            RoomMember.user_id == target_user.id,
        )
    )
    existing_member = m_res.scalar_one_or_none()
    role = req.role if req.role in ("viewer", "editor", "owner") else "viewer"

    if existing_member:
        existing_member.role = role
        await db.commit()
        await db.refresh(existing_member)
        return RoomMemberResponse(
            id=existing_member.id,
            room_id=existing_member.room_id,
            user_id=target_user.id,
            username=target_user.username,
            email=target_user.email,
            full_name=target_user.full_name,
            role=existing_member.role,
            created_at=existing_member.created_at,
        )

    new_member = RoomMember(
        id=str(uuid.uuid4()),
        room_id=room_id,
        user_id=target_user.id,
        role=role,
    )
    db.add(new_member)
    await db.commit()
    await db.refresh(new_member)

    return RoomMemberResponse(
        id=new_member.id,
        room_id=new_member.room_id,
        user_id=target_user.id,
        username=target_user.username,
        email=target_user.email,
        full_name=target_user.full_name,
        role=new_member.role,
        created_at=new_member.created_at,
    )


@router.get("/{room_id}/members", response_model=List[RoomMemberResponse])
async def list_room_members(
    room_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """List all members of a room workspace."""
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    await check_room_access(room, current_user, db, required_role="viewer")

    mem_res = await db.execute(
        select(RoomMember, User)
        .join(User, RoomMember.user_id == User.id)
        .where(RoomMember.room_id == room_id)
        .order_by(RoomMember.created_at.asc())
    )
    rows = mem_res.all()
    return [
        RoomMemberResponse(
            id=m.id,
            room_id=m.room_id,
            user_id=u.id,
            username=u.username,
            email=u.email,
            full_name=u.full_name,
            role=m.role,
            created_at=m.created_at,
        )
        for m, u in rows
    ]


@router.delete("/{room_id}/members/{user_id}", status_code=status.HTTP_200_OK)
async def remove_room_member(
    room_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a member from a room (owner, admin, or member self-removal)."""
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    is_self = current_user.id == user_id
    if not is_self:
        await check_room_access(room, current_user, db, required_role="owner")

    m_res = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == room_id,
            RoomMember.user_id == user_id,
        )
    )
    member = m_res.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found in this room.")

    await db.delete(member)
    await db.commit()
    return {"message": "Member removed from room.", "room_id": room_id, "user_id": user_id}


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

    await check_room_access(room, current_user, db, required_role="viewer")

    rd_res = await db.execute(select(RoomDocument.document_id).where(RoomDocument.room_id == room_id))
    doc_ids = [r[0] for r in rd_res.all()]
    return await extract_room_references(db, doc_ids)


@router.get("/{room_id}/items", response_model=RoomItemsFilterResponse)
async def list_room_items(
    room_id: str,
    filter_type: str = Query("all", description="'all', 'projects', or 'chats'"),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """List projects and/or chats belonging to a room workspace according to the selected filter value."""
    r_res = await db.execute(select(Room).where(Room.id == room_id))
    room = r_res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    await check_room_access(room, current_user, db, required_role="viewer")

    # 1. Fetch Projects in room
    p_res = await db.execute(
        select(Project).where(Project.room_id == room_id).order_by(Project.updated_at.desc())
    )
    projects = p_res.scalars().all()

    # 2. Fetch Conversations in room
    c_res = await db.execute(
        select(Conversation).where(Conversation.room_id == room_id).order_by(Conversation.updated_at.desc())
    )
    conversations = c_res.scalars().all()

    # Message counts for conversations
    conv_ids = [c.id for c in conversations]
    msg_counts = {}
    if conv_ids:
        mc_res = await db.execute(
            select(Message.conversation_id, func.count(Message.id))
            .where(Message.conversation_id.in_(conv_ids))
            .group_by(Message.conversation_id)
        )
        msg_counts = dict(mc_res.all())

    project_map = {p.id: p.name for p in projects}

    items: List[RoomItemResponse] = []

    # Map projects to polymorphic item response
    if filter_type in ("all", "projects"):
        for p in projects:
            items.append(
                RoomItemResponse(
                    id=p.id,
                    item_type="project",
                    title=p.name,
                    description=p.description,
                    room_id=room_id,
                    project_id=p.id,
                    project_name=p.name,
                    status=p.status,
                    request_type=getattr(p, "request_type", "standard"),
                    communication_channel=getattr(p, "communication_channel", None),
                    client_name=getattr(p, "client_name", None),
                    tags=p.tags or [],
                    message_count=0,
                    created_at=p.created_at,
                    updated_at=p.updated_at,
                )
            )

    # Map chats to polymorphic item response
    if filter_type in ("all", "chats"):
        for c in conversations:
            items.append(
                RoomItemResponse(
                    id=c.id,
                    item_type="chat",
                    title=c.title or "Chat Session",
                    description=f"{msg_counts.get(c.id, 0)} message(s)",
                    room_id=room_id,
                    project_id=c.project_id,
                    project_name=project_map.get(c.project_id) if c.project_id else None,
                    status="active",
                    tags=["chat"],
                    message_count=msg_counts.get(c.id, 0),
                    created_at=c.created_at,
                    updated_at=c.updated_at,
                )
            )

    # Sort items by updated_at descending
    items.sort(key=lambda x: x.updated_at, reverse=True)

    return RoomItemsFilterResponse(
        room_id=room_id,
        filter_type=filter_type if filter_type in ("all", "projects", "chats") else "all",
        total_projects=len(projects),
        total_chats=len(conversations),
        items=items,
    )


@router.post("/{room_id}/share-link/generate", response_model=ShareLinkResponse)
async def generate_room_share_link(
    room_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate or retrieve a secure public share link for a room workspace (owner or editor)."""
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    await check_room_access(room, current_user, db, required_role="editor")

    if not room.share_token or room.share_revoked:
        room.share_token = uuid.uuid4().hex
        room.share_revoked = False

    room.is_public = True
    await db.commit()
    await db.refresh(room)

    base_url = str(request.base_url).rstrip("/")
    share_url = f"{base_url}/shared/room/{room.share_token}"

    return ShareLinkResponse(
        room_id=room.id,
        share_token=room.share_token,
        share_url=share_url,
        is_public=room.is_public,
        is_revoked=room.share_revoked,
        pii_consent_status=room.pii_consent_status,
        created_at=room.updated_at,
    )


@router.post("/{room_id}/share-link/revoke", status_code=status.HTTP_200_OK)
async def revoke_room_share_link(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke share linking immediately, blocking external access (owner or admin only)."""
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    await check_room_access(room, current_user, db, required_role="owner")

    room.share_revoked = True
    room.is_public = False
    await db.commit()
    await db.refresh(room)

    logger.info(f"Share link for room {room_id} revoked by user {current_user.id}")
    return {
        "message": "Share link has been revoked. External users can no longer access this workspace.",
        "room_id": room_id,
        "is_revoked": True,
        "is_public": False,
    }


@router.post("/{room_id}/pii/scan", response_model=RoomPIIScanResponse)
async def scan_room_pii(
    room_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Scan all discussions and room content for accidental PII breaches."""
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    await check_room_access(room, current_user, db, required_role="viewer")

    # Collect room text corpus
    text_corpus = [room.name or "", room.description or ""]

    # Recent messages
    m_res = await db.execute(
        select(Message.content)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Conversation.room_id == room_id)
        .limit(40)
    )
    for row in m_res.all():
        if row[0]:
            text_corpus.append(row[0])

    combined_text = "\n".join(text_corpus)
    scan_res = pii_service.scan_and_mask(combined_text)

    categories = list(sorted(set(d.category for d in scan_res.detections)))
    masked_snippets = [d.masked_representation for d in scan_res.detections[:5]]

    if scan_res.has_pii and room.pii_consent_status == "clean":
        room.pii_consent_status = "breach_detected"
        await db.commit()

    return RoomPIIScanResponse(
        room_id=room.id,
        has_pii_breach=scan_res.has_pii,
        breach_count=scan_res.breach_count,
        risk_level=scan_res.risk_level,
        alert_message=scan_res.alert_message,
        pii_consent_status=room.pii_consent_status,
        detected_categories=categories,
        preview_masked_snippets=masked_snippets,
    )


@router.post("/{room_id}/pii/consent", response_model=PIIConsentResponse)
async def submit_pii_consent(
    room_id: str,
    req: PIIConsentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Capture explicit user consent for PII sharing (mask or unmasked) before making available to others."""
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    await check_room_access(room, current_user, db, required_role="editor")

    if not req.confirm_acknowledgment:
        raise HTTPException(status_code=400, detail="Consent confirmation acknowledgment is required.")

    if req.consent_mode == "mask":
        room.pii_consent_status = "consent_masked"
        msg = "Consent recorded: Sensitive data will remain securely masked with contextual descriptors for other users."
    else:
        room.pii_consent_status = "consent_unmasked"
        msg = "Explicit consent recorded: Room content has been authorized for unmasked sharing."

    await db.commit()
    await db.refresh(room)

    return PIIConsentResponse(
        room_id=room.id,
        pii_consent_status=room.pii_consent_status,
        message=msg,
        updated_at=room.updated_at,
    )


@router.get("/shared/{share_token}", response_model=RoomDetailResponse)
async def get_shared_room_by_token(
    share_token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public access endpoint for shared rooms with enforced revocation and contextual PII masking."""
    res = await db.execute(select(Room).where(Room.share_token == share_token))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Shared workspace not found.")

    if room.share_revoked:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This share link has been revoked by the workspace owner.",
        )

    # If consent is not explicitly unmasked, apply contextual masking to description
    display_desc = room.description
    if room.pii_consent_status != "consent_unmasked" and display_desc:
        scan = pii_service.scan_and_mask(display_desc)
        display_desc = scan.masked_text

    rd_res = await db.execute(select(RoomDocument).where(RoomDocument.room_id == room.id))
    room_docs = rd_res.scalars().all()
    doc_ids = [rd.document_id for rd in room_docs]

    docs: List[Document] = []
    if doc_ids:
        docs_res = await db.execute(select(Document).where(Document.id.in_(doc_ids)))
        docs = docs_res.scalars().all()

    conv = await get_room_active_conversation(db, room, create_if_absent=False)
    references = await extract_room_references(db, doc_ids)

    return RoomDetailResponse(
        id=room.id,
        name=room.name,
        description=display_desc,
        is_public=room.is_public,
        user_role="viewer",
        created_at=room.created_at,
        updated_at=room.updated_at,
        documents=[DocumentResponse.model_validate(d) for d in docs],
        references=references,
        members=[],
        active_conversation_id=conv.id if conv else None,
        message_count=0,
    )


