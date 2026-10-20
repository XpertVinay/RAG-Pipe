"""API Endpoints for Multi-Agent Workflows, Real-Time SSE Collaboration, and MCP Tools."""

import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.multi_agent.orchestrator import multi_agent_orchestrator
from app.agent.multi_agent.protocol import WorkflowInitRequest
from app.core.auth import get_optional_user
from app.core.logging import logger
from app.database import get_db
from app.mcp.protocol import MCPClientConfig, MCPTool
from app.mcp.registry import mcp_registry
from app.models.multi_agent import AgentSubTask, AgentWorkflow
from app.models.user import User

router = APIRouter(prefix="/agents", tags=["agents"])


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
            "status": t.status,
            "assigned_tools": t.assigned_tools,
            "mcp_provider": t.mcp_provider,
            "validation_score": t.validation_score,
            "validation_result": t.validation_result,
            "output_data": t.output_data,
            "execution_logs": t.execution_logs,
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
