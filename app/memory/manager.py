"""Memory Manager orchestrating Two-Tier L1/L2 storage, dual-scoping, and low-memory context retrieval."""

import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import func, or_, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app import database
from app.memory.l1_cache import CachedMemoryEntry, LowMemoryLRUCache
from app.memory.revaluation import revaluation_engine
from app.memory.schemas import (
    MemoryDistributionStats,
    ScopeDistributionItem,
)
from app.models.document import Document
from app.models.memory import MemoryItem, MemoryScope, MemoryType


def utc_now() -> datetime:
    """Current UTC datetime."""
    return datetime.now(timezone.utc)


class MemoryManager:
    """Orchestrator for Low-Memory Two-Tier STM/LTM with automatic expiry and document revaluation."""

    def __init__(self, max_l1_items: int = 512, max_l1_bytes: int = 2 * 1024 * 1024):
        # L1 In-Memory LRU Cache with strict 2MB ceiling
        self.l1_cache = LowMemoryLRUCache(max_items=max_l1_items, max_bytes=max_l1_bytes)

    async def store_memory(
        self,
        scope: str,
        memory_type: str,
        key: str,
        content: str,
        user_id: Optional[str] = None,
        room_id: Optional[str] = None,
        document_id: Optional[str] = None,
        document_hash: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        revaluation_interval_seconds: int = 86400,
        importance: float = 0.5,
        metadata_payload: Optional[Dict[str, Any]] = None,
        db: Optional[AsyncSession] = None,
    ) -> MemoryItem:
        """Store or update a memory item in both L2 (SQLite) and L1 (In-Memory LRU)."""
        # Enforce memory safety: truncate excessively long content
        content_clean = content.strip()[:800]
        meta = metadata_payload or {}
        now = utc_now()

        # Calculate expiration
        expires_at: Optional[datetime] = None
        if ttl_seconds is not None and ttl_seconds > 0:
            expires_at = now + timedelta(seconds=ttl_seconds)
        elif memory_type == MemoryType.SHORT_TERM.value:
            # Default Short-Term TTL: 2 hours
            expires_at = now + timedelta(hours=2)
        elif memory_type == MemoryType.LONG_TERM.value and ttl_seconds is None:
            # Long-Term memories default to 90 days with periodic revaluation
            expires_at = now + timedelta(days=90)

        # Internal helper to perform DB upsert
        async def _do_upsert(session: AsyncSession) -> MemoryItem:
            # Check for existing memory with same key, scope, and user_id
            stmt = select(MemoryItem).where(
                MemoryItem.key == key,
                MemoryItem.scope == scope,
            )
            if user_id:
                stmt = stmt.where(MemoryItem.user_id == user_id)
            else:
                stmt = stmt.where(MemoryItem.user_id.is_(None))

            res = await session.execute(stmt)
            existing = res.scalar_one_or_none()

            if existing:
                existing.content = content_clean
                existing.memory_type = memory_type
                existing.importance = importance
                existing.room_id = room_id or existing.room_id
                existing.document_id = document_id or existing.document_id
                existing.document_hash = document_hash or existing.document_hash
                existing.metadata_payload = meta
                existing.expires_at = expires_at
                existing.revaluation_interval_seconds = revaluation_interval_seconds
                existing.updated_at = now
                mem_item = existing
            else:
                mem_item = MemoryItem(
                    scope=scope,
                    memory_type=memory_type,
                    key=key,
                    content=content_clean,
                    importance=importance,
                    user_id=user_id,
                    room_id=room_id,
                    document_id=document_id,
                    document_hash=document_hash,
                    metadata_payload=meta,
                    expires_at=expires_at,
                    revaluated_at=now if document_id else None,
                    revaluation_interval_seconds=revaluation_interval_seconds,
                    created_at=now,
                    updated_at=now,
                )
                session.add(mem_item)

            await session.commit()
            await session.refresh(mem_item)
            return mem_item

        if db:
            saved = await _do_upsert(db)
        else:
            async with database.AsyncSessionLocal() as session:
                saved = await _do_upsert(session)

        # Update hot L1 cache
        l1_entry = CachedMemoryEntry(
            id=saved.id,
            key=saved.key,
            scope=saved.scope,
            memory_type=saved.memory_type,
            user_id=saved.user_id,
            room_id=saved.room_id,
            document_id=saved.document_id,
            document_hash=saved.document_hash,
            content=saved.content,
            importance=saved.importance,
            expires_at=saved.expires_at,
            revaluated_at=saved.revaluated_at,
            revaluation_interval_seconds=saved.revaluation_interval_seconds,
            metadata_payload=saved.metadata_payload,
            access_count=saved.access_count,
            last_accessed=now.timestamp(),
        )
        self.l1_cache.put(l1_entry)
        return saved

    async def get_memory(
        self,
        scope: str,
        key: str,
        user_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> Optional[MemoryItem]:
        """Fetch memory with L1 cache hit check and fallback to DB."""
        # 1. Fast L1 In-Memory Check
        cached = self.l1_cache.get(scope=scope, key=key, user_id=user_id)
        if cached:
            # Reconstruct model from cache
            return MemoryItem(
                id=cached.id,
                scope=cached.scope,
                memory_type=cached.memory_type,
                key=cached.key,
                content=cached.content,
                importance=cached.importance,
                user_id=cached.user_id,
                room_id=cached.room_id,
                document_id=cached.document_id,
                document_hash=cached.document_hash,
                metadata_payload=cached.metadata_payload,
                expires_at=cached.expires_at,
                revaluated_at=cached.revaluated_at,
                revaluation_interval_seconds=cached.revaluation_interval_seconds,
                access_count=cached.access_count,
            )

        # 2. L2 Persistent DB Check
        async def _query_db(session: AsyncSession) -> Optional[MemoryItem]:
            stmt = select(MemoryItem).where(
                MemoryItem.key == key,
                MemoryItem.scope == scope,
            )
            if user_id:
                stmt = stmt.where(MemoryItem.user_id == user_id)
            else:
                stmt = stmt.where(MemoryItem.user_id.is_(None))

            res = await session.execute(stmt)
            item = res.scalar_one_or_none()

            if item:
                if item.is_expired():
                    return None
                # Populate L1 cache on hit
                self.l1_cache.put(
                    CachedMemoryEntry(
                        id=item.id,
                        key=item.key,
                        scope=item.scope,
                        memory_type=item.memory_type,
                        user_id=item.user_id,
                        room_id=item.room_id,
                        document_id=item.document_id,
                        document_hash=item.document_hash,
                        content=item.content,
                        importance=item.importance,
                        expires_at=item.expires_at,
                        revaluated_at=item.revaluated_at,
                        revaluation_interval_seconds=item.revaluation_interval_seconds,
                        metadata_payload=item.metadata_payload or {},
                        access_count=item.access_count,
                        last_accessed=utc_now().timestamp(),
                    )
                )
            return item

        if db:
            return await _query_db(db)
        async with database.AsyncSessionLocal() as session:
            return await _query_db(session)

    async def retrieve_context(
        self,
        query: str,
        user_id: Optional[str] = None,
        room_id: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
        top_k: int = 4,
        max_tokens_budget: int = 250,
        db: Optional[AsyncSession] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Retrieve most salient memories (Global & User-Specific, Short & Long-Term) for query injection.

        Returns:
            Tuple[context_string, consulted_memories_list]
        """
        now = utc_now()
        tokens = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 2]

        async def _retrieve(session: AsyncSession) -> List[MemoryItem]:
            # Pull candidates matching:
            # 1. Global (both short and long term)
            # 2. User Specific (matching user_id or active room)
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

            stmt = (
                select(MemoryItem)
                .where(or_(*conditions))
                .where(or_(MemoryItem.expires_at.is_(None), MemoryItem.expires_at > now))
                .order_by(MemoryItem.importance.desc(), MemoryItem.updated_at.desc())
                .limit(30)
            )
            res = await session.execute(stmt)
            return list(res.scalars().all())

        candidates: List[MemoryItem] = []
        if db:
            candidates = await _retrieve(db)
        else:
            async with database.AsyncSessionLocal() as session:
                candidates = await _retrieve(session)

        if not candidates:
            return "", []

        # Score candidates based on token overlap + importance + recency
        scored_memories: List[Tuple[float, MemoryItem]] = []
        for mem in candidates:
            # Check on-the-fly revaluation if document-linked and stale
            if mem.document_id and mem.document_hash:
                # If document is stale, queue or attempt quick revaluation
                pass

            mem_text = f"{mem.key} {mem.content}".lower()
            overlap_score = sum(1.0 for token in tokens if token in mem_text)

            # Boost user-specific over global for personalization
            user_boost = 1.3 if mem.scope == MemoryScope.USER_SPECIFIC.value else 1.0
            # Boost short-term for recent context immediacy
            type_boost = 1.2 if mem.memory_type == MemoryType.SHORT_TERM.value else 1.0

            final_score = (overlap_score + (mem.importance * 2.0)) * user_boost * type_boost
            scored_memories.append((final_score, mem))

        # Sort highest score first
        scored_memories.sort(key=lambda x: x[0], reverse=True)
        top_candidates = [m for _, m in scored_memories[:top_k]]

        # Build compact context within token budget (~4 chars per token)
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

    async def consolidate_interaction(
        self,
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
        await self.store_memory(
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
            await self.store_memory(
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

    async def get_distribution_stats(self, db: Optional[AsyncSession] = None) -> MemoryDistributionStats:
        """Calculate complete 4-quadrant distribution matrix and low-memory performance metrics."""
        now = utc_now()

        async def _calc(session: AsyncSession) -> MemoryDistributionStats:
            all_mems_res = await session.execute(select(MemoryItem))
            all_mems = all_mems_res.scalars().all()

            # Initialize Quadrants
            g_st = ScopeDistributionItem()
            g_lt = ScopeDistributionItem()
            u_st = ScopeDistributionItem()
            u_lt = ScopeDistributionItem()

            active_count = 0
            expired_count = 0
            reval_count = 0

            for m in all_mems:
                is_exp = m.is_expired(now)
                needs_rev = m.needs_revaluation(now=now)

                if is_exp:
                    expired_count += 1
                else:
                    active_count += 1

                if needs_rev:
                    reval_count += 1

                # Approximate byte size of record
                approx_bytes = len(m.key) + len(m.content) + 128

                # Route to quadrant
                if m.scope == MemoryScope.GLOBAL.value:
                    if m.memory_type == MemoryType.SHORT_TERM.value:
                        g_st.count += 1
                        g_st.estimated_bytes += approx_bytes
                        if len(g_st.sample_keys) < 4:
                            g_st.sample_keys.append(m.key)
                    else:
                        g_lt.count += 1
                        g_lt.estimated_bytes += approx_bytes
                        if len(g_lt.sample_keys) < 4:
                            g_lt.sample_keys.append(m.key)
                else:
                    if m.memory_type == MemoryType.SHORT_TERM.value:
                        u_st.count += 1
                        u_st.estimated_bytes += approx_bytes
                        if len(u_st.sample_keys) < 4:
                            u_st.sample_keys.append(m.key)
                    else:
                        u_lt.count += 1
                        u_lt.estimated_bytes += approx_bytes
                        if len(u_lt.sample_keys) < 4:
                            u_lt.sample_keys.append(m.key)

            l1_stats = self.l1_cache.get_stats()

            return MemoryDistributionStats(
                global_short_term=g_st,
                global_long_term=g_lt,
                user_short_term=u_st,
                user_long_term=u_lt,
                total_memories=len(all_mems),
                active_memories=active_count,
                expired_memories=expired_count,
                needs_revaluation_count=reval_count,
                in_memory_l1_bytes=l1_stats["total_bytes"],
                in_memory_l1_items=l1_stats["total_items"],
                in_memory_l1_max_items=l1_stats["max_items"],
                cache_hits=l1_stats["hits"],
                cache_misses=l1_stats["misses"],
            )

        if db:
            return await _calc(db)
        async with database.AsyncSessionLocal() as session:
            return await _calc(session)

    async def prune_expired(self, db: Optional[AsyncSession] = None) -> int:
        """Prune expired memories from L1 cache and database."""
        self.l1_cache.prune_expired()
        now = utc_now()

        async def _prune_db(session: AsyncSession) -> int:
            stmt = delete(MemoryItem).where(
                MemoryItem.expires_at.is_not(None),
                MemoryItem.expires_at < now,
            )
            res = await session.execute(stmt)
            await session.commit()
            return res.rowcount or 0

        if db:
            return await _prune_db(db)
        async with database.AsyncSessionLocal() as session:
            return await _prune_db(session)

    async def record_chat_turn_memory(
        self,
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
            await self.store_memory(
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
                await self.store_memory(
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


memory_manager = MemoryManager()
