"""API tests for conversation management and SSE streaming."""

import json
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_conversation_lifecycle(client: AsyncClient):
    """Verify creating, retrieving, and deleting conversations."""
    # 1. Create conversation
    create_res = await client.post("/api/chat/conversations?title=Project+Alpha")
    assert create_res.status_code == 201
    conv = create_res.json()
    conv_id = conv["id"]
    assert conv["title"] == "Project Alpha"

    # 2. List conversations
    list_res = await client.get("/api/chat/conversations")
    assert list_res.status_code == 200
    assert any(c["id"] == conv_id for c in list_res.json())

    # 3. Retrieve conversation
    get_res = await client.get(f"/api/chat/conversations/{conv_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == conv_id

    # 4. Delete conversation
    del_res = await client.delete(f"/api/chat/conversations/{conv_id}")
    assert del_res.status_code == 200

    # 5. Verify deleted
    get_del = await client.get(f"/api/chat/conversations/{conv_id}")
    assert get_del.status_code == 404


@pytest.mark.asyncio
async def test_standard_query_endpoint(client: AsyncClient):
    """Verify non-streaming JSON query endpoint."""
    payload = {
        "message": "What is the status of the deployment?",
    }
    res = await client.post("/api/chat/query", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "content" in data
    assert data["role"] == "assistant"
    assert "conversation_id" in data


@pytest.mark.asyncio
async def test_stream_query_sse(client: AsyncClient):
    """Verify Server-Sent Events streaming query endpoint."""
    payload = {
        "message": "Hello assistant!",
    }
    res = await client.post("/api/chat/stream", json=payload)
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]

    body = res.text
    assert "event: status" in body
    assert "event: token" in body
    assert "event: done" in body
