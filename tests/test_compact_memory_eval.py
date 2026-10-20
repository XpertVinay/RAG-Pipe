"""Tests for compact + meaning synthesis of short-term and long-term memory."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.manager import memory_manager
from app.memory.quick_eval import quick_memory_evaluator
from app.models.memory import MemoryScope, MemoryType


@pytest.mark.asyncio
async def test_compact_memory_evaluator(test_db: AsyncSession):
    """Verify QuickMemoryEvaluator consolidates STM and LTM into high-density semantic synthesis."""
    # 1. Store a Short-Term Memory item
    await memory_manager.store_memory(
        scope=MemoryScope.USER_SPECIFIC.value,
        memory_type=MemoryType.SHORT_TERM.value,
        key="topic_quarterly_reports",
        content="User inquired about Q3 cash flows and runway analysis.",
        user_id="test-auth-user-id",
        room_id="room-eval-123",
        importance=0.8,
        metadata_payload={"meaning_intent": "Active Financial Audit Focus"},
        db=test_db,
    )

    # 2. Store a Long-Term Memory item
    await memory_manager.store_memory(
        scope=MemoryScope.USER_SPECIFIC.value,
        memory_type=MemoryType.LONG_TERM.value,
        key="pref_strict_citations",
        content="Always output markdown tables and bulleted executive summaries.",
        user_id="test-auth-user-id",
        room_id="room-eval-123",
        importance=0.9,
        metadata_payload={"meaning_intent": "Formatting Preference"},
        db=test_db,
    )

    # 3. Evaluate context
    eval_res = await quick_memory_evaluator.evaluate_room_context(
        db=test_db,
        room_id="room-eval-123",
        user_id="test-auth-user-id",
    )

    assert eval_res.total_memories >= 2
    assert eval_res.short_term_count >= 1
    assert eval_res.long_term_count >= 1
    assert "Short-Term Working Focus" in eval_res.compact_synthesis
    assert "Long-Term Preferences & Constraints" in eval_res.compact_synthesis
    assert eval_res.readiness_score > 0.8
    assert eval_res.tokens_saved_percent >= 0.0


@pytest.mark.asyncio
async def test_compact_memory_quick_eval_api(client: AsyncClient):
    """Verify GET /api/memory/quick-eval returns synthesized evaluation."""
    # Create room
    r_res = await client.post("/api/rooms", json={"name": "Eval Room"})
    assert r_res.status_code == 201
    room_id = r_res.json()["id"]

    res = await client.get(f"/api/memory/quick-eval?room_id={room_id}")
    assert res.status_code == 200
    data = res.json()

    assert "compact_synthesis" in data
    assert "short_term_items" in data
    assert "long_term_items" in data
    assert "readiness_score" in data
    assert "tokens_saved_percent" in data
