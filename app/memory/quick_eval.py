"""Compact Semantic Synthesis of Short-Term and Long-Term Memory for Quick Chat and Room Evaluation."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.memory import MemoryItem, MemoryScope, MemoryType


def utc_now() -> datetime:
    """Current UTC datetime."""
    return datetime.now(timezone.utc)


class CompactMemoryItem(BaseModel):
    """Compact meaning item for quick evaluation."""
    id: str
    memory_type: str  # "short_term" or "long_term"
    scope: str        # "global" or "user_specific"
    key: str
    meaning_intent: str
    compact_content: str
    importance: float
    age_hours: float


class CompactMemoryEvalResponse(BaseModel):
    """Complete compact memory evaluation payload for next new chats and rooms."""
    room_id: Optional[str] = None
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    evaluated_at: datetime = Field(default_factory=utc_now)
    total_memories: int
    short_term_count: int
    long_term_count: int
    compact_synthesis: str
    active_intent_summary: str
    enduring_constraints: List[str]
    short_term_items: List[CompactMemoryItem]
    long_term_items: List[CompactMemoryItem]
    raw_estimated_tokens: int
    compact_tokens: int
    tokens_saved_percent: float
    readiness_score: float  # 0.0 to 1.0


class QuickMemoryEvaluator:
    """Evaluates short-term and long-term memory into high-density semantic summaries."""

    @staticmethod
    def estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)

    @classmethod
    async def evaluate_room_context(
        cls,
        db: AsyncSession,
        room_id: Optional[str] = None,
        project_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 30,
    ) -> CompactMemoryEvalResponse:
        """Extract and evaluate compact short-term and long-term memories for quick injection into new chats/rooms."""
        now = utc_now()

        conditions = [MemoryItem.scope == MemoryScope.GLOBAL.value]
        if user_id:
            conditions.append((MemoryItem.scope == MemoryScope.USER_SPECIFIC.value) & (MemoryItem.user_id == user_id))
        if room_id:
            conditions.append(MemoryItem.room_id == room_id)
        if project_id:
            conditions.append(MemoryItem.project_id == project_id)

        stmt = (
            select(MemoryItem)
            .where(or_(*conditions))
            .where(or_(MemoryItem.expires_at.is_(None), MemoryItem.expires_at > now))
            .order_by(MemoryItem.importance.desc(), MemoryItem.updated_at.desc())
            .limit(limit)
        )

        res = await db.execute(stmt)
        memories = list(res.scalars().all())

        stm_items: List[CompactMemoryItem] = []
        ltm_items: List[CompactMemoryItem] = []
        raw_char_sum = 0

        for m in memories:
            raw_char_sum += len(m.content) + len(m.key)
            ts = m.updated_at or m.created_at
            if ts:
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_hours = round(max(0.0, (now - ts).total_seconds() / 3600.0), 1)
            else:
                age_hours = 0.0

            # Extract meaning intent
            meta = m.metadata_payload or {}
            meaning = meta.get("meaning_intent") or meta.get("trigger") or m.key.replace("_", " ").title()

            # Compact representation (trim noise, emphasize payload)
            compact_text = m.content.strip()
            if len(compact_text) > 160:
                compact_text = compact_text[:157] + "..."

            item = CompactMemoryItem(
                id=m.id,
                memory_type=m.memory_type,
                scope=m.scope,
                key=m.key,
                meaning_intent=meaning,
                compact_content=compact_text,
                importance=m.importance,
                age_hours=age_hours,
            )

            if m.memory_type == MemoryType.SHORT_TERM.value:
                stm_items.append(item)
            else:
                ltm_items.append(item)

        # Synthesize meaning paragraphs
        stm_points = [f"{i.meaning_intent}: {i.compact_content}" for i in stm_items[:4]]
        ltm_points = [f"{i.meaning_intent}: {i.compact_content}" for i in ltm_items[:4]]

        active_intent = "; ".join(stm_points) if stm_points else "No active short-term inquiries logged."
        enduring = ltm_points if ltm_points else ["Default enterprise guidelines and factual grounding."]

        synthesis_parts = []
        if stm_points:
            synthesis_parts.append(f"Short-Term Working Focus: {'; '.join(stm_points)}.")
        if ltm_points:
            synthesis_parts.append(f"Long-Term Preferences & Constraints: {'; '.join(ltm_points)}.")

        compact_synthesis = " ".join(synthesis_parts) if synthesis_parts else "Standard verified document workspace context."

        compact_tokens = cls.estimate_tokens(compact_synthesis)
        raw_tokens = max(compact_tokens, cls.estimate_tokens(" " * raw_char_sum))
        tokens_saved = max(0, raw_tokens - compact_tokens)
        pct_saved = round((tokens_saved / raw_tokens * 100.0), 1) if raw_tokens > 0 else 0.0

        # Readiness score based on presence of context
        readiness = 0.5
        if stm_items and ltm_items:
            readiness = 0.95
        elif stm_items or ltm_items:
            readiness = 0.80

        return CompactMemoryEvalResponse(
            room_id=room_id,
            project_id=project_id,
            user_id=user_id,
            evaluated_at=now,
            total_memories=len(memories),
            short_term_count=len(stm_items),
            long_term_count=len(ltm_items),
            compact_synthesis=compact_synthesis,
            active_intent_summary=active_intent,
            enduring_constraints=enduring,
            short_term_items=stm_items,
            long_term_items=ltm_items,
            raw_estimated_tokens=raw_tokens,
            compact_tokens=compact_tokens,
            tokens_saved_percent=pct_saved,
            readiness_score=readiness,
        )


quick_memory_evaluator = QuickMemoryEvaluator()
