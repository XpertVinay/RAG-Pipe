"""Tests for document upload deduplication, vector reuse, and worker orphan recovery."""

import io
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.models.room import Room, RoomDocument
from app.services.document_worker import recover_orphaned_processing_jobs


async def _get_auth_header(client: AsyncClient, username: str, email: str) -> dict:
    """Helper to register/login a user and return the Authorization header."""
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
async def test_duplicate_upload_while_processing_does_not_enqueue_duplicate(client: AsyncClient, test_db: AsyncSession):
    """Uploading the exact same file while it is currently queued/processing should return the existing doc and not enqueue duplicate jobs."""
    auth_headers = await _get_auth_header(client, "dedupe_user_1", "dedupe1@test.local")
    file_bytes = b"Sample unique content for testing upload deduplication while processing."
    files = {"files": ("report_v1.txt", io.BytesIO(file_bytes), "text/plain")}

    with patch("app.services.queue_service.queue_service.enqueue_document_job", new_callable=AsyncMock) as mock_enqueue:
        mock_enqueue.return_value = {"status": "enqueued", "mechanism": "rabbitmq"}

        # 1. First upload
        res1 = await client.post("/api/documents/upload", files=files, headers=auth_headers)
        assert res1.status_code == 202
        data1 = res1.json()
        assert len(data1["uploaded"]) == 1
        doc1_id = data1["uploaded"][0]["id"]
        assert mock_enqueue.call_count == 1

        # 2. Second upload of the EXACT same file content while doc1 is queued/processing
        files2 = {"files": ("report_v1.txt", io.BytesIO(file_bytes), "text/plain")}
        res2 = await client.post("/api/documents/upload", files=files2, headers=auth_headers)
        assert res2.status_code == 202
        data2 = res2.json()
        assert len(data2["uploaded"]) == 1
        # It must return the exact same document ID!
        assert data2["uploaded"][0]["id"] == doc1_id
        # Crucially: it must NOT have enqueued a second job to the worker!
        assert mock_enqueue.call_count == 1
        assert "actively being indexed" in data2["message"] or "monitored" in data2["message"]


@pytest.mark.asyncio
async def test_duplicate_upload_after_completed_reuses_existing_document(client: AsyncClient, test_db: AsyncSession):
    """Uploading the exact same file after it is completed should return the existing doc without re-embedding."""
    auth_headers = await _get_auth_header(client, "dedupe_user_2", "dedupe2@test.local")
    file_bytes = b"Financial report quarterly balance sheet document content."
    files = {"files": ("balance_sheet.txt", io.BytesIO(file_bytes), "text/plain")}

    with patch("app.services.queue_service.queue_service.enqueue_document_job", new_callable=AsyncMock) as mock_enqueue:
        mock_enqueue.return_value = {"status": "enqueued", "mechanism": "rabbitmq"}

        # 1. First upload
        res1 = await client.post("/api/documents/upload", files=files, headers=auth_headers)
        assert res1.status_code == 202
        doc_id = res1.json()["uploaded"][0]["id"]
        assert mock_enqueue.call_count == 1

        # Mark document as completed in DB
        doc_res = await test_db.execute(select(Document).where(Document.id == doc_id))
        doc = doc_res.scalar_one()
        doc.status = "completed"
        doc.chunk_count = 5
        await test_db.commit()

        # 2. Upload same file again
        files2 = {"files": ("balance_sheet.txt", io.BytesIO(file_bytes), "text/plain")}
        res2 = await client.post("/api/documents/upload", files=files2, headers=auth_headers)
        assert res2.status_code == 202
        data2 = res2.json()
        assert len(data2["uploaded"]) == 1
        assert data2["uploaded"][0]["id"] == doc_id
        assert data2["uploaded"][0]["status"] == "completed"
        # Must not enqueue another worker job
        assert mock_enqueue.call_count == 1
        assert "already uploaded and indexed" in data2["message"] or "skipped duplicate embedding" in data2["message"]


@pytest.mark.asyncio
async def test_reprocess_active_document_rejected(client: AsyncClient, test_db: AsyncSession):
    """Calling /reprocess on a document that is actively being processed should not enqueue a duplicate job."""
    auth_headers = await _get_auth_header(client, "reproc_user", "reproc@test.local")
    
    # Create active document
    now = datetime.now(timezone.utc)
    active_doc = Document(
        id=str(uuid.uuid4()),
        filename="active_job.pdf",
        file_type="pdf",
        file_size=1024,
        storage_path="/tmp/active_job.pdf",
        status="processing",
        created_at=now,
        updated_at=now,
        is_shared=True,
    )
    test_db.add(active_doc)
    await test_db.commit()

    with patch("app.services.queue_service.queue_service.enqueue_document_job", new_callable=AsyncMock) as mock_enqueue:
        res = await client.post(f"/api/documents/{active_doc.id}/reprocess", headers=auth_headers)
        assert res.status_code == 202
        data = res.json()
        assert data.get("already_processing") is True
        assert "actively being processed" in data["message"]
        # Enqueue should NOT be called
        assert not mock_enqueue.called


@pytest.mark.asyncio
async def test_room_upload_deduplication(client: AsyncClient, test_db: AsyncSession):
    """Uploading the same file to a room should attach existing document and avoid duplicate worker jobs."""
    auth_headers = await _get_auth_header(client, "room_dedupe_user", "rdu@test.local")
    
    # Create a room
    room_res = await client.post("/api/rooms", json={"name": "Dedupe Room", "description": "Test"}, headers=auth_headers)
    assert room_res.status_code == 201
    room_id = room_res.json()["id"]

    file_bytes = b"Special document for room collaboration testing."
    files = {"files": ("collab.txt", io.BytesIO(file_bytes), "text/plain")}

    with patch("app.services.queue_service.queue_service.enqueue_document_job", new_callable=AsyncMock) as mock_enqueue:
        mock_enqueue.return_value = {"status": "enqueued", "mechanism": "rabbitmq"}

        # 1. Upload to room first time
        res1 = await client.post(f"/api/rooms/{room_id}/upload", files=files, headers=auth_headers)
        assert res1.status_code == 202
        data1 = res1.json()
        assert len(data1["uploaded"]) == 1
        doc_id = data1["uploaded"][0]["id"]
        assert mock_enqueue.call_count == 1

        # 2. Upload to same room again while queued/processing
        files2 = {"files": ("collab.txt", io.BytesIO(file_bytes), "text/plain")}
        res2 = await client.post(f"/api/rooms/{room_id}/upload", files=files2, headers=auth_headers)
        assert res2.status_code == 202
        data2 = res2.json()
        assert len(data2["uploaded"]) == 1
        assert data2["uploaded"][0]["id"] == doc_id
        # Worker job should not be enqueued again
        assert mock_enqueue.call_count == 1


@pytest.mark.asyncio
async def test_recover_orphaned_jobs_preserves_active_jobs(test_db: AsyncSession):
    """Verify that recover_orphaned_processing_jobs preserves active jobs within timeout and only fails truly stale ones."""
    now = datetime.now(timezone.utc)
    fresh_time = now - timedelta(seconds=30)
    stale_time = now - timedelta(minutes=25)

    fresh_doc = Document(
        id=str(uuid.uuid4()),
        filename="fresh_doc.pdf",
        file_type="pdf",
        file_size=1024,
        storage_path="/tmp/fresh.pdf",
        status="processing",
        created_at=fresh_time,
        updated_at=fresh_time,
        is_shared=True,
    )
    stale_doc = Document(
        id=str(uuid.uuid4()),
        filename="stale_doc.pdf",
        file_type="pdf",
        file_size=1024,
        storage_path="/tmp/stale.pdf",
        status="processing",
        created_at=stale_time,
        updated_at=stale_time,
        is_shared=True,
    )
    test_db.add_all([fresh_doc, stale_doc])
    await test_db.commit()

    fresh_id = fresh_doc.id
    stale_id = stale_doc.id

    # Run orphan recovery with 600s timeout
    recovered_count = await recover_orphaned_processing_jobs(timeout_seconds=600)
    assert recovered_count >= 1

    # Expire test session cache to see database commit
    test_db.expire_all()

    # Check database status
    r_fresh = (await test_db.execute(select(Document).where(Document.id == fresh_id))).scalar_one()
    r_stale = (await test_db.execute(select(Document).where(Document.id == stale_id))).scalar_one()

    # The active/fresh job MUST stay 'processing' without interruption
    assert r_fresh.status == "processing"
    assert r_fresh.error_message is None

    # The stale job MUST be marked as failed
    assert r_stale.status == "failed"
    assert "timed out" in r_stale.error_message.lower()
