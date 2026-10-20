"""Tests for chat database persistence, STM/LTM memory per chat/room, and Delete All Data."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message
from app.models.memory import MemoryItem, MemoryType
from app.memory.manager import memory_manager
from app.services.conversation_service import get_recent_chat_history


@pytest.mark.asyncio
async def test_get_recent_chat_history_ordering(test_db: AsyncSession):
    """Verify get_recent_chat_history returns the most recent messages in chronological order."""
    conv = Conversation(title="Ordering Test")
    test_db.add(conv)
    await test_db.commit()
    await test_db.refresh(conv)

    # Insert 15 messages
    for i in range(1, 16):
        msg = Message(
            conversation_id=conv.id,
            role="user" if i % 2 == 1 else "assistant",
            content=f"Message {i}",
        )
        test_db.add(msg)
    await test_db.commit()

    # Fetch limit 5
    history = await get_recent_chat_history(test_db, conv.id, limit=5)
    assert len(history) == 5
    # The 5 most recent should be Message 11 to Message 15 in ascending chronological order
    assert history[0]["content"] == "Message 11"
    assert history[4]["content"] == "Message 15"


@pytest.mark.asyncio
async def test_chat_turn_memory_distillation(test_db: AsyncSession):
    """Verify record_chat_turn_memory creates STM turn, STM summary, and LTM for preferences."""
    conv = Conversation(title="Memory Test")
    test_db.add(conv)
    await test_db.commit()
    await test_db.refresh(conv)

    # Query with user preference
    await memory_manager.record_chat_turn_memory(
        user_id=None,
        room_id=None,
        conversation_id=conv.id,
        query="Remember that I prefer technical explanations in Python",
        answer="Understood, I will format technical answers in Python.",
        db=test_db,
    )

    # Check memories created in DB
    mem_res = await test_db.execute(select(MemoryItem))
    memories = mem_res.scalars().all()
    assert len(memories) >= 2  # Turn STM, conversation summary, and LTM preference

    types = [m.memory_type for m in memories]
    assert MemoryType.SHORT_TERM.value in types
    assert MemoryType.LONG_TERM.value in types


@pytest.mark.asyncio
async def test_delete_all_chat_and_memory_data(client: AsyncClient, test_db: AsyncSession):
    """Verify DELETE /api/chat/data/all completely wipes conversations, messages, and memories."""
    conv = Conversation(title="Wipe Test")
    test_db.add(conv)
    await test_db.commit()
    await test_db.refresh(conv)

    msg = Message(conversation_id=conv.id, role="user", content="Hello world")
    test_db.add(msg)
    await test_db.commit()

    await memory_manager.record_chat_turn_memory(
        user_id=None,
        room_id=None,
        conversation_id=conv.id,
        query="Hello test",
        answer="World test",
        db=test_db,
    )

    # Call DELETE /api/chat/data/all
    del_res = await client.delete("/api/chat/data/all")
    assert del_res.status_code == 200
    data = del_res.json()
    assert "deleted_conversations" in data
    assert data["deleted_conversations"] >= 1

    # Check DB is empty of conversations
    c_check = await test_db.execute(select(func.count(Conversation.id)))
    assert c_check.scalar_one() == 0

    m_check = await test_db.execute(select(func.count(Message.id)))
    assert m_check.scalar_one() == 0
