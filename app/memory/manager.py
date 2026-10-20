"""Memory Manager orchestrating Two-Tier L1/L2 storage, dual-scoping, and low-memory context retrieval."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.config import get_settings
from app.core.logging import logger
from app.memory.context_ranker import memory_context_ranker
from app.memory.distiller import memory_distiller
from app.memory.l1_cache import CachedMemoryEntry, LowMemoryLRUCache
from app.memory.schemas import MemoryDistributionStats
from app.models.memory import MemoryItem, MemoryType

settings = get_settings()


def utc_now() -> datetime:
    """Current UTC datetime."""
    return datetime.now(timezone.utc)


class MemoryManager:
    """Orchestrator for Low-Memory Two-Tier STM/LTM with automatic expiry and document revaluation."""

    def __init__(self, max_l1_items: Optional[int] = None, max_l1_bytes: Optional[int] = None):
        items = max_l1_items if max_l1_items is not None else getattr(settings, "MEMORY_L1_MAX_ITEMS", 512)
        bytes_limit = max_l1_bytes if max_l1_bytes is not None else getattr(settings, "MEMORY_L1_MAX_BYTES", 2 * 1024 * 1024)
        # L1 In-Memory LRU Cache with strict ceiling
        self.l1_cache = LowMemoryLRUCache(max_items=items, max_bytes=bytes_limit)
        self.ranker = memory_context_ranker
        self.distiller = memory_distiller

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
        revaluation_interval_seconds: Optional[int] = None,
        importance: float = 0.5,
        metadata_payload: Optional[Dict[str, Any]] = None,
        db: Optional[AsyncSession] = None,
    ) -> MemoryItem:
        """Store or update a memory item in both L2 (SQLite) and L1 (In-Memory LRU)."""
        content_clean = content.strip()[:800]
        meta = metadata_payload or {}
        now = utc_now()
        reval_interval = revaluation_interval_seconds or getattr(settings, "MEMORY_REVALUATION_INTERVAL_SECONDS", 86400)

        expires_at: Optional[datetime] = None
        if ttl_seconds is not None and ttl_seconds > 0:
            expires_at = now + timedelta(seconds=ttl_seconds)
        elif memory_type == MemoryType.SHORT_TERM.value:
            stm_hours = getattr(settings, "MEMORY_STM_TTL_HOURS", 2)
            expires_at = now + timedelta(hours=stm_hours)
        elif memory_type == MemoryType.LONG_TERM.value and ttl_seconds is None:
            ltm_days = getattr(settings, "MEMORY_LTM_TTL_DAYS", 90)
            expires_at = now + timedelta(days=ltm_days)

        async def _do_upsert(session: AsyncSession) -> MemoryItem:
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
                existing.revaluation_interval_seconds = reval_interval
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
                    revaluation_interval_seconds=reval_interval,
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
        cached = self.l1_cache.get(scope=scope, key=key, user_id=user_id)
        if cached:
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
        """Retrieve most salient memories for query injection using dedicated ranking component."""
        now = utc_now()

        async def _retrieve(session: AsyncSession) -> List[MemoryItem]:
            stmt = self.ranker.build_candidate_query(
                now=now,
                user_id=user_id,
                room_id=room_id,
                document_ids=document_ids,
                limit=30,
            )
            res = await session.execute(stmt)
            return list(res.scalars().all())

        if db:
            candidates = await _retrieve(db)
        else:
            async with database.AsyncSessionLocal() as session:
                candidates = await _retrieve(session)

        if not candidates:
            return "", []

        top_candidates = self.ranker.score_candidates(candidates, query=query, top_k=top_k)
        return self.ranker.format_context_string(top_candidates, max_tokens_budget=max_tokens_budget)

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
        await self.distiller.consolidate_interaction(
            manager=self,
            query=query,
            answer=answer,
            user_id=user_id,
            room_id=room_id,
            document_ids=document_ids,
            db=db,
        )

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
        await self.distiller.record_chat_turn_memory(
            manager=self,
            user_id=user_id,
            room_id=room_id,
            conversation_id=conversation_id,
            query=query,
            answer=answer,
            db=db,
        )

    async def get_distribution_stats(self, db: Optional[AsyncSession] = None) -> MemoryDistributionStats:
        """Calculate complete 4-quadrant distribution matrix and low-memory performance metrics."""
        from app.memory.stats import memory_stats_collector

        now = utc_now()

        async def _calc(session: AsyncSession) -> MemoryDistributionStats:
            all_mems_res = await session.execute(select(MemoryItem))
            all_mems = list(all_mems_res.scalars().all())
            l1_stats = self.l1_cache.get_stats()
            return memory_stats_collector.calculate_stats(all_mems, l1_stats, now)

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


memory_manager = MemoryManager()
