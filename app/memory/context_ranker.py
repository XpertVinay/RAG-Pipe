"""Memory ranking and context assembly component adhering to Single Responsibility Principle."""

import re
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import MemoryItem, MemoryScope, MemoryType


class MemoryContextRanker:
    """Ranks and formats relevant memory items within token budgets for LLM context injection."""

    @staticmethod
    def build_candidate_query(
        now,
        user_id: Optional[str] = None,
        room_id: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
        limit: int = 30,
    ):
        """Construct SQLAlchemy query for candidate memories matching global and user/room scopes."""
        conditions = [
            MemoryItem.scope == MemoryScope.GLOBAL.value,
        ]
        if user_id:
            conditions.append(
                (MemoryItem.scope == MemoryScope.USER_SPECIFIC.value) & (MemoryItem.user_id == user_id)
            )
        if room_id:
            conditions.append(MemoryItem.room_id == room_id)
        if document_ids:
            conditions.append(MemoryItem.document_id.in_(document_ids))

        return (
            select(MemoryItem)
            .where(or_(*conditions))
            .where(or_(MemoryItem.expires_at.is_(None), MemoryItem.expires_at > now))
            .order_by(MemoryItem.importance.desc(), MemoryItem.updated_at.desc())
            .limit(limit)
        )

    @classmethod
    def score_candidates(
        cls,
        candidates: List[MemoryItem],
        query: str,
        top_k: int = 4,
    ) -> List[MemoryItem]:
        """Score candidate memories based on token overlap, importance, and recency boosts."""
        tokens = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 2]
        scored_memories: List[Tuple[float, MemoryItem]] = []

        for mem in candidates:
            mem_text = f"{mem.key} {mem.content}".lower()
            overlap_score = sum(1.0 for token in tokens if token in mem_text)

            # Boost user-specific over global for personalization
            user_boost = 1.3 if mem.scope == MemoryScope.USER_SPECIFIC.value else 1.0
            # Boost short-term for recent context immediacy
            type_boost = 1.2 if mem.memory_type == MemoryType.SHORT_TERM.value else 1.0

            final_score = (overlap_score + (mem.importance * 2.0)) * user_boost * type_boost
            scored_memories.append((final_score, mem))

        scored_memories.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored_memories[:top_k]]

    @classmethod
    def format_context_string(
        cls,
        top_candidates: List[MemoryItem],
        max_tokens_budget: int = 250,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Pack highest-ranked memories into a compact context string respecting token budget."""
        max_chars = max_tokens_budget * 4
        lines = []
        current_chars = 0
        consulted_list = []

        for m in top_candidates:
            scope_tag = "User" if m.scope == MemoryScope.USER_SPECIFIC.value else "Global"
            type_tag = "STM" if m.memory_type == MemoryType.SHORT_TERM.value else "LTM"
            line = f"• [{scope_tag}:{type_tag}] {m.key}: {m.content}"

            if current_chars + len(line) > max_chars:
                break

            lines.append(line)
            current_chars += len(line)
            consulted_list.append({
                "id": m.id,
                "scope": m.scope,
                "type": m.memory_type,
                "key": m.key,
                "content": m.content,
            })

        if not lines:
            return "", []

        context_str = "--- Relevant Memory Context ---\n" + "\n".join(lines) + "\n-------------------------------"
        return context_str, consulted_list


memory_context_ranker = MemoryContextRanker()
