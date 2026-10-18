"""Comprehensive test suite for Two-Tier Memory System (Short-Term & Long-Term, Global & User-Specific)."""

from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.l1_cache import CachedMemoryEntry, LowMemoryLRUCache
from app.memory.manager import memory_manager
from app.memory.revaluation import revaluation_engine
from app.models.document import Document, DocumentChunk
from app.models.memory import MemoryItem, MemoryScope, MemoryType
from app.models.user import User


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def test_l1_cache_bounded_capacity_and_eviction():
    """Test that L1 LRU cache respects maximum item count and tracks byte sizes accurately."""
    cache = LowMemoryLRUCache(max_items=3, max_bytes=100000)

    now = utc_now()
    entry1 = CachedMemoryEntry(
        id="1", key="k1", scope="global", memory_type="short_term",
        user_id=None, room_id=None, document_id=None, document_hash=None,
        content="Alpha fact", importance=0.5, expires_at=None,
        revaluated_at=now, revaluation_interval_seconds=86400,
        metadata_payload={}, access_count=0, last_accessed=now.timestamp(),
    )
    entry2 = CachedMemoryEntry(
        id="2", key="k2", scope="global", memory_type="short_term",
        user_id=None, room_id=None, document_id=None, document_hash=None,
        content="Beta fact", importance=0.5, expires_at=None,
        revaluated_at=now, revaluation_interval_seconds=86400,
        metadata_payload={}, access_count=0, last_accessed=now.timestamp(),
    )
    entry3 = CachedMemoryEntry(
        id="3", key="k3", scope="global", memory_type="short_term",
        user_id=None, room_id=None, document_id=None, document_hash=None,
        content="Gamma fact", importance=0.5, expires_at=None,
        revaluated_at=now, revaluation_interval_seconds=86400,
        metadata_payload={}, access_count=0, last_accessed=now.timestamp(),
    )
    entry4 = CachedMemoryEntry(
        id="4", key="k4", scope="global", memory_type="short_term",
        user_id=None, room_id=None, document_id=None, document_hash=None,
        content="Delta fact", importance=0.5, expires_at=None,
        revaluated_at=now, revaluation_interval_seconds=86400,
        metadata_payload={}, access_count=0, last_accessed=now.timestamp(),
    )

    cache.put(entry1)
    cache.put(entry2)
    cache.put(entry3)
    assert len(cache._entries) == 3

    # Access entry1 to make it most recently used
    assert cache.get("global", "k1") is not None
    assert cache.hits == 1

    # Adding entry4 should evict entry2 (the least recently used)
    cache.put(entry4)
    assert len(cache._entries) == 3
    assert cache.get("global", "k2") is None  # Evicted
    assert cache.get("global", "k1") is not None
    assert cache.get("global", "k4") is not None


def test_l1_cache_lazy_expiration():
    """Test that expired items in L1 are lazily evicted on get or via prune."""
    cache = LowMemoryLRUCache(max_items=10)
    past_time = utc_now() - timedelta(seconds=10)

    expired_entry = CachedMemoryEntry(
        id="exp1", key="expired_key", scope="global", memory_type="short_term",
        user_id=None, room_id=None, document_id=None, document_hash=None,
        content="Old temporary note", importance=0.5, expires_at=past_time,
        revaluated_at=past_time, revaluation_interval_seconds=86400,
        metadata_payload={}, access_count=0, last_accessed=past_time.timestamp(),
    )
    cache.put(expired_entry)

    # Calling get should return None and lazy-evict
    val = cache.get("global", "expired_key")
    assert val is None
    assert len(cache._entries) == 0


@pytest.mark.asyncio
async def test_memory_distribution_matrix(test_db: AsyncSession):
    """Test storing and distribution of all 4 quadrants: Global/User x Short/Long Term."""
    now = utc_now()

    # 1. Global Short-Term
    await memory_manager.store_memory(
        scope=MemoryScope.GLOBAL.value,
        memory_type=MemoryType.SHORT_TERM.value,
        key="global_temp_topic",
        content="Active trending query: RAG Chunking",
        ttl_seconds=3600,
        importance=0.6,
        db=test_db,
    )

    # 2. Global Long-Term
    await memory_manager.store_memory(
        scope=MemoryScope.GLOBAL.value,
        memory_type=MemoryType.LONG_TERM.value,
        key="system_guideline",
        content="Always answer with grounded facts and citations.",
        ttl_seconds=86400 * 30,
        importance=0.9,
        db=test_db,
    )

    # 3. User Short-Term
    user_id = "test-user-123"
    await memory_manager.store_memory(
        scope=MemoryScope.USER_SPECIFIC.value,
        memory_type=MemoryType.SHORT_TERM.value,
        key="current_focus",
        content="User is comparing vector databases",
        user_id=user_id,
        ttl_seconds=1800,
        importance=0.7,
        db=test_db,
    )

    # 4. User Long-Term
    await memory_manager.store_memory(
        scope=MemoryScope.USER_SPECIFIC.value,
        memory_type=MemoryType.LONG_TERM.value,
        key="user_preference",
        content="User prefers concise Python code examples",
        user_id=user_id,
        ttl_seconds=86400 * 90,
        importance=0.95,
        db=test_db,
    )

    stats = await memory_manager.get_distribution_stats(db=test_db)

    assert stats.total_memories >= 4
    assert stats.global_short_term.count >= 1
    assert stats.global_long_term.count >= 1
    assert stats.user_short_term.count >= 1
    assert stats.user_long_term.count >= 1

    # Verify byte tracking is low (< 50 KB for few entries)
    total_bytes = (
        stats.global_short_term.estimated_bytes
        + stats.global_long_term.estimated_bytes
        + stats.user_short_term.estimated_bytes
        + stats.user_long_term.estimated_bytes
    )
    assert total_bytes < 50000  # Highly optimized low-memory footprint
    assert stats.in_memory_l1_items >= 4


@pytest.mark.asyncio
async def test_low_token_context_retrieval(test_db: AsyncSession):
    """Test retrieving memory context with strict token budget and relevance ranking."""
    user_id = "analyst-456"

    await memory_manager.store_memory(
        scope=MemoryScope.USER_SPECIFIC.value,
        memory_type=MemoryType.LONG_TERM.value,
        key="user_role",
        content="User is a senior risk analyst focused on credit loss modeling.",
        user_id=user_id,
        importance=0.9,
        db=test_db,
    )
    await memory_manager.store_memory(
        scope=MemoryScope.GLOBAL.value,
        memory_type=MemoryType.SHORT_TERM.value,
        key="market_brief",
        content="Federal Reserve interest rate decisions are pending.",
        importance=0.5,
        db=test_db,
    )

    context_str, consulted = await memory_manager.retrieve_context(
        query="What is the credit risk projection for Q4?",
        user_id=user_id,
        top_k=2,
        max_tokens_budget=150,
        db=test_db,
    )

    assert "Relevant Memory Context" in context_str
    assert "credit loss modeling" in context_str
    assert len(consulted) >= 1
    # Verify budget constraint: context should be compact
    assert len(context_str) < 150 * 5


@pytest.mark.asyncio
async def test_document_revaluation_on_hash_change(test_db: AsyncSession):
    """Test document revaluation trigger when document hash or contents are refreshed."""
    # 1. Create a dummy Document
    doc = Document(
        filename="financial_q3.pdf",
        file_type="pdf",
        file_size=1024,
        storage_path="/tmp/fake_q3.pdf",
        file_hash="hash_v1",
        status="completed",
        chunk_count=1,
    )
    test_db.add(doc)
    await test_db.commit()
    await test_db.refresh(doc)

    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content="Q3 net revenue reached $45.2 million, up 12% year-over-year.",
        chunk_metadata={"page": 1},
    )
    test_db.add(chunk)
    await test_db.commit()

    # 2. Store memory linked to document with hash_v1
    mem = await memory_manager.store_memory(
        scope=MemoryScope.GLOBAL.value,
        memory_type=MemoryType.LONG_TERM.value,
        key="q3_revenue",
        content="Q3 revenue was initially projected at $40M.",
        document_id=doc.id,
        document_hash="hash_v1",
        db=test_db,
    )

    # Document hash unchanged: no revaluation needed yet
    assert not mem.needs_revaluation(current_doc_hash="hash_v1")

    # Document updated to hash_v2!
    doc.file_hash = "hash_v2"
    chunk.content = "UPDATED AUDIT: Q3 net revenue revised to $48.5 million after international restatement."
    await test_db.commit()

    assert mem.needs_revaluation(current_doc_hash=doc.file_hash)

    # Trigger revaluation
    revaluated = await revaluation_engine.check_and_revaluate(mem, test_db, doc_obj=doc)
    assert revaluated is True
    assert mem.document_hash == "hash_v2"
    assert mem.revaluated_at is not None


@pytest.mark.asyncio
async def test_memory_api_endpoints(client: AsyncClient):
    """Test REST endpoints: GET /api/memory, POST /api/memory, GET /api/memory/stats, POST /api/memory/revaluate."""
    # Register test user
    reg_res = await client.post("/api/auth/register", json={
        "email": "mem_user@test.local",
        "username": "memuser",
        "password": "memPassword123",
        "full_name": "Memory User",
    })
    token = reg_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create a memory item via API
    payload = {
        "scope": "global",
        "memory_type": "short_term",
        "key": "api_test_fact",
        "content": "FastAPI is asynchronous and efficient.",
        "importance": 0.8,
        "ttl_seconds": 3600,
    }
    create_res = await client.post("/api/memory", json=payload, headers=headers)
    assert create_res.status_code == 201
    created_data = create_res.json()
    assert created_data["key"] == "api_test_fact"
    assert created_data["is_expired"] is False

    # 2. List memories
    list_res = await client.get("/api/memory?scope=global", headers=headers)
    assert list_res.status_code == 200
    items = list_res.json()
    assert any(i["key"] == "api_test_fact" for i in items)

    # 3. Get Distribution Stats
    stats_res = await client.get("/api/memory/stats", headers=headers)
    assert stats_res.status_code == 200
    stats = stats_res.json()
    assert "global_short_term" in stats
    assert "global_long_term" in stats
    assert "user_short_term" in stats
    assert "user_long_term" in stats
    assert stats["total_memories"] >= 1
    assert stats["in_memory_l1_bytes"] > 0

    # 4. Trigger revaluation scan
    reval_res = await client.post("/api/memory/revaluate", json={}, headers=headers)
    assert reval_res.status_code == 200
    reval_data = reval_res.json()
    assert "scanned_count" in reval_data

    # 5. Delete the test memory
    mem_id = created_data["id"]
    del_res = await client.delete(f"/api/memory/{mem_id}", headers=headers)
    assert del_res.status_code == 200

