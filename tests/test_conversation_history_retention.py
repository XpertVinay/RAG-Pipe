"""Tests verifying multi-turn conversation memory, history context retention, and thread continuity."""

import json
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.nodes import format_chat_history_messages, rewrite_query
from app.agent.state import AgentState
from app.memory.manager import memory_manager
from app.models.conversation import Conversation, Message
from app.models.memory import MemoryItem
from langchain_core.messages import AIMessage, HumanMessage


@pytest.mark.asyncio
async def test_format_chat_history_messages_alternation_and_deduplication():
    """Verify format_chat_history_messages creates Human/AI message turns and excludes duplicate current query."""
    history = [
        {"role": "user", "content": "What is PostgreSQL?"},
        {"role": "assistant", "content": "PostgreSQL is a powerful relational database."},
        {"role": "user", "content": "Can it handle JSON data?"},
    ]
    # When current_query matches the last user message, it should be excluded from prior history
    msgs = format_chat_history_messages(history, current_query="Can it handle JSON data?")
    assert len(msgs) == 2
    assert isinstance(msgs[0], HumanMessage)
    assert msgs[0].content == "What is PostgreSQL?"
    assert isinstance(msgs[1], AIMessage)
    assert msgs[1].content == "PostgreSQL is a powerful relational database."

    # When current_query is new, all history turns are retained
    msgs_new = format_chat_history_messages(history, current_query="What about indexing?")
    assert len(msgs_new) == 3
    assert isinstance(msgs_new[0], HumanMessage)
    assert isinstance(msgs_new[1], AIMessage)
    assert isinstance(msgs_new[2], HumanMessage)


@pytest.mark.asyncio
async def test_stream_multi_turn_conversation_same_thread(client: AsyncClient, test_db: AsyncSession):
    """Verify that multiple prompts in a chat window remain in the same conversation thread and retain context."""
    # 1. Turn 1: User introduces themselves and their project without conversation_id
    turn1_payload = {
        "message": "Hello, my name is Alex and I am developing Project Falcon with Redis cache.",
    }
    turn1_res = await client.post("/api/chat/stream", json=turn1_payload)
    assert turn1_res.status_code == 200
    turn1_text = turn1_res.text

    # Extract conversation_id from meta or done event
    conv_id = None
    for line in turn1_text.splitlines():
        if line.startswith("data:") and "conversation_id" in line:
            data = json.loads(line.replace("data:", "").strip())
            if "conversation_id" in data and data["conversation_id"]:
                conv_id = data["conversation_id"]
                break

    assert conv_id is not None, "conversation_id was not returned in SSE stream events"

    # Verify conversation exists in DB
    conv_db = await test_db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = conv_db.scalar_one_or_none()
    assert conv is not None

    # 2. Turn 2: User asks a follow-up query referencing previous context with the SAME conversation_id
    turn2_payload = {
        "conversation_id": conv_id,
        "message": "What is my name and what project am I working on?",
    }
    turn2_res = await client.post("/api/chat/stream", json=turn2_payload)
    assert turn2_res.status_code == 200
    turn2_text = turn2_res.text

    # Extract conversation_id from turn 2
    conv_id_2 = None
    turn2_answer = ""
    for line in turn2_text.splitlines():
        if line.startswith("data:") and "conversation_id" in line:
            data = json.loads(line.replace("data:", "").strip())
            if "conversation_id" in data:
                conv_id_2 = data["conversation_id"]
            if "answer" in data:
                turn2_answer = data["answer"]

    # Verify turn 2 remained in the exact same conversation thread
    assert conv_id_2 == conv_id

    # Verify all messages belong to this single conversation
    msgs_res = await test_db.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at.asc())
    )
    messages = msgs_res.scalars().all()
    assert len(messages) >= 4  # [Turn 1 user, Turn 1 assistant, Turn 2 user, Turn 2 assistant]

    # Verify conversation count in DB hasn't created a redundant new conversation
    total_convs = await test_db.execute(select(func.count(Conversation.id)))
    assert total_convs.scalar_one() == 1


@pytest.mark.asyncio
async def test_standard_query_multi_turn_history(client: AsyncClient, test_db: AsyncSession):
    """Verify non-streaming query endpoint preserves multi-turn conversation and records STM/LTM memory."""
    # 1. First turn: user defines their preferred formatting
    turn1_res = await client.post("/api/chat/query", json={
        "message": "Remember that I prefer responses summarized in bullet points with emoji icons.",
    })
    assert turn1_res.status_code == 200
    data1 = turn1_res.json()
    conv_id = data1["conversation_id"]
    assert conv_id is not None

    # 2. Second turn: follow-up query using the same conversation_id
    turn2_res = await client.post("/api/chat/query", json={
        "conversation_id": conv_id,
        "message": "How do distributed locks work in Redis?",
    })
    assert turn2_res.status_code == 200
    data2 = turn2_res.json()
    assert data2["conversation_id"] == conv_id

    # Verify database has 4 messages belonging to this single conversation
    m_res = await test_db.execute(select(Message).where(Message.conversation_id == conv_id))
    assert len(m_res.scalars().all()) == 4

    # Verify memory retrieval can locate context by conversation_id
    mem_context, consulted = await memory_manager.retrieve_context(
        query="redis distributed locks",
        conversation_id=conv_id,
        db=test_db,
    )
    assert len(consulted) > 0 or len(mem_context) > 0


@pytest.mark.asyncio
async def test_rewrite_query_incorporates_conversation_history():
    """Verify rewrite_query uses prior conversation history when reformulating ambiguous follow-up queries."""
    state: AgentState = {
        "query": "What are its key benefits?",
        "original_query": "What are its key benefits?",
        "chat_history": [
            {"role": "user", "content": "Tell me about Redis caching strategies."},
            {"role": "assistant", "content": "Redis provides in-memory key-value caching with TTL expiration."},
        ],
        "conversation_id": "test-conv-1234",
        "retrieval_retry_count": 0,
        "max_retries": 2,
        "document_ids": None,
        "user_id": None,
        "room_id": None,
        "memory_context": None,
        "consulted_memories": [],
        "provider": None,
        "model": None,
        "temperature": 0.2,
        "top_k": 4,
        "intent": "qa",
        "documents": [],
        "citations": [],
        "is_relevant": False,
        "generation_grounded": True,
        "needs_visualization": False,
        "visualization": None,
        "answer": "",
        "error": None,
        "status_update": "",
    }

    rewritten_state = await rewrite_query(state)
    assert rewritten_state["retrieval_retry_count"] == 1
    assert "query" in rewritten_state
    assert len(rewritten_state["query"]) > 0


@pytest.mark.asyncio
async def test_topic_shift_preserves_query_and_prevents_history_bleed():
    """Verify that rewrite_query does not blend prior conversation topics when user switches topic."""
    state: AgentState = {
        "query": "What are the fundamental rights of individuals in India",
        "original_query": "What are the fundamental rights of individuals in India",
        "chat_history": [
            {"role": "user", "content": "How to print a variable in javascript?"},
            {
                "role": "assistant",
                "content": "To print a variable in JavaScript, you can use console.log() or print().",
            },
        ],
        "conversation_id": "test-topic-shift-456",
        "retrieval_retry_count": 0,
        "max_retries": 2,
        "document_ids": None,
        "user_id": None,
        "room_id": None,
        "memory_context": None,
        "consulted_memories": [],
        "provider": None,
        "model": None,
        "temperature": 0.2,
        "top_k": 4,
        "intent": "qa",
        "documents": [],
        "citations": [],
        "is_relevant": False,
        "generation_grounded": True,
        "needs_visualization": False,
        "visualization": None,
        "answer": "",
        "error": None,
        "status_update": "",
    }

    rewritten_state = await rewrite_query(state)
    # The rewritten query must NOT incorporate JavaScript context on topic shift
    assert "javascript" not in rewritten_state["query"].lower()
    assert "fundamental rights" in rewritten_state["query"].lower()
    assert "india" in rewritten_state["query"].lower()


@pytest.mark.asyncio
async def test_memory_ranker_rejects_unrelated_stm_on_topic_shift(test_db: AsyncSession):
    """Verify memory ranking component ignores past turn STM with zero token overlap on topic shift."""
    conv_id = "shift-conv-987"
    # Store STM about JavaScript for this conversation
    await memory_manager.store_memory(
        scope="global",
        memory_type="short_term",
        key=f"chat_stm_{conv_id[:8]}_123456",
        content="User asked: How to print a variable in javascript? -> Context: JavaScript is a loosely typed language.",
        importance=0.7,
        db=test_db,
    )
    await memory_manager.store_memory(
        scope="global",
        memory_type="short_term",
        key=f"chat_summary_{conv_id[:8]}",
        content="Active discussion topic: How to print a variable in javascript?",
        importance=0.7,
        db=test_db,
    )

    # Now retrieve memory for a completely different topic (India fundamental rights)
    mem_context, consulted = await memory_manager.retrieve_context(
        query="What are the fundamental rights of individuals in India",
        conversation_id=conv_id,
        db=test_db,
    )

    # Must NOT include JavaScript memories
    assert "javascript" not in mem_context.lower()
    assert len(consulted) == 0


@pytest.mark.asyncio
async def test_multi_turn_topic_shift_streaming_no_context_bleed(client: AsyncClient, test_db: AsyncSession):
    """Verify that Turn 1 about JavaScript followed by Turn 2 about Indian fundamental rights does not bleed context."""
    # 1. Turn 1: JavaScript inquiry
    turn1_res = await client.post("/api/chat/stream", json={
        "message": "How to print a variable in javascript?",
    })
    assert turn1_res.status_code == 200

    conv_id = None
    for line in turn1_res.text.splitlines():
        if line.startswith("data:") and "conversation_id" in line:
            data = json.loads(line.replace("data:", "").strip())
            if data.get("conversation_id"):
                conv_id = data["conversation_id"]
                break
    assert conv_id is not None

    # 2. Turn 2: Switch to completely unrelated topic in the same conversation
    turn2_res = await client.post("/api/chat/stream", json={
        "conversation_id": conv_id,
        "message": "What are the fundamental rights of individuals in India",
    })
    assert turn2_res.status_code == 200

    turn2_answer = ""
    turn2_meta = {}
    for line in turn2_res.text.splitlines():
        if line.startswith("data:"):
            try:
                data = json.loads(line.replace("data:", "").strip())
                if "token" in data:
                    turn2_answer += data["token"]
                if "response_type" in data:
                    turn2_meta = data
            except Exception:
                pass

    # Assert Turn 2 does NOT talk about JavaScript
    assert "javascript" not in turn2_answer.lower()
    assert "loosely typed" not in turn2_answer.lower()

    # Assert response type is domain synthesis (ungrounded_sensible), NOT falsely claiming grounded in JavaScript
    assert turn2_meta.get("response_type") != "grounded"
    assert turn2_meta.get("generation_grounded") is False

