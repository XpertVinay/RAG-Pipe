"""SQLAlchemy ORM models for Multi-Agent Workflow, Atomic Subtasks, and Execution Auditing."""

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class WorkflowStatus(str, enum.Enum):
    """Lifecycle status for a multi-agent workflow."""
    PENDING = "pending"
    PLANNING = "planning"
    RESEARCHING = "researching"
    GENERATING_TASKS = "generating_tasks"
    EXECUTING = "executing"
    VALIDATING = "validating"
    DEPLOYING = "deploying"
    COMPLETED = "completed"
    FAILED = "failed"


class SubTaskStatus(str, enum.Enum):
    """Lifecycle status for an atomic subtask."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    VALIDATED = "validated"
    RETRYING = "retrying"
    FAILED = "failed"
    DEPLOYED = "deployed"


class AgentRole(str, enum.Enum):
    """The 6 specialized multi-agent roles."""
    DECISION_MAKER = "decision_maker"
    RESEARCHER = "researcher"
    TASK_GENERATOR = "task_generator"
    TASK_EXECUTOR = "task_executor"
    VALIDATOR = "validator"
    DEPLOYER = "deployer"


class AgentWorkflow(Base):
    """Persisted multi-agent collaborative workflow."""

    __tablename__ = "agent_workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    room_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default=WorkflowStatus.PENDING.value, index=True)

    # Context window & summary tracking
    executive_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requirements_spec: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deployment_info: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    # Performance, context compaction & security telemetry
    metrics: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    tasks: Mapped[List["AgentSubTask"]] = relationship(
        "AgentSubTask", back_populates="workflow", cascade="all, delete-orphan", order_by="AgentSubTask.task_number"
    )
    user: Mapped[Optional["User"]] = relationship("User", lazy="joined")
    room: Mapped[Optional["Room"]] = relationship("Room", lazy="joined")


class AgentSubTask(Base):
    """Persisted atomic subtask executed by task executor and checked by validator."""

    __tablename__ = "agent_subtasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_number: Mapped[int] = mapped_column(Integer, default=1, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    agent_role: Mapped[str] = mapped_column(String(30), default=AgentRole.TASK_EXECUTOR.value, index=True)
    status: Mapped[str] = mapped_column(String(30), default=SubTaskStatus.PENDING.value, index=True)

    # MCP tool & provider metadata
    assigned_tools: Mapped[List[str]] = mapped_column(JSON, default=list)
    mcp_provider: Mapped[str] = mapped_column(String(100), default="native")
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=True)

    # Execution data contracts
    input_data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    output_data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    artifacts: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)

    # Validation & retry
    validation_result: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    validation_score: Mapped[float] = mapped_column(Float, default=1.0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)

    # Execution logs & context compaction
    execution_logs: Mapped[List[str]] = mapped_column(JSON, default=list)
    compact_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationship back to workflow
    workflow: Mapped["AgentWorkflow"] = relationship("AgentWorkflow", back_populates="tasks")
