"""API Endpoints for Multi-Agent Workflows, Real-Time SSE Collaboration, and MCP Tools."""

import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.multi_agent.orchestrator import multi_agent_orchestrator
from app.agent.multi_agent.protocol import WorkflowInitRequest
from app.config import get_settings
from app.core.auth import get_current_user, get_optional_user, is_admin, require_admin
from app.core.logging import logger
from app.database import get_db
from app.mcp.protocol import MCPClientConfig, MCPTool
from app.mcp.registry import mcp_registry
from app.models.document import AuditLog
from app.models.memory import MemoryItem
from app.models.multi_agent import AgentSubTask, AgentWorkflow
from app.models.user import User

router = APIRouter(prefix="/agents", tags=["agents"])
settings = get_settings()


@router.post("/workflows/stream", status_code=status.HTTP_200_OK)
async def stream_multi_agent_workflow(
    request: WorkflowInitRequest,
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Execute a collaborative multi-agent workflow and stream real-time SSE progress events."""
    user_id = current_user.id if current_user else None

    return StreamingResponse(
        multi_agent_orchestrator.execute_workflow_stream(
            request=request,
            user_id=user_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/advise", status_code=status.HTTP_200_OK)
async def advise_and_accomplish_workflow(
    request: WorkflowInitRequest,
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Initiate a call where Decision Maker advises the customer/user accordingly with the provided document (or admin/staff domain knowledge if none provided) for development and accomplishing the tasks."""
    user_id = current_user.id if current_user else None
    result = await multi_agent_orchestrator.advise_and_execute(
        request=request,
        user_id=user_id,
    )
    return result


@router.post("/workflows", status_code=status.HTTP_201_CREATED)
async def create_workflow(
    request: WorkflowInitRequest,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Initialize a multi-agent workflow record."""
    wf_id = str(uuid.uuid4())
    user_id = current_user.id if current_user else None

    wf = AgentWorkflow(
        id=wf_id,
        user_id=user_id,
        room_id=request.room_id,
        title=request.title or request.goal[:60],
        goal=request.goal,
        status="pending",
        is_anonymous=request.anonymous,
    )
    db.add(wf)
    await db.commit()
    await db.refresh(wf)

    return {
        "workflow_id": wf.id,
        "title": wf.title,
        "status": wf.status,
        "stream_url": f"/api/v1/agents/workflows/{wf.id}/stream",
    }


@router.get("/workflows", status_code=status.HTTP_200_OK)
async def list_workflows(
    limit: int = Query(20, ge=1, le=50),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """List recent collaborative workflows."""
    stmt = (
        select(AgentWorkflow)
        .options(selectinload(AgentWorkflow.tasks))
        .order_by(AgentWorkflow.created_at.desc())
        .limit(limit)
    )
    if current_user and getattr(current_user, "role", "user") != "admin":
        stmt = stmt.where(AgentWorkflow.user_id == current_user.id)

    res = await db.execute(stmt)
    workflows = res.scalars().all()

    output = []
    for wf in workflows:
        output.append({
            "id": wf.id,
            "title": wf.title,
            "goal": wf.goal,
            "status": wf.status,
            "created_at": wf.created_at.isoformat(),
            "task_count": len(wf.tasks),
            "metrics": wf.metrics,
        })
    return output


@router.get("/workflows/{workflow_id}", status_code=status.HTTP_200_OK)
async def get_workflow_details(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get full state, subtasks, logs, and metrics for a specific workflow."""
    stmt = (
        select(AgentWorkflow)
        .options(selectinload(AgentWorkflow.tasks))
        .where(AgentWorkflow.id == workflow_id)
    )
    res = await db.execute(stmt)
    wf = res.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    tasks_out = []
    for t in wf.tasks:
        tasks_out.append({
            "id": t.id,
            "task_number": t.task_number,
            "title": t.title,
            "description": t.description,
            "agent_role": t.agent_role or "task_executor",
            "status": t.status,
            "assigned_tools": t.assigned_tools or [],
            "mcp_provider": t.mcp_provider or "native",
            "validation_score": t.validation_score,
            "validation_result": t.validation_result or {},
            "output_data": t.output_data or {},
            "execution_logs": t.execution_logs or [],
            "compact_summary": t.compact_summary or "",
        })

    return {
        "id": wf.id,
        "title": wf.title,
        "goal": wf.goal,
        "status": wf.status,
        "executive_summary": wf.executive_summary,
        "requirements_spec": wf.requirements_spec,
        "deployment_info": wf.deployment_info,
        "metrics": wf.metrics,
        "created_at": wf.created_at.isoformat(),
        "tasks": tasks_out,
    }


@router.delete("/workflows", status_code=status.HTTP_200_OK)
async def clear_all_workflows(
    clear_logs: bool = Query(True, description="Also clear audit logs and operational traces"),
    optimize_db: bool = Query(True, description="Optimize database storage and reclaim disk space"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Clear all collaborative agent workflows and subtasks to optimize storage and database.
    
    Restricted to Super Admin and Admin roles.
    """
    logger.info(f"Admin {current_user.username} ({current_user.role}) initiated multi-agent workflow wipe.")

    # 1. Count and delete subtasks & workflows
    sub_res = await db.execute(delete(AgentSubTask))
    deleted_subtasks = sub_res.rowcount or 0

    wf_res = await db.execute(delete(AgentWorkflow))
    deleted_workflows = wf_res.rowcount or 0

    # 2. Clear workflow deliverable memory items
    mem_res = await db.execute(
        delete(MemoryItem).where(
            or_(
                MemoryItem.key.like("workflow_%"),
                MemoryItem.key.like("Workflow_%"),
            )
        )
    )
    deleted_memories = mem_res.rowcount or 0

    # 3. Clear audit logs if requested
    deleted_audit_logs = 0
    if clear_logs:
        audit_res = await db.execute(delete(AuditLog))
        deleted_audit_logs = audit_res.rowcount or 0

    await db.commit()

    # 4. Storage optimization & WAL checkpointing for SQLite
    storage_optimized = False
    if optimize_db and "sqlite" in settings.DATABASE_URL:
        try:
            await db.execute(text("PRAGMA wal_checkpoint(TRUNCATE);"))
            await db.execute(text("PRAGMA incremental_vacuum;"))
            await db.execute(text("PRAGMA optimize;"))
            await db.commit()
            storage_optimized = True
        except Exception as e:
            logger.warning(f"Database optimization note: {e}")

    return {
        "message": "All agent workflows and operational records have been permanently cleared. Database storage optimized.",
        "deleted_workflows": deleted_workflows,
        "deleted_subtasks": deleted_subtasks,
        "deleted_workflow_memories": deleted_memories,
        "deleted_audit_logs": deleted_audit_logs,
        "storage_optimized": storage_optimized,
    }


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_200_OK)
async def delete_single_workflow(
    workflow_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a specific agent workflow and its subtasks.
    
    Permitted for Super Admin, Admin, or the workflow owner.
    """
    stmt = select(AgentWorkflow).where(AgentWorkflow.id == workflow_id)
    res = await db.execute(stmt)
    wf = res.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    user_role = getattr(current_user, "role", "user")
    if user_role not in ("admin", "super_admin") and wf.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this workflow.")

    await db.execute(delete(AgentSubTask).where(AgentSubTask.workflow_id == workflow_id))
    await db.execute(delete(AgentWorkflow).where(AgentWorkflow.id == workflow_id))
    await db.commit()

    return {
        "message": f"Workflow '{wf.title}' deleted successfully.",
        "workflow_id": workflow_id,
    }


@router.delete("/logs", status_code=status.HTTP_200_OK)
async def clear_system_and_agent_logs(
    optimize_db: bool = Query(True, description="Optimize database storage and reclaim disk space"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Clear system audit logs and agent execution traces to optimize storage and database.
    
    Restricted to Super Admin and Admin roles.
    """
    logger.info(f"Admin {current_user.username} ({current_user.role}) initiated audit and agent logs purge.")

    # 1. Clear audit logs
    audit_res = await db.execute(delete(AuditLog))
    deleted_audit_logs = audit_res.rowcount or 0

    # 2. Reset execution logs in agent subtasks
    subtask_update = await db.execute(
        update(AgentSubTask).values(execution_logs=[])
    )
    cleared_subtasks_logs = subtask_update.rowcount or 0

    await db.commit()

    # 3. Storage optimization & WAL checkpointing for SQLite
    storage_optimized = False
    if optimize_db and "sqlite" in settings.DATABASE_URL:
        try:
            await db.execute(text("PRAGMA wal_checkpoint(TRUNCATE);"))
            await db.execute(text("PRAGMA incremental_vacuum;"))
            await db.execute(text("PRAGMA optimize;"))
            await db.commit()
            storage_optimized = True
        except Exception as e:
            logger.warning(f"Database optimization note: {e}")

    return {
        "message": "System audit logs and agent execution logs cleared successfully. Database storage optimized.",
        "deleted_audit_logs": deleted_audit_logs,
        "cleared_subtasks_logs": cleared_subtasks_logs,
        "storage_optimized": storage_optimized,
    }


@router.get("/tools", response_model=List[MCPTool])
async def list_available_tools():
    """List all registered MCP tools and native tools available for agent assignment."""
    return await mcp_registry.list_all_tools()


@router.post("/tools/mcp/register", status_code=status.HTTP_201_CREATED)
async def register_mcp_provider(config: MCPClientConfig):
    """Register an external third-party MCP provider with anonymous proxying."""
    try:
        client = mcp_registry.register_mcp_client(config)
        tools = await client.list_tools(force_refresh=True)
        return {
            "message": f"Registered MCP provider '{config.provider_id}' successfully.",
            "discovered_tools": [t.name for t in tools],
            "anonymous_proxy_enabled": config.anonymous,
        }
    except Exception as e:
        logger.error(f"Failed to register MCP provider: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to register MCP provider: {str(e)}")
