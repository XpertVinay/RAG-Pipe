"""Unit & integration tests for multi-worker concurrent document chunking and reverse proxy configuration."""

import math
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select, func

from app.config import get_settings
from app.models.document import Document, DocumentChunk, DocumentPartition
from app.ingestion.pipeline import IngestionPipeline
from app.services.queue_service import QueueService


@pytest.mark.asyncio
async def test_document_list_response_backward_compatibility(client: AsyncClient, test_db):
    """Verify DocumentListResponse returns both 'items' and 'documents' for complete frontend compatibility."""
    # Register/login user
    reg = await client.post("/api/auth/register", json={
        "username": "chunk_tester",
        "email": "chunk_tester@test.local",
        "password": "Password123!",
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Upload test document
    files = {"files": ("test_doc.txt", b"Hello concurrent chunking world! " * 20, "text/plain")}
    res = await client.post("/api/documents/upload", files=files, headers=headers)
    assert res.status_code == 202

    # Query /api/documents
    list_res = await client.get("/api/documents", headers=headers)
    assert list_res.status_code == 200
    data = list_res.json()
    assert "items" in data
    assert "documents" in data
    assert len(data["items"]) >= 1
    assert len(data["documents"]) == len(data["items"])
    assert data["items"][0]["filename"] == "test_doc.txt"
    assert data["documents"][0]["filename"] == "test_doc.txt"


def test_concurrency_config_flags():
    """Verify configuration flags for multi-worker concurrent chunking and reverse proxy."""
    settings = get_settings()
    assert hasattr(settings, "ENABLE_CONCURRENT_CHUNK_PROCESSING")
    assert hasattr(settings, "WORKER_CONCURRENCY")
    assert hasattr(settings, "NUM_CHUNKING_WORKERS")
    assert hasattr(settings, "CHUNK_PARTITION_SIZE_MB")
    assert hasattr(settings, "CHUNK_PARTITION_THRESHOLD_MB")
    assert hasattr(settings, "RABBITMQ_CHUNK_QUEUE_NAME")
    assert hasattr(settings, "LOAD_BALANCER_ENABLED")
    assert hasattr(settings, "PROXY_PORT")

    # Default should utilize 1 worker without spinning up more unless configured
    assert settings.WORKER_CONCURRENCY >= 1
    assert settings.CHUNK_PARTITION_SIZE_MB > 0


@pytest.mark.asyncio
async def test_process_chunk_partition_and_completion_aggregation(test_db, monkeypatch):
    """Verify independent processing of chunk partitions and aggregated document completion."""
    settings = get_settings()
    pipeline = IngestionPipeline()

    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        filename="distributed_report.pdf",
        file_type="pdf",
        file_size=9 * 1024 * 1024,  # 9 MB
        storage_path="/tmp/fake_9mb.pdf",
        status="processing",
        chunk_count=0,
    )
    test_db.add(doc)

    part1_id = str(uuid.uuid4())
    part2_id = str(uuid.uuid4())
    part3_id = str(uuid.uuid4())

    part1 = DocumentPartition(
        id=part1_id,
        document_id=doc_id,
        partition_index=0,
        total_partitions=3,
        status="queued",
        chunk_count=2,
    )
    part2 = DocumentPartition(
        id=part2_id,
        document_id=doc_id,
        partition_index=1,
        total_partitions=3,
        status="queued",
        chunk_count=2,
    )
    part3 = DocumentPartition(
        id=part3_id,
        document_id=doc_id,
        partition_index=2,
        total_partitions=3,
        status="queued",
        chunk_count=2,
    )
    test_db.add_all([part1, part2, part3])
    await test_db.commit()

    # Mock vector store add_chunks_async to avoid external Ollama calls in unit test
    async def mock_add_chunks_async(chunks, batch_size=8, on_batch_complete=None):
        return [str(uuid.uuid4()) for _ in chunks]

    from app.ingestion.vector_store import vector_store
    monkeypatch.setattr(vector_store, "add_chunks_async", mock_add_chunks_async)

    # Process Partition 1 (chunks 1 & 2)
    chunks_p1 = [
        {"content": "Chunk 1 content of 9MB file", "metadata": {"chunk_id": f"{doc_id}_c0", "chunk_index": 0}},
        {"content": "Chunk 2 content of 9MB file", "metadata": {"chunk_id": f"{doc_id}_c1", "chunk_index": 1}},
    ]
    res1 = await pipeline.process_chunk_partition(part1_id, doc_id, 0, 3, chunks_p1)
    assert res1 is True

    # Verify partition 1 completed, document still processing
    refreshed_p1 = await test_db.get(DocumentPartition, part1_id)
    await test_db.refresh(refreshed_p1)
    assert refreshed_p1.status == "completed"
    refreshed_doc = await test_db.get(Document, doc_id)
    await test_db.refresh(refreshed_doc)
    assert refreshed_doc.status == "processing"

    # Process Partition 2 (chunks 3 & 4)
    chunks_p2 = [
        {"content": "Chunk 3 content of 9MB file", "metadata": {"chunk_id": f"{doc_id}_c2", "chunk_index": 2}},
        {"content": "Chunk 4 content of 9MB file", "metadata": {"chunk_id": f"{doc_id}_c3", "chunk_index": 3}},
    ]
    res2 = await pipeline.process_chunk_partition(part2_id, doc_id, 1, 3, chunks_p2)
    assert res2 is True

    # Process Partition 3 (chunks 5 & 6) -> Final partition should complete document!
    chunks_p3 = [
        {"content": "Chunk 5 content of 9MB file", "metadata": {"chunk_id": f"{doc_id}_c4", "chunk_index": 4}},
        {"content": "Chunk 6 content of 9MB file", "metadata": {"chunk_id": f"{doc_id}_c5", "chunk_index": 5}},
    ]
    res3 = await pipeline.process_chunk_partition(part3_id, doc_id, 2, 3, chunks_p3)
    assert res3 is True

    # Check that document is now marked 'completed' with all 6 chunks aggregated
    completed_doc = await test_db.get(Document, doc_id)
    await test_db.refresh(completed_doc)
    assert completed_doc.status == "completed"
    assert completed_doc.chunk_count == 6

    # Verify all 6 chunks are in DocumentChunk table
    chunks_res = await test_db.execute(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == doc_id)
    )
    assert chunks_res.scalar_one() == 6


@pytest.mark.asyncio
async def test_queue_service_enqueue_chunk_partition_fallback():
    """Verify QueueService handles chunk partition jobs gracefully with local fallback."""
    queue = QueueService()
    part_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    chunks = [{"content": "Test chunk partition", "metadata": {"chunk_id": "c1", "chunk_index": 0}}]

    result = await queue.enqueue_chunk_partition_job(
        document_id=doc_id,
        partition_id=part_id,
        partition_index=0,
        total_partitions=1,
        chunks=chunks,
    )
    assert result["status"] == "queued"
    assert result["document_id"] == doc_id
    assert result["partition_id"] == part_id
    assert result["mechanism"] in ("rabbitmq", "background_task")
