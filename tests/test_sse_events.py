"""Test suite for Server-Sent Events (SSE) and Real-Time Event Broadcasting."""

import asyncio
import json
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.user import User
from app.services.event_broadcaster import EventBroadcaster, event_broadcaster


@pytest.mark.asyncio
async def test_event_broadcaster_subscribe_and_broadcast():
    """Verify EventBroadcaster delivers status events to subscribers in-memory."""
    broadcaster = EventBroadcaster()
    queue = await broadcaster.subscribe()

    test_event = await broadcaster.broadcast_document_status(
        document_id="doc-test-123",
        status="processing",
        filename="contract.pdf",
        chunk_count=0,
        file_size=2048,
        user_id="user-1",
    )

    assert test_event["document_id"] == "doc-test-123"
    assert test_event["status"] == "processing"

    received = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert received["document_id"] == "doc-test-123"
    assert received["status"] == "processing"
    assert received["filename"] == "contract.pdf"

    await broadcaster.unsubscribe(queue)
    assert len(broadcaster._subscribers) == 0


@pytest.mark.asyncio
async def test_sse_endpoint_receives_connected_and_status_event(test_user, auth_token):
    """Verify GET /api/documents/events/stream connects and streams SSE events."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Start SSE stream
        async with client.stream(
            "GET",
            f"/api/documents/events/stream?token={auth_token}",
        ) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

            # Broadcast an event while client is listening
            asyncio.create_task(
                event_broadcaster.broadcast_document_status(
                    document_id="doc-sse-999",
                    status="completed",
                    filename="sales_q3.pdf",
                    chunk_count=18,
                    user_id=test_user.id,
                )
            )

            lines = []
            async for line in response.aiter_lines():
                if line.strip():
                    lines.append(line.strip())
                if any("doc-sse-999" in l for l in lines):
                    break

            combined = "\n".join(lines)
            assert "event: connected" in combined
            assert "event: document_status" in combined
            assert "sales_q3.pdf" in combined
            assert "completed" in combined
