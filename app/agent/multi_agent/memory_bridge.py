"""Memory Bridge integrating Multi-Agent workflows with Two-Tier L1/L2 STM and LTM storage."""

from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.memory.manager import memory_manager
from app.models.memory import MemoryScope, MemoryType


class MultiAgentMemoryBridge:
    """Orchestrates short-term and long-term memory operations for multi-agent workflows."""

    @staticmethod
    async def retrieve_workflow_context(
        goal: str,
        user_id: Optional[str] = None,
        room_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Query existing STM & LTM memories to retrieve relevant prior context for the workflow."""
        try:
            context_str, memories = await memory_manager.retrieve_context(
                query=goal,
                user_id=user_id,
                room_id=room_id,
                top_k=4,
                max_tokens_budget=400,
                db=db,
            )
            return context_str, memories
        except Exception as e:
            logger.warning(f"Error querying memory bridge: {e}")
            return "", []

    @staticmethod
    async def save_subtask_stm(
        workflow_id: str,
        task_number: int,
        title: str,
        output_summary: str,
        user_id: Optional[str] = None,
        room_id: Optional[str] = None,
        ttl_seconds: int = 7200,  # 2 hours default for STM
        db: Optional[AsyncSession] = None,
    ) -> None:
        """Save intermediate task progress into Short-Term Memory (STM) with TTL."""
        key = f"workflow_{workflow_id}_task_{task_number}"
        content = f"Subtask {task_number} [{title}]: {output_summary[:500]}"
        scope = MemoryScope.USER_SPECIFIC.value if user_id else MemoryScope.GLOBAL.value

        try:
            await memory_manager.store_memory(
                scope=scope,
                memory_type=MemoryType.SHORT_TERM.value,
                key=key,
                content=content,
                user_id=user_id,
                room_id=room_id,
                ttl_seconds=ttl_seconds,
                importance=0.6,
                metadata_payload={"workflow_id": workflow_id, "task_number": task_number, "title": title},
                db=db,
            )
            logger.debug(f"Saved subtask {task_number} to STM: {key}")
        except Exception as e:
            logger.warning(f"Failed to save subtask STM memory: {e}")

    @staticmethod
    async def save_decision_or_spec_ltm(
        title: str,
        content: str,
        category: str = "strategic_decision",
        user_id: Optional[str] = None,
        room_id: Optional[str] = None,
        importance: float = 0.9,
        db: Optional[AsyncSession] = None,
    ) -> None:
        """Persist high-value strategic decisions, requirements, and validated solutions into Long-Term Memory (LTM)."""
        clean_title = title.lower().replace(" ", "_")[:50]
        key = f"ltm_{category}_{clean_title}"
        scope = MemoryScope.USER_SPECIFIC.value if user_id else MemoryScope.GLOBAL.value

        try:
            await memory_manager.store_memory(
                scope=scope,
                memory_type=MemoryType.LONG_TERM.value,
                key=key,
                content=content[:750],
                user_id=user_id,
                room_id=room_id,
                importance=importance,
                metadata_payload={"category": category, "title": title},
                db=db,
            )
            logger.info(f"Persisted high-value knowledge to LTM: {key}")
        except Exception as e:
            logger.warning(f"Failed to persist LTM memory: {e}")
