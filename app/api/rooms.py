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
from app.models.conversation import Message
from app.models.document import Document
from app.models.room import Room, RoomDocument, RoomMember
from app.models.user import User
from app.schemas.document import DocumentResponse
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
from app.services.room_service import (
    check_room_access,
    extract_room_references,
    fetch_room_summary_counts,
    get_or_create_room_conversation,
    process_room_file_upload,
)

router = APIRouter(prefix="/api/rooms", tags=["rooms"])
room_upload_rate_limiter = RateLimiter(max_requests=15, window_seconds=60)


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
        is_public=request.is_public,
    )
    db.add(room)
    await db.commit()
    await db.refresh(room)

    conv = await get_or_create_room_conversation(db, room)

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
        active_conversation_id=conv.id,
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

    conv = await get_or_create_room_conversation(db, room)

    msg_count_res = await db.execute(
        select(func.count(Message.id)).where(Message.conversation_id == conv.id)
    )
    message_count = msg_count_res.scalar_one()
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
    current_user: Optional[User] = Depends(get_optional_user),
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

    for file in files:
        try:
            doc = await process_room_file_upload(
                file=file,
                room=room,
                current_user=current_user,
                client_ip=client_ip,
                user_agent=user_agent,
                db=db,
            )
            background_tasks.add_task(ingestion_pipeline.process_document, doc.id)
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

