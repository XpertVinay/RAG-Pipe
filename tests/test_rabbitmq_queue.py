"""Comprehensive test suite for RabbitMQ queue document processing, worker consumer, and LLM prompt readiness."""

import io
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.document import Document
from app.models.room import Room, RoomDocument
from app.services.queue_service import QueueService, queue_service
from app.services.document_worker import process_incoming_job


async def _get_auth_header(client: AsyncClient, username: str = "rabbit_user", email: str = "rabbit@test.local") -> dict:
    """Helper to authenticate user and return authorization header."""
    res = await client.post("/api/auth/register", json={
        "username": username,
        "email": email,
        "password": "Password123!",
    })
    if res.status_code == 201:
        token = res.json()["access_token"]
    else:
        login_res = await client.post("/api/auth/token", data={
            "username": username,
            "password": "Password123!",
        })
        token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_queue_service_fallback_when_rabbitmq_unreachable():
    """Verify that when RabbitMQ is unreachable, queue_service gracefully falls back to in-process execution."""
    test_svc = QueueService()
    # Force get_channel to return None simulating disconnected broker
    with patch.object(test_svc, "get_channel", AsyncMock(return_value=None)):
        mock_bg = MagicMock()
        result = await test_svc.enqueue_document_job("doc-123", background_tasks=mock_bg)

        assert result["status"] == "queued"
        assert result["mechanism"] == "background_task"
        assert result["document_id"] == "doc-123"
        mock_bg.add_task.assert_called_once()


@pytest.mark.asyncio
async def test_queue_service_publishes_to_rabbitmq_channel():
    """Verify that when RabbitMQ channel is available, persistent messages are published."""
    test_svc = QueueService()
    mock_channel = MagicMock()
    mock_channel.is_closed = False
    mock_channel.default_exchange = MagicMock()
    mock_channel.default_exchange.publish = AsyncMock()

    with patch.object(test_svc, "get_channel", AsyncMock(return_value=mock_channel)):
        result = await test_svc.enqueue_document_job("doc-456", retry_count=0)

        assert result["status"] == "queued"
        assert result["mechanism"] == "rabbitmq"
        assert result["document_id"] == "doc-456"
        mock_channel.default_exchange.publish.assert_called_once()
        call_args = mock_channel.default_exchange.publish.call_args
        published_msg = call_args[0][0]
        payload = json.loads(published_msg.body.decode("utf-8"))
        assert payload["document_id"] == "doc-456"
        assert payload["action"] == "process_document"


@pytest.mark.asyncio
async def test_queue_service_health_check_reporting():
    """Verify queue_service check_health reporting."""
    test_svc = QueueService()
    # When disconnected
    with patch.object(test_svc, "get_connection", AsyncMock(return_value=None)):
        health = await test_svc.check_health()
        assert health["status"] == "degraded"
        assert health["connected"] is False
        assert health["fallback_active"] is True

    # When connected
    mock_conn = MagicMock()
    mock_conn.is_closed = False
    mock_channel = MagicMock()
    mock_channel.is_closed = False
    mock_q = MagicMock()
    mock_q.declaration_result.message_count = 5
    mock_q.declaration_result.consumer_count = 2
    mock_channel.declare_queue = AsyncMock(return_value=mock_q)

    with patch.object(test_svc, "get_connection", AsyncMock(return_value=mock_conn)), \
         patch.object(test_svc, "get_channel", AsyncMock(return_value=mock_channel)):
        test_svc._channel = mock_channel
        health = await test_svc.check_health()
        assert health["status"] == "healthy"
        assert health["connected"] is True
        assert health["message_count"] == 5
        assert health["consumer_count"] == 2


@pytest.mark.asyncio
async def test_worker_process_incoming_job_success():
    """Verify that worker consumes job, calls ingestion_pipeline, and acknowledges message."""
    mock_msg = MagicMock()
    mock_msg.body = json.dumps({"document_id": "test-doc-id", "retry_count": 0}).encode("utf-8")

    # Mock async context manager for message.process
    process_cm = AsyncMock()
    process_cm.__aenter__ = AsyncMock(return_value=None)
    process_cm.__aexit__ = AsyncMock(return_value=None)
    mock_msg.process = MagicMock(return_value=process_cm)

    with patch("app.ingestion.pipeline.ingestion_pipeline.process_document", AsyncMock()) as mock_ingest:
        await process_incoming_job(mock_msg)
        mock_ingest.assert_called_once_with("test-doc-id")
        mock_msg.process.assert_called_once()


@pytest.mark.asyncio
async def test_worker_process_incoming_job_retry_on_failure():
    """Verify worker retry mechanism when ingestion fails."""
    mock_msg = MagicMock()
    mock_msg.body = json.dumps({"document_id": "failing-doc", "retry_count": 0}).encode("utf-8")

    process_cm = AsyncMock()
    process_cm.__aenter__ = AsyncMock(return_value=None)
    process_cm.__aexit__ = AsyncMock(return_value=None)
    mock_msg.process = MagicMock(return_value=process_cm)

    with patch("app.ingestion.pipeline.ingestion_pipeline.process_document", AsyncMock(side_effect=RuntimeError("Transient error"))), \
         patch("app.services.queue_service.queue_service.enqueue_document_job", AsyncMock()) as mock_re_enqueue, \
         patch("asyncio.sleep", AsyncMock()):
        await process_incoming_job(mock_msg)
        mock_re_enqueue.assert_called_once_with(document_id="failing-doc", retry_count=1)


@pytest.mark.asyncio
async def test_api_queue_status_endpoint(client: AsyncClient):
    """Verify GET /api/documents/queue/status returns broker metrics."""
    res = await client.get("/api/documents/queue/status")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "connected" in data


@pytest.mark.asyncio
async def test_api_health_includes_queue(client: AsyncClient):
    """Verify GET /api/health includes the queue component."""
    res = await client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert "queue" in data["components"]
    assert "status" in data["components"]["queue"]


@pytest.mark.asyncio
async def test_api_document_upload_queues_job(client: AsyncClient):
    """Verify POST /api/documents/upload schedules job via queue_service."""
    headers = await _get_auth_header(client, "uploader_q", "uq@test.local")
    files = {"files": ("queue_test.txt", io.BytesIO(b"Scale up rabbitmq test content"), "text/plain")}

    with patch("app.services.queue_service.queue_service.enqueue_document_job", AsyncMock(return_value={"status": "queued", "mechanism": "rabbitmq"})) as mock_enqueue:
        res = await client.post("/api/documents/upload", files=files, headers=headers)
        assert res.status_code == 202
        assert mock_enqueue.called
        data = res.json()
        assert len(data["uploaded"]) == 1
        assert data["uploaded"][0]["status"] == "queued"


@pytest.mark.asyncio
async def test_api_document_readiness_check(client: AsyncClient, test_db: AsyncSession):
    """Verify GET /api/documents/readiness/check returns document readiness details."""
    headers = await _get_auth_header(client, "readiness_user", "ready@test.local")

    # Create a queued document and a completed document
    doc1 = Document(
        id=str(uuid.uuid4()),
        filename="pending_file.pdf",
        file_type="pdf",
        file_size=1024,
        storage_path="/tmp/pending.pdf",
        status="queued",
        is_shared=True,
    )
    doc2 = Document(
        id=str(uuid.uuid4()),
        filename="ready_file.txt",
        file_type="txt",
        file_size=512,
        storage_path="/tmp/ready.txt",
        status="completed",
        chunk_count=3,
        is_shared=True,
    )
    test_db.add_all([doc1, doc2])
    await test_db.commit()

    doc1_id, doc2_id = doc1.id, doc2.id

    # Check readiness when doc1 is pending
    res = await client.get(f"/api/documents/readiness/check?document_ids={doc1_id}", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["all_ready"] is False
    assert data["pending_count"] == 1
    assert data["ready_count"] == 0
    assert "pending_file.pdf" in data["documents"][0]["filename"]

    # Check readiness when doc2 is completed
    res2 = await client.get(f"/api/documents/readiness/check?document_ids={doc2_id}", headers=headers)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["all_ready"] is True
    assert data2["pending_count"] == 0
    assert data2["ready_count"] == 1


@pytest.mark.asyncio
async def test_chat_query_informs_user_when_documents_in_queue(client: AsyncClient, test_db: AsyncSession):
    """Verify that querying a workspace with only queued/processing documents informs the user to wait until ready."""
    headers = await _get_auth_header(client, "chat_queue_user", "cqu@test.local")

    # Create room and attach a document in 'queued' status
    room = Room(
        id=str(uuid.uuid4()),
        name="Queue Test Workspace",
        description="Testing RabbitMQ queue readiness",
        is_public=True,
    )
    doc = Document(
        id=str(uuid.uuid4()),
        filename="financial_audit_2026.pdf",
        file_type="pdf",
        file_size=2048,
        storage_path="/tmp/financial_audit.pdf",
        status="queued",
        is_shared=True,
    )
    test_db.add_all([room, doc])
    await test_db.flush()

    room_doc = RoomDocument(room_id=room.id, document_id=doc.id)
    test_db.add(room_doc)
    await test_db.commit()
    room_id = room.id

    # Ask query while document is still queued
    chat_res = await client.post(
        "/api/chat/query",
        json={"message": "What were the total Q3 revenues?", "room_id": room_id},
        headers=headers,
    )
    assert chat_res.status_code == 200
    chat_data = chat_res.json()

    assert "financial_audit_2026.pdf" in chat_data["content"]
    assert "RabbitMQ" in chat_data["content"]
    assert "queue" in chat_data["content"].lower()
    assert chat_data["metadata_info"]["response_type"] == "queue_pending"
    assert chat_data["metadata_info"]["queue_pending"] is True
