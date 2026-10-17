"""API tests for document upload, listing, validation, and deletion."""

import io
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_upload_invalid_extension(client: AsyncClient):
    """Verify uploading an unpermitted file extension is rejected."""
    files = {"files": ("malicious.exe", io.BytesIO(b"executable content"), "application/x-msdownload")}
    response = await client.post("/api/documents/upload", files=files)
    assert response.status_code == 202
    data = response.json()
    assert len(data["failed"]) == 1
    assert "not permitted" in data["failed"][0]["error"]


@pytest.mark.asyncio
async def test_upload_empty_file(client: AsyncClient):
    """Verify uploading an empty file is rejected."""
    files = {"files": ("empty.txt", io.BytesIO(b""), "text/plain")}
    response = await client.post("/api/documents/upload", files=files)
    assert response.status_code == 202
    data = response.json()
    assert len(data["failed"]) == 1
    assert "empty" in data["failed"][0]["error"]


@pytest.mark.asyncio
async def test_upload_valid_document_and_list(client: AsyncClient):
    """Verify uploading a valid TXT document and listing it."""
    file_content = b"Antigravity Document Ingestion System.\nProduction RAG implementation."
    files = {"files": ("manual.txt", io.BytesIO(file_content), "text/plain")}

    # 1. Upload
    upload_res = await client.post("/api/documents/upload", files=files)
    assert upload_res.status_code == 202
    data = upload_res.json()
    assert len(data["uploaded"]) == 1
    doc_id = data["uploaded"][0]["id"]
    assert data["uploaded"][0]["filename"] == "manual.txt"

    # 2. List documents
    list_res = await client.get("/api/documents")
    assert list_res.status_code == 200
    docs = list_res.json()["items"]
    assert any(d["id"] == doc_id for d in docs)

    # 3. Document details
    detail_res = await client.get(f"/api/documents/{doc_id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["id"] == doc_id

    # 4. Reprocess document
    reproc_res = await client.post(f"/api/documents/{doc_id}/reprocess")
    assert reproc_res.status_code == 202

    # 5. Delete document
    del_res = await client.delete(f"/api/documents/{doc_id}")
    assert del_res.status_code == 200

    # 6. Verify deleted
    get_del = await client.get(f"/api/documents/{doc_id}")
    assert get_del.status_code == 404
