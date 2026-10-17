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


@pytest.mark.asyncio
async def test_query_endpoint_with_gemini_provider(client: AsyncClient):
    """Verify chat query works with provider='gemini' and model='gemini-2.5-flash'."""
    payload = {
        "message": "Summarize the project document.",
        "provider": "gemini",
        "model": "gemini-2.5-flash",
    }
    res = await client.post("/api/chat/query", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "content" in data
    assert data["role"] == "assistant"


@pytest.mark.asyncio
async def test_response_differentiator_metadata(client: AsyncClient):
    """Verify response_type differentiator is returned in metadata_info."""
    # Greeting query -> greeting differentiator
    greeting_res = await client.post("/api/chat/query", json={"message": "hello!"})
    assert greeting_res.status_code == 200
    greeting_data = greeting_res.json()
    assert "metadata_info" in greeting_data
    assert greeting_data["metadata_info"].get("response_type") == "greeting"

    # Streaming query -> meta event and done payload include response_type
    stream_res = await client.post("/api/chat/stream", json={"message": "hey there"})
    assert stream_res.status_code == 200
    body = stream_res.text
    assert "event: meta" in body
    assert '"response_type": "greeting"' in body

    # Complex specific question on empty doc scope -> insufficient_info differentiator
    qa_res = await client.post("/api/chat/query", json={"message": "What is the secret deployment protocol code?", "document_ids": ["non-existent-doc"]})
    assert qa_res.status_code == 200
    qa_data = qa_res.json()
    assert qa_data["metadata_info"].get("response_type") == "insufficient_info"
