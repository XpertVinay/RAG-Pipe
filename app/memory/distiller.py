"""Memory distillation component extracting conversation insights, short-term context, and long-term preferences."""

import re
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.memory import MemoryScope, MemoryType


def utc_now() -> datetime:
    """Current UTC datetime."""
    return datetime.now(timezone.utc)


class MemoryDistiller:
    """Distills conversational interactions into structured short-term and long-term memories."""

    @classmethod
    async def consolidate_interaction(
        cls,
        manager,
        query: str,
        answer: str,
        user_id: Optional[str] = None,
        room_id: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
        db: Optional[AsyncSession] = None,
    ) -> None:
        """Autonomously extract and consolidate short-term & long-term memory nuggets after a chat turn."""
        clean_q = query.strip()
        if len(clean_q) < 6:
            return

        # 1. User Short-Term Memory: Active inquiry context (expires in 2 hours)
        topic_key = "last_inquiry:" + re.sub(r"[^a-zA-Z0-9_]", "_", clean_q[:25]).strip("_").lower()
        await manager.store_memory(
            scope=MemoryScope.USER_SPECIFIC.value if user_id else MemoryScope.GLOBAL.value,
            memory_type=MemoryType.SHORT_TERM.value,
            key=topic_key,
            content=f"User asked about: {clean_q[:120]}",
            user_id=user_id,
            room_id=room_id,
            ttl_seconds=7200,  # 2 hours
            importance=0.4,
            db=db,
        )

        # 2. Extract explicit preferences if present (e.g., "I prefer", "always give me", "I am a ...")
        pref_match = re.search(r"(?:i prefer|always|remember that|my name is|i am a)\s+([^.!?]+)", clean_q, re.IGNORECASE)
        if pref_match and user_id:
            fact = pref_match.group(0).strip()
            await manager.store_memory(
                scope=MemoryScope.USER_SPECIFIC.value,
                memory_type=MemoryType.LONG_TERM.value,
                key=f"user_pref:{re.sub(r'[^a-zA-Z0-9_]', '_', fact[:20]).lower()}",
                content=fact[:150],
                user_id=user_id,
                room_id=room_id,
                ttl_seconds=30 * 86400,  # 30 days
                importance=0.9,
                db=db,
            )

    @classmethod
    async def record_chat_turn_memory(
        cls,
        manager,
        user_id: Optional[str],
        room_id: Optional[str],
        conversation_id: str,
        query: str,
        answer: str,
        db: Optional[AsyncSession] = None,
    ) -> None:
        """Automatically distill and persist Short-Term and Long-Term memory for the user's chat."""
        if not user_id:
            return

        now = utc_now()
        # 1. Short-Term Memory (STM): recent interaction context (TTL: 2 hours)
        clean_query = query.strip()[:140]
        clean_ans = answer.strip()[:200]
        stm_content = f"Recent query: {clean_query} -> Context: {clean_ans}"
        stm_key = f"chat_stm_{conversation_id[:8]}"

        try:
            await manager.store_memory(
                scope=MemoryScope.USER_SPECIFIC.value,
                memory_type=MemoryType.SHORT_TERM.value,
                key=stm_key,
                content=stm_content,
                user_id=user_id,
                room_id=room_id,
                ttl_seconds=7200,  # 2 hours
                importance=0.6,
                metadata_payload={"conversation_id": conversation_id, "recorded_at": now.isoformat()},
                db=db,
            )
        except Exception as stm_err:
            logger.warning(f"Error persisting chat STM: {stm_err}")

        # 2. Extract potential Long-Term Memory (LTM) user preferences/facts (TTL: 90 days)
        lower_q = query.lower()
        pref_triggers = ["i prefer", "my name is", "i am a", "i work on", "remember that", "always format", "my project is"]
        matched_trigger = next((t for t in pref_triggers if t in lower_q), None)

        if matched_trigger:
            pref_content = query.strip()[:300]
            pref_key = f"pref_{matched_trigger.replace(' ', '_')}"
            try:
                await manager.store_memory(
                    scope=MemoryScope.USER_SPECIFIC.value,
                    memory_type=MemoryType.LONG_TERM.value,
                    key=pref_key,
                    content=pref_content,
                    user_id=user_id,
                    room_id=room_id,
                    ttl_seconds=90 * 86400,  # 90 days
                    importance=0.85,
                    metadata_payload={"trigger": matched_trigger, "conversation_id": conversation_id},
                    db=db,
                )
            except Exception as ltm_err:
                logger.warning(f"Error persisting chat LTM: {ltm_err}")


memory_distiller = MemoryDistiller()
