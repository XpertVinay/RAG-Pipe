"""Test suite for Server-Sent Events (SSE) and Real-Time Event Broadcasting."""

import asyncio
import json
import pytest
from unittest.mock import MagicMock

from app.api.documents import stream_document_events
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
async def test_stream_document_events_endpoint():
    """Verify stream_document_events returns SSE streaming response and pushes real-time events."""
    mock_request = MagicMock()
    mock_user = User(
        id="test-sse-user-id",
        email="test_sse@example.com",
        username="sse_user",
        hashed_password="mock",
        is_active=True,
    )

    response = await stream_document_events(mock_request, current_user=mock_user)
    assert response.status_code == 200
    assert response.media_type == "text/event-stream"
    assert response.headers.get("Cache-Control") == "no-cache, no-transform"

    gen = response.body_iterator

    # 1. First event must be handshake connected event
    connected_event = await anext(gen)
    assert "event: connected" in connected_event
    assert "test-sse-user-id" in connected_event

    # 2. Broadcast a status change
    await event_broadcaster.broadcast_document_status(
        document_id="doc-sse-888",
        status="completed",
        filename="financial_summary.pdf",
        chunk_count=24,
        user_id=mock_user.id,
    )

    # 3. Next yielded event must be document_status event with chunk details
    status_event = await anext(gen)
    assert "event: document_status" in status_event
    assert "doc-sse-888" in status_event
    assert "financial_summary.pdf" in status_event
    assert "completed" in status_event
    assert "24" in status_event

    # Clean up generator
    await gen.aclose()
