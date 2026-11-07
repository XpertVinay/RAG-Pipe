"""API tests for document upload, listing, validation, and deletion."""

import io
import pytest
from httpx import AsyncClient


async def _get_auth_header(client: AsyncClient, username: str = "audit_user", email: str = "audit@test.local") -> dict:
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
async def test_unauthenticated_upload_rejected(client: AsyncClient):
    """Verify that unauthenticated document uploads are strictly rejected with 401."""
    files = {"files": ("unauth_test.txt", io.BytesIO(b"Secret content"), "text/plain")}
    response = await client.post("/api/documents/upload", files=files)
    assert response.status_code == 401
    assert "Not authenticated" in response.text or "Authentication required" in response.text

    # Also verify room upload requires authentication
    room_upload_res = await client.post("/api/rooms/test-room-id/upload", files=files)
    assert room_upload_res.status_code == 401


@pytest.mark.asyncio
async def test_upload_invalid_extension(client: AsyncClient):
    """Verify uploading an unpermitted file extension is rejected."""
    auth_headers = await _get_auth_header(client, "test_invalid_ext", "invalid_ext@test.local")
    files = {"files": ("malicious.exe", io.BytesIO(b"executable content"), "application/x-msdownload")}
    response = await client.post("/api/documents/upload", files=files, headers=auth_headers)
    assert response.status_code == 202
    data = response.json()
    assert len(data["failed"]) == 1
    err = data["failed"][0]["error"].lower()
    assert "not permitted" in err or "forbidden" in err


@pytest.mark.asyncio
async def test_upload_empty_file(client: AsyncClient):
    """Verify uploading an empty file is rejected."""
    auth_headers = await _get_auth_header(client, "test_empty_user", "empty_file@test.local")
    files = {"files": ("empty.txt", io.BytesIO(b""), "text/plain")}
    response = await client.post("/api/documents/upload", files=files, headers=auth_headers)
    assert response.status_code == 202
    data = response.json()
    assert len(data["failed"]) == 1
    assert "empty" in data["failed"][0]["error"]


@pytest.mark.asyncio
async def test_upload_valid_document_and_list(client: AsyncClient):
    """Verify uploading a valid TXT document, tracking uploader & audit trail, and listing it."""
    auth_headers = await _get_auth_header(client, "alice_uploader", "alice_uploader@test.local")
    file_content = b"Antigravity Document Ingestion System.\nProduction RAG implementation."
    files = {"files": ("manual.txt", io.BytesIO(file_content), "text/plain")}

    # 1. Upload with authenticated user
    upload_res = await client.post("/api/documents/upload", files=files, headers=auth_headers)
    assert upload_res.status_code == 202
    data = upload_res.json()
    assert len(data["uploaded"]) == 1
    doc_id = data["uploaded"][0]["id"]
    assert data["uploaded"][0]["filename"] == "manual.txt"
    assert data["uploaded"][0]["uploader_username"] == "alice_uploader"
    assert data["uploaded"][0]["uploader_email"] == "alice_uploader@test.local"
    assert data["uploaded"][0]["client_ip"] is not None

    # 2. Check Audit Trail endpoint
    audit_res = await client.get(f"/api/documents/{doc_id}/audit", headers=auth_headers)
    assert audit_res.status_code == 200
    audit_data = audit_res.json()
    assert audit_data["document_id"] == doc_id
    assert audit_data["filename"] == "manual.txt"
    assert audit_data["uploader_username"] == "alice_uploader"
    assert audit_data["uploader_email"] == "alice_uploader@test.local"
    assert len(audit_data["events"]) >= 1
    assert any(log["action"] == "document_upload" for log in audit_data["events"])

    # 3. List documents
    list_res = await client.get("/api/documents", headers=auth_headers)
    assert list_res.status_code == 200
    docs = list_res.json()["items"]
    assert any(d["id"] == doc_id for d in docs)

    # 4. Document details
    detail_res = await client.get(f"/api/documents/{doc_id}", headers=auth_headers)
    assert detail_res.status_code == 200
    assert detail_res.json()["id"] == doc_id
    assert detail_res.json()["uploader_username"] == "alice_uploader"

    # 5. Download / stream file inline
    file_res = await client.get(f"/api/documents/{doc_id}/file", headers=auth_headers)
    assert file_res.status_code == 200
    assert file_res.content == file_content

    # 6. Realtime evidence lookup with line highlighting
    ev_res = await client.get(f"/api/documents/{doc_id}/evidence?page=1&query=Antigravity", headers=auth_headers)
    assert ev_res.status_code == 200
    ev_data = ev_res.json()
    assert ev_data["document_id"] == doc_id
    assert ev_data["filename"] == "manual.txt"
    assert ev_data["page"] == 1
    assert len(ev_data["highlight_lines"]) >= 1
    assert any(line["is_match"] for line in ev_data["highlight_lines"])

    # 7. Reprocess document
    reproc_res = await client.post(f"/api/documents/{doc_id}/reprocess", headers=auth_headers)
    assert reproc_res.status_code == 202

    # Check Audit Trail has reprocess action recorded
    audit_res_after_reproc = await client.get(f"/api/documents/{doc_id}/audit", headers=auth_headers)
    assert audit_res_after_reproc.status_code == 200
    assert any(log["action"] == "document_reprocess" for log in audit_res_after_reproc.json()["events"])

    # 8. Delete document
    del_res = await client.delete(f"/api/documents/{doc_id}", headers=auth_headers)
    assert del_res.status_code == 200

    # 9. Verify deleted
    get_del = await client.get(f"/api/documents/{doc_id}", headers=auth_headers)
    assert get_del.status_code == 404


@pytest.mark.asyncio
async def test_document_live_file_authentication_and_query_token(client: AsyncClient):
    """Verify authenticated document file rendering via ?token= query parameter and cookies for iframes."""
    # 1. Register a user
    reg_res = await client.post("/api/auth/register", json={
        "email": "docviewer@test.local",
        "username": "docviewer",
        "password": "Password123!",
    })
    assert reg_res.status_code == 201
    token = reg_res.json()["access_token"]

    # 2. Upload document as this user
    doc_content = b"Simulated live document data for inline rendering and verification."
    files = {"files": ("sample_report.txt", io.BytesIO(doc_content), "text/plain")}
    upload_res = await client.post(
        "/api/documents/upload",
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert upload_res.status_code == 202
    doc_id = upload_res.json()["uploaded"][0]["id"]

    # 3. Direct unauthenticated request to /file should return 401
    unauth_res = await client.get(f"/api/documents/{doc_id}/file")
    assert unauth_res.status_code == 401
    assert "Authentication required" in unauth_res.json()["detail"]

    # 4. Request with query parameter ?token=... (as used by browser <iframe>) should succeed (200)
    query_res = await client.get(f"/api/documents/{doc_id}/file?token={token}")
    assert query_res.status_code == 200
    assert query_res.content == doc_content
    assert "text/plain" in query_res.headers["content-type"]
    assert "inline" in query_res.headers["content-disposition"]

    # 5. Request with cookie access_token=... (browser cookies) should succeed (200)
    cookie_res = await client.get(
        f"/api/documents/{doc_id}/file",
        cookies={"access_token": token},
    )
    assert cookie_res.status_code == 200
    assert cookie_res.content == doc_content

    # 6. Evidence endpoint returns file_url formatted with token query param before hash fragment
    ev_res = await client.get(
        f"/api/documents/{doc_id}/evidence?page=1&token={token}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ev_res.status_code == 200
    ev_data = ev_res.json()
    assert f"?token={token}#page=1" in ev_data["file_url"]

    # 7. Document attached to a public room should be accessible without auth
    room_res = await client.post(
        "/api/rooms",
        json={"name": "Public Showcase Room", "is_public": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert room_res.status_code == 201
    room_id = room_res.json()["id"]

    link_res = await client.post(
        f"/api/rooms/{room_id}/documents/{doc_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert link_res.status_code == 200

    # Now anonymous visitor can view it because it's attached to a public room
    pub_res = await client.get(f"/api/documents/{doc_id}/file")
    assert pub_res.status_code == 200
    assert pub_res.content == doc_content


@pytest.mark.asyncio
async def test_per_user_document_upload_and_persistent_embeddings_sharing(client: AsyncClient):
    """Verify document upload is per-user, embeddings are persistent & shared, and users maintain their own STM/LTM."""
    # 1. Register User A (Alice)
    res_a = await client.post("/api/auth/register", json={
        "email": "alice_shared@test.local",
        "username": "alice_shared",
        "password": "Password123!",
    })
    assert res_a.status_code == 201
    token_a = res_a.json()["access_token"]
    user_a_id = res_a.json()["user"]["id"]

    # 2. Register User B (Bob) as staff member
    res_b = await client.post("/api/auth/register", json={
        "email": "bob_shared@test.local",
        "username": "bob_shared",
        "password": "Password123!",
        "role": "staff",
    })
    assert res_b.status_code == 201
    token_b = res_b.json()["access_token"]
    user_b_id = res_b.json()["user"]["id"]

    # 3. User A uploads a document
    doc_content = b"Quantum Lattice Cryptography securely shields decentralized RAG agent knowledge pipelines."
    files = {"files": ("quantum_guide.txt", io.BytesIO(doc_content), "text/plain")}
    upload_res = await client.post(
        "/api/documents/upload",
        files=files,
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert upload_res.status_code == 202
    doc_data = upload_res.json()["uploaded"][0]
    doc_id = doc_data["id"]
    assert doc_data["user_id"] == user_a_id
    assert doc_data["uploader_username"] == "alice_shared"
    assert doc_data["is_persistent_vector"] is True
    # Private by default for strict session isolation
    assert doc_data["is_shared"] is False

    # 4. Strict isolation: User A sees it under scope=mine and scope=all
    res_a_docs = await client.get("/api/documents?scope=mine", headers={"Authorization": f"Bearer {token_a}"})
    assert res_a_docs.status_code == 200
    assert any(d["id"] == doc_id for d in res_a_docs.json()["items"])

    # User B does NOT see it under scope=mine, scope=shared, or scope=all while private
    res_b_docs = await client.get("/api/documents?scope=mine", headers={"Authorization": f"Bearer {token_b}"})
    assert res_b_docs.status_code == 200
    assert not any(d["id"] == doc_id for d in res_b_docs.json()["items"])

    res_b_private = await client.get("/api/documents?scope=all", headers={"Authorization": f"Bearer {token_b}"})
    assert res_b_private.status_code == 200
    assert not any(d["id"] == doc_id for d in res_b_private.json()["items"])

    # 5. User A explicitly shares the document publicly with RBAC toggle
    share_res = await client.patch(
        f"/api/documents/{doc_id}/share",
        json={"is_shared": True},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert share_res.status_code == 200
    assert share_res.json()["is_shared"] is True

    # User B now sees it under scope=shared and scope=all
    res_b_all = await client.get("/api/documents?scope=shared", headers={"Authorization": f"Bearer {token_b}"})
    assert res_b_all.status_code == 200
    # Process document so vectors exist for retrieval
    from app.ingestion.pipeline import ingestion_pipeline
    await ingestion_pipeline.process_document(doc_id)

    # 5. User B queries chat: can retrieve and cite the persistent vector embeddings uploaded by User A
    chat_res = await client.post(
        "/api/chat/query",
        json={
            "message": "How does Quantum Lattice Cryptography shield RAG knowledge?",
            "document_ids": [doc_id],
        },
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert chat_res.status_code == 200
    chat_data = chat_res.json()
    assert len(chat_data["citations"]) > 0
    assert any(c["filename"] == "quantum_guide.txt" for c in chat_data["citations"])
    conv_id_b = chat_data["conversation_id"]

    # 6. User B chatting records STM and LTM for User B's own chat
    pref_res = await client.post(
        "/api/chat/query",
        json={
            "conversation_id": conv_id_b,
            "message": "I prefer bullet points and concise technical summaries in all responses.",
        },
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert pref_res.status_code == 200

    # Verify User B (staff) can inspect their user-specific STM and LTM
    mem_b_res = await client.get("/api/memory?scope=user_specific", headers={"Authorization": f"Bearer {token_b}"})
    assert mem_b_res.status_code == 200
    mem_items_b = mem_b_res.json()
    assert any(m["user_id"] == user_b_id for m in mem_items_b)

    # Verify User A (common user) cannot view STM/LTM memory (403 Forbidden)
    mem_a_res = await client.get("/api/memory?scope=user_specific", headers={"Authorization": f"Bearer {token_a}"})
    assert mem_a_res.status_code == 403

    # 7. User A deletes their personal document record:
    # Persistent vector embeddings remain available for other users
    del_res = await client.delete(
        f"/api/documents/{doc_id}?purge_vectors=false",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert del_res.status_code == 200
    assert del_res.json()["persistent_vectors_retained"] is True


