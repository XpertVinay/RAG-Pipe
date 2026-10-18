"""Document and Context Revaluation Engine for updating stale or expired memory context."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.logging import logger
from app.models.document import Document, DocumentChunk
from app.models.memory import MemoryItem, MemoryType
from app.providers.factory import ModelFactory


def utc_now() -> datetime:
    """Current UTC datetime."""
    return datetime.now(timezone.utc)


REVALUATION_PROMPT = """You are a Memory Context Revaluator.
Your goal is to inspect the latest document chunks and distill an ultra-compact, high-density, updated factual summary (maximum 2-3 sentences) specifically answering or updating the context for the topic key: "{key}".

Original Cached Context:
"{original_content}"

Latest Document Chunks:
{document_context}

Return ONLY the updated factual synthesis. Keep it concise, direct, and under 300 characters. Do not include fluff, preamble, or markdown formatting."""


class MemoryRevaluationEngine:
    """Engine that checks document staleness, re-evaluates expired or updated contexts, and refreshes memory."""

    async def check_and_revaluate(
        self,
        memory: MemoryItem,
        db: AsyncSession,
        doc_obj: Optional[Document] = None,
        force: bool = False,
    ) -> bool:
        """Check if a memory item requires revaluation and re-evaluate if needed."""
        if not memory.document_id:
            # Memory not linked to a document; check if expired
            if memory.is_expired():
                # For non-document memories that expired, check if they should be pruned
                return False
            return False

        # Load document if not passed
        if doc_obj is None:
            doc_res = await db.execute(select(Document).where(Document.id == memory.document_id))
            doc_obj = doc_res.scalar_one_or_none()

        # If document was deleted, remove the orphan memory
        if not doc_obj:
            logger.info(f"Document {memory.document_id} was deleted; purging memory {memory.id} ('{memory.key}')")
            await db.delete(memory)
            await db.commit()
            return True

        # Check staleness
        needs_update = force or memory.needs_revaluation(current_doc_hash=doc_obj.file_hash)
        if not needs_update:
            return False

        logger.info(f"Revaluating memory {memory.id} ('{memory.key}') for document {doc_obj.filename}")

        # Fetch latest document chunks
        chunks_res = await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc_obj.id)
            .order_by(DocumentChunk.chunk_index.asc())
            .limit(4)
        )
        chunks = chunks_res.scalars().all()

        if not chunks:
            logger.warning(f"No chunks found for document {doc_obj.id} during revaluation.")
            return False

        chunk_text = "\n\n".join([f"[Chunk {c.chunk_index}] {c.content[:400]}" for c in chunks])

        # Distill updated context using ModelFactory or heuristic fallback
        updated_content = await self._synthesize_updated_context(
            key=memory.key,
            original_content=memory.content,
            chunk_text=chunk_text,
        )

        now = utc_now()
        memory.content = updated_content
        memory.document_hash = doc_obj.file_hash
        memory.revaluated_at = now
        memory.updated_at = now

        # Refresh expiration if short-term or has TTL
        if memory.memory_type == MemoryType.SHORT_TERM.value:
            # Short-term memories refreshed with standard TTL (e.g., 2 hours)
            memory.expires_at = now + timedelta(hours=2)
        elif memory.revaluation_interval_seconds:
            # Long-term memories refreshed with interval
            memory.expires_at = now + timedelta(seconds=memory.revaluation_interval_seconds * 2)

        await db.commit()
        await db.refresh(memory)
        logger.info(f"Successfully revaluated memory '{memory.key}' with fresh context from {doc_obj.filename}")
        return True

    async def _synthesize_updated_context(self, key: str, original_content: str, chunk_text: str) -> str:
        """Use fast chat model or fallback to distill fresh context."""
        try:
            model = ModelFactory.get_chat_model(temperature=0.0, streaming=False)
            prompt = [
                SystemMessage(content="You are a precise, low-memory context distillation engine."),
                HumanMessage(
                    content=REVALUATION_PROMPT.format(
                        key=key,
                        original_content=original_content,
                        document_context=chunk_text[:1500],
                    )
                ),
            ]
            resp = await model.ainvoke(prompt)
            text = resp.content.strip() if hasattr(resp, "content") else str(resp).strip()
            if text and len(text) > 10:
                return text[:500]  # Strict low-memory limit
        except Exception as e:
            logger.warning(f"LLM synthesis skipped during memory revaluation: {e}. Using chunk excerpt fallback.")

        # Heuristic fallback: clean concise extract from first chunk
        clean_fallback = chunk_text.replace("\n", " ").strip()
        return clean_fallback[:250] + ("..." if len(clean_fallback) > 250 else "")

    async def revaluate_for_document(self, document_id: str, db: AsyncSession) -> int:
        """Trigger revaluation for all memories bound to a specific document."""
        doc_res = await db.execute(select(Document).where(Document.id == document_id))
        doc_obj = doc_res.scalar_one_or_none()
        if not doc_obj:
            return 0

        mem_res = await db.execute(select(MemoryItem).where(MemoryItem.document_id == document_id))
        memories = mem_res.scalars().all()

        revaluated_count = 0
        for mem in memories:
            revaluated = await self.check_and_revaluate(mem, db, doc_obj=doc_obj, force=True)
            if revaluated:
                revaluated_count += 1

        return revaluated_count

    async def scan_and_revaluate_all(self, db: AsyncSession, limit: int = 50) -> Dict[str, Any]:
        """Scan and revaluate any stale or expired memories across the entire system."""
        now = utc_now()
        # Find memories where document_id is not null or expires_at is past
        mem_res = await db.execute(
            select(MemoryItem).order_by(MemoryItem.updated_at.asc()).limit(limit)
        )
        memories = mem_res.scalars().all()

        scanned = len(memories)
        revaluated = 0
        updated_keys = []
        expired_pruned = 0

        for mem in memories:
            if mem.document_id:
                did_reval = await self.check_and_revaluate(mem, db)
                if did_reval:
                    revaluated += 1
                    updated_keys.append(mem.key)
            elif mem.is_expired(now):
                # Expired non-document memory: prune
                await db.delete(mem)
                expired_pruned += 1

        if expired_pruned > 0:
            await db.commit()

        return {
            "scanned_count": scanned,
            "revaluated_count": revaluated,
            "updated_keys": updated_keys,
            "expired_pruned_count": expired_pruned,
        }


revaluation_engine = MemoryRevaluationEngine()
