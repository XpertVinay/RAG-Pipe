"""FastAPI Router for Projects scoped within Room Workspaces and Application Requests."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_user
from app.database import get_db
from app.models.conversation import Conversation, Message
from app.models.project import Project
from app.models.room import Room
from app.models.user import User
from app.schemas.project import (
    AppCreationProjectRequest,
    InitiateCallRequest,
    InitiateCallResponse,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
)
from app.services.room_service import check_room_access

# Scoped router: /api/rooms/{room_id}/projects
router = APIRouter(prefix="/rooms/{room_id}/projects", tags=["projects"])

# Direct router: /api/projects
projects_direct_router = APIRouter(prefix="/projects", tags=["projects"])


def serialize_project_response(p: Project, conversation_count: int = 0) -> ProjectResponse:
    """Helper to convert Project ORM entity to standard Pydantic response."""
    return ProjectResponse(
        id=p.id,
        room_id=p.room_id,
        user_id=p.user_id,
        name=p.name,
        description=p.description,
        status=p.status,
        request_type=getattr(p, "request_type", "standard") or "standard",
        client_name=getattr(p, "client_name", None),
        email=getattr(p, "email", None),
        phone=getattr(p, "phone", None),
        communication_channel=getattr(p, "communication_channel", "Gmeet") or "Gmeet",
        transcripts=getattr(p, "transcripts", None),
        meeting_link=getattr(p, "meeting_link", None),
        call_initiated_at=getattr(p, "call_initiated_at", None),
        call_notes=getattr(p, "call_notes", None),
        tags=p.tags or [],
        created_at=p.created_at,
        updated_at=p.updated_at,
        conversation_count=conversation_count,
    )


async def compile_conversation_transcripts(db: AsyncSession, conversation_id: str) -> str:
    """Format all messages from a conversation into a structured readable transcript."""
    c_res = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conv = c_res.scalar_one_or_none()
    title = conv.title if conv else conversation_id

    res = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    messages = res.scalars().all()
    if not messages:
        return f"=== CONVERSATION TRANSCRIPT: {title} ===\n(No message history recorded yet.)"

    lines = [
        f"=== CONVERSATION TRANSCRIPT ===",
        f"Thread Title: {title}",
        f"Conversation ID: {conversation_id}",
        f"Compiled At: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Message Count: {len(messages)}",
        "=" * 45,
        "",
    ]
    for msg in messages:
        role = "👤 USER" if msg.role == "user" else "🤖 AI ASSISTANT"
        ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if msg.created_at else "N/A"
        lines.append(f"[{role} | {ts}]")
        lines.append(msg.content.strip())
        lines.append("-" * 35)
        lines.append("")

    return "\n".join(lines)


def generate_channel_meeting_link(channel: Optional[str], project_id: str) -> str:
    """Generate direct video meeting launch URL depending on communication channel."""
    ch = (channel or "Gmeet").strip().lower()
    if "gmeet" in ch or "meet" in ch or "google" in ch:
        return "https://meet.google.com/new"
    elif "team" in ch:
        return f"https://teams.microsoft.com/l/meetup-join/19%3ameeting_{project_id[:8]}%40thread.v2/0"
    elif "zoom" in ch:
        return "https://zoom.us/join"
    else:
        return "https://meet.google.com/new"


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    room_id: str,
    request: ProjectCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new project workspace inside a room, optionally saving contact & transcript details."""
    r_res = await db.execute(select(Room).where(Room.id == room_id))
    room = r_res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room workspace not found.")

    await check_room_access(room, current_user, db, required_role="editor")

    # If conversation_id is provided and transcripts not explicitly given, compile them
    transcripts_content = request.transcripts
    if request.conversation_id and not transcripts_content:
        transcripts_content = await compile_conversation_transcripts(db, request.conversation_id)

    project_id = str(uuid.uuid4())
    meeting_link = request.meeting_link or generate_channel_meeting_link(request.communication_channel, project_id)

    project = Project(
        id=project_id,
        room_id=room_id,
        user_id=current_user.id,
        name=request.name.strip(),
        description=request.description.strip() if request.description else None,
        status=request.status or "active",
        request_type=request.request_type or "standard",
        client_name=request.client_name.strip() if request.client_name else None,
        email=request.email.strip() if request.email else None,
        phone=request.phone.strip() if request.phone else None,
        communication_channel=request.communication_channel or "Gmeet",
        transcripts=transcripts_content,
        meeting_link=meeting_link,
        tags=request.tags or [],
        metadata_info={},
    )
    db.add(project)

    # Link conversation to this project if conversation_id was passed
    if request.conversation_id:
        c_res = await db.execute(select(Conversation).where(Conversation.id == request.conversation_id))
        conv = c_res.scalar_one_or_none()
        if conv:
            conv.project_id = project.id

    await db.commit()
    await db.refresh(project)

    return serialize_project_response(project, conversation_count=1 if request.conversation_id else 0)


@router.get("", response_model=List[ProjectResponse])
async def list_projects(
    room_id: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """List all projects created within a specific room workspace."""
    r_res = await db.execute(select(Room).where(Room.id == room_id))
    room = r_res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room workspace not found.")

    await check_room_access(room, current_user, db, required_role="viewer")

    query = select(Project).where(Project.room_id == room_id)
    if status_filter:
        query = query.where(Project.status == status_filter)

    query = query.order_by(Project.updated_at.desc())
    res = await db.execute(query)
    projects = res.scalars().all()

    # Get conversation count per project
    counts_res = await db.execute(
        select(Conversation.project_id, func.count(Conversation.id))
        .where(Conversation.project_id.in_([p.id for p in projects]))
        .group_by(Conversation.project_id)
    )
    counts_map = dict(counts_res.all())

    return [serialize_project_response(p, counts_map.get(p.id, 0)) for p in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    room_id: str,
    project_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Get single project details."""
    r_res = await db.execute(select(Room).where(Room.id == room_id))
    room = r_res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room workspace not found.")

    await check_room_access(room, current_user, db, required_role="viewer")

    p_res = await db.execute(select(Project).where(Project.id == project_id, Project.room_id == room_id))
    project = p_res.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found in this room.")

    c_count_res = await db.execute(
        select(func.count(Conversation.id)).where(Conversation.project_id == project_id)
    )
    c_count = c_count_res.scalar_one()

    return serialize_project_response(project, c_count)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    room_id: str,
    project_id: str,
    request: ProjectUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update project title, description, client contact details, status, or notes."""
    r_res = await db.execute(select(Room).where(Room.id == room_id))
    room = r_res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room workspace not found.")

    await check_room_access(room, current_user, db, required_role="editor")

    p_res = await db.execute(select(Project).where(Project.id == project_id, Project.room_id == room_id))
    project = p_res.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found in this room.")

    if request.name is not None:
        project.name = request.name.strip()
    if request.description is not None:
        project.description = request.description.strip()
    if request.status is not None:
        project.status = request.status
    if request.tags is not None:
        project.tags = request.tags
    if request.client_name is not None:
        project.client_name = request.client_name.strip()
    if request.email is not None:
        project.email = request.email.strip()
    if request.phone is not None:
        project.phone = request.phone.strip()
    if request.communication_channel is not None:
        project.communication_channel = request.communication_channel
    if request.request_type is not None:
        project.request_type = request.request_type
    if request.transcripts is not None:
        project.transcripts = request.transcripts
    if request.meeting_link is not None:
        project.meeting_link = request.meeting_link
    if request.call_notes is not None:
        project.call_notes = request.call_notes
    if request.call_initiated_at is not None:
        project.call_initiated_at = request.call_initiated_at

    await db.commit()
    await db.refresh(project)

    c_count_res = await db.execute(
        select(func.count(Conversation.id)).where(Conversation.project_id == project_id)
    )
    c_count = c_count_res.scalar_one()

    return serialize_project_response(project, c_count)


@router.delete("/{project_id}", status_code=status.HTTP_200_OK)
async def delete_project(
    room_id: str,
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a project (owner or editor)."""
    r_res = await db.execute(select(Room).where(Room.id == room_id))
    room = r_res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room workspace not found.")

    await check_room_access(room, current_user, db, required_role="editor")

    p_res = await db.execute(select(Project).where(Project.id == project_id, Project.room_id == room_id))
    project = p_res.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found in this room.")

    await db.delete(project)
    await db.commit()
    return {"message": "Project deleted successfully.", "project_id": project_id, "room_id": room_id}


# =========================================================================
# Application Request & Call Initiation Endpoints
# =========================================================================

async def handle_create_app_request(
    request: AppCreationProjectRequest,
    current_user: Optional[User],
    db: AsyncSession,
) -> ProjectResponse:
    """Core logic to register an application creation request into projects table with conversation transcripts."""
    target_room_id = request.room_id

    # If room_id is omitted or null, find first room or room tied to conversation
    if not target_room_id and request.conversation_id:
        c_check = await db.execute(select(Conversation).where(Conversation.id == request.conversation_id))
        conv_obj = c_check.scalar_one_or_none()
        if conv_obj and conv_obj.room_id:
            target_room_id = conv_obj.room_id

    if not target_room_id:
        # Fallback to any active room or default workspace
        r_first = await db.execute(select(Room).order_by(Room.created_at.asc()).limit(1))
        first_room = r_first.scalar_one_or_none()
        if first_room:
            target_room_id = first_room.id
        else:
            # Create a default room workspace
            new_room = Room(
                id=str(uuid.uuid4()),
                name="Default Workspace",
                description="Default room for projects and client application requests",
                user_id=current_user.id if current_user else None,
            )
            db.add(new_room)
            await db.flush()
            target_room_id = new_room.id

    # Check room access if user authenticated
    r_res = await db.execute(select(Room).where(Room.id == target_room_id))
    room = r_res.scalar_one_or_none()
    if room and current_user:
        await check_room_access(room, current_user, db, required_role="editor")

    # Compile transcripts from conversation
    transcripts_content = ""
    if request.conversation_id:
        transcripts_content = await compile_conversation_transcripts(db, request.conversation_id)
    else:
        transcripts_content = f"=== APPLICATION REQUEST: {request.name} ===\nCreated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\nSummary: {request.description or 'No initial notes provided.'}"

    project_id = str(uuid.uuid4())
    meeting_link = request.meeting_link or generate_channel_meeting_link(request.communication_channel, project_id)

    project = Project(
        id=project_id,
        room_id=target_room_id,
        user_id=current_user.id if current_user else None,
        name=request.name.strip(),
        description=request.description.strip() if request.description else None,
        status="pending_call",
        request_type="app_creation",
        client_name=request.client_name.strip(),
        email=request.email.strip(),
        phone=request.phone.strip() if request.phone else None,
        communication_channel=request.communication_channel or "Gmeet",
        transcripts=transcripts_content,
        meeting_link=meeting_link,
        tags=request.tags or ["app-request", request.communication_channel.lower()],
        metadata_info={"created_via": "llm_chat_prompt", "source_conv_id": request.conversation_id},
    )
    db.add(project)

    if request.conversation_id:
        c_res = await db.execute(select(Conversation).where(Conversation.id == request.conversation_id))
        conv = c_res.scalar_one_or_none()
        if conv:
            conv.project_id = project.id

    await db.commit()
    await db.refresh(project)

    return serialize_project_response(project, conversation_count=1 if request.conversation_id else 0)


async def handle_initiate_call(
    project_id: str,
    request: InitiateCallRequest,
    current_user: Optional[User],
    db: AsyncSession,
) -> InitiateCallResponse:
    """Core logic to initiate a consultation call, ensuring conversation transcripts and meeting links are present."""
    p_res = await db.execute(select(Project).where(Project.id == project_id))
    project = p_res.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    channel = request.communication_channel or project.communication_channel or "Gmeet"
    link = request.meeting_link or project.meeting_link or generate_channel_meeting_link(channel, project.id)

    # If transcripts are empty, try to compile from any linked conversations
    if not project.transcripts:
        c_res = await db.execute(
            select(Conversation).where(Conversation.project_id == project.id).order_by(Conversation.updated_at.desc()).limit(1)
        )
        linked_conv = c_res.scalar_one_or_none()
        if linked_conv:
            project.transcripts = await compile_conversation_transcripts(db, linked_conv.id)
        else:
            project.transcripts = (
                f"=== CONSULTATION CALL TRANSCRIPT LOG: {project.name} ===\n"
                f"Client: {project.client_name or 'N/A'}\n"
                f"Email: {project.email or 'N/A'}\n"
                f"Phone: {project.phone or 'N/A'}\n"
                f"Channel: {channel}\n"
                f"Initiated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            )

    now = datetime.now(timezone.utc)
    project.status = "call_initiated"
    project.call_initiated_at = now
    project.communication_channel = channel
    project.meeting_link = link
    if request.call_notes:
        existing_notes = project.call_notes or ""
        project.call_notes = f"{existing_notes}\n[{now.strftime('%Y-%m-%d %H:%M')}]: {request.call_notes}".strip()

    await db.commit()
    await db.refresh(project)

    return InitiateCallResponse(
        project_id=project.id,
        name=project.name,
        request_type=project.request_type,
        client_name=project.client_name,
        email=project.email,
        phone=project.phone,
        communication_channel=project.communication_channel,
        meeting_link=project.meeting_link,
        transcripts=project.transcripts,
        call_initiated_at=project.call_initiated_at,
        status=project.status,
        message=f"Consultation call successfully initiated via {project.communication_channel} with complete conversation transcripts.",
    )


# Mount under /api/rooms/{room_id}/projects
@router.post("/app-request", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_app_request_scoped(
    room_id: str,
    request: AppCreationProjectRequest,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an application project request inside room workspace."""
    request.room_id = room_id
    return await handle_create_app_request(request, current_user, db)


@router.post("/{project_id}/initiate-call", response_model=InitiateCallResponse)
async def initiate_project_call_scoped(
    room_id: str,
    project_id: str,
    request: InitiateCallRequest = InitiateCallRequest(),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Initiate consultation call with transcripts for a project inside a room."""
    return await handle_initiate_call(project_id, request, current_user, db)


# Mount direct endpoints under /api/projects
@projects_direct_router.post("/app-request", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_app_request_direct(
    request: AppCreationProjectRequest,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an application project request from chat prompt with Name, Email, Phone, Channel, and Transcripts."""
    return await handle_create_app_request(request, current_user, db)


@projects_direct_router.post("/{project_id}/initiate-call", response_model=InitiateCallResponse)
async def initiate_project_call_direct(
    project_id: str,
    request: InitiateCallRequest = InitiateCallRequest(),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Initiate a consultation call on Gmeet/Teams/Zoom/others with conversation transcripts."""
    return await handle_initiate_call(project_id, request, current_user, db)


@projects_direct_router.get("/{project_id}/transcripts")
async def get_project_transcripts(
    project_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve full conversation transcripts associated with this project request."""
    p_res = await db.execute(select(Project).where(Project.id == project_id))
    project = p_res.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    transcripts = project.transcripts
    if not transcripts:
        # Check linked conversations
        c_res = await db.execute(
            select(Conversation).where(Conversation.project_id == project.id).order_by(Conversation.updated_at.desc()).limit(1)
        )
        linked_conv = c_res.scalar_one_or_none()
        if linked_conv:
            transcripts = await compile_conversation_transcripts(db, linked_conv.id)
            project.transcripts = transcripts
            await db.commit()

    return {
        "project_id": project.id,
        "name": project.name,
        "client_name": project.client_name,
        "email": project.email,
        "phone": project.phone,
        "communication_channel": project.communication_channel,
        "meeting_link": project.meeting_link,
        "transcripts": transcripts or "(No conversation transcripts recorded yet.)",
        "call_initiated_at": project.call_initiated_at,
        "status": project.status,
    }


@projects_direct_router.get("/{project_id}", response_model=ProjectResponse)
async def get_project_direct(
    project_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Get single project details directly by project ID."""
    p_res = await db.execute(select(Project).where(Project.id == project_id))
    project = p_res.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    c_count_res = await db.execute(
        select(func.count(Conversation.id)).where(Conversation.project_id == project_id)
    )
    c_count = c_count_res.scalar_one()

    return serialize_project_response(project, c_count)
