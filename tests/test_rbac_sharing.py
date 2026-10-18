"""Tests for RBAC authorization, session isolation, and room/document sharing."""

import io
import pytest
from httpx import AsyncClient


async def _register(client: AsyncClient, username: str, email: str, role: str = "user") -> tuple[str, str]:
    """Helper to register and return (user_id, token)."""
    res = await client.post("/api/auth/register", json={
        "username": username,
        "email": email,
        "password": "Password123!",
        "role": role,
    })
    assert res.status_code == 201
    return res.json()["user"]["id"], res.json()["access_token"]


@pytest.mark.asyncio
async def test_session_isolation_and_rbac_document_sharing(client: AsyncClient):
    """Verify documents are private by default, not listed to other users, and only visible when shared or public."""
    # 1. Register User 1 (Alice) and User 2 (Bob)
    u1_id, token_1 = await _register(client, "alice_iso", "alice_iso@test.local")
    u2_id, token_2 = await _register(client, "bob_iso", "bob_iso@test.local")

    h1 = {"Authorization": f"Bearer {token_1}"}
    h2 = {"Authorization": f"Bearer {token_2}"}

    # 2. Alice uploads a private document
    file_bytes = b"Secret financial strategy and private research for Alice only."
    upload_res = await client.post(
        "/api/documents/upload",
        files={"files": ("alice_private.txt", io.BytesIO(file_bytes), "text/plain")},
        headers=h1,
    )
    assert upload_res.status_code == 202
    doc = upload_res.json()["uploaded"][0]
    doc_id = doc["id"]
    assert doc["is_shared"] is False

    # 3. Alice can see her document
    alice_docs = await client.get("/api/documents?scope=all", headers=h1)
    assert any(d["id"] == doc_id for d in alice_docs.json()["items"])

    # 4. Bob CANNOT see Alice's document under any scope
    bob_all = await client.get("/api/documents?scope=all", headers=h2)
    assert not any(d["id"] == doc_id for d in bob_all.json()["items"])

    bob_shared = await client.get("/api/documents?scope=shared", headers=h2)
    assert not any(d["id"] == doc_id for d in bob_shared.json()["items"])

    # 5. Bob direct file access is strictly forbidden (403)
    bob_view = await client.get(f"/api/documents/{doc_id}/file", headers=h2)
    assert bob_view.status_code == 403

    # 6. Bob cannot toggle Alice's document sharing (403)
    bob_share_attempt = await client.patch(
        f"/api/documents/{doc_id}/share",
        json={"is_shared": True},
        headers=h2,
    )
    assert bob_share_attempt.status_code == 403

    # 7. Alice shares document publicly
    alice_share = await client.patch(
        f"/api/documents/{doc_id}/share",
        json={"is_shared": True},
        headers=h1,
    )
    assert alice_share.status_code == 200
    assert alice_share.json()["is_shared"] is True

    # 8. Now Bob sees it under shared and all, and can view file
    bob_all_shared = await client.get("/api/documents?scope=all", headers=h2)
    assert any(d["id"] == doc_id for d in bob_all_shared.json()["items"])

    bob_view_ok = await client.get(f"/api/documents/{doc_id}/file", headers=h2)
    assert bob_view_ok.status_code == 200
    assert bob_view_ok.content == file_bytes


@pytest.mark.asyncio
async def test_room_membership_rbac_and_sharing(client: AsyncClient):
    """Verify room workspaces are private by default, and sharing with members grants access with role hierarchy."""
    u1_id, token_1 = await _register(client, "alice_room", "alice_room@test.local")
    u2_id, token_2 = await _register(client, "bob_member", "bob_member@test.local")
    u3_id, token_3 = await _register(client, "eve_stranger", "eve_stranger@test.local")

    h1 = {"Authorization": f"Bearer {token_1}"}
    h2 = {"Authorization": f"Bearer {token_2}"}
    h3 = {"Authorization": f"Bearer {token_3}"}

    # 1. Alice creates a private room
    room_res = await client.post(
        "/api/rooms",
        json={"name": "Alpha Project Workspace", "description": "Restricted team room", "is_public": False},
        headers=h1,
    )
    assert room_res.status_code == 201
    room_id = room_res.json()["id"]

    # 2. Alice uploads a file to the room
    upload_res = await client.post(
        f"/api/rooms/{room_id}/upload",
        files={"files": ("project_alpha.txt", io.BytesIO(b"Alpha workspace specs"), "text/plain")},
        headers=h1,
    )
    assert upload_res.status_code == 202
    doc_id = upload_res.json()["uploaded"][0]["id"]

    # 3. Eve (uninvited) cannot access the room (403)
    eve_res = await client.get(f"/api/rooms/{room_id}", headers=h3)
    assert eve_res.status_code == 403

    # Eve cannot access the room's document (403)
    eve_doc = await client.get(f"/api/documents/{doc_id}/file", headers=h3)
    assert eve_doc.status_code == 403

    # 4. Alice invites Bob as 'viewer'
    member_res = await client.post(
        f"/api/rooms/{room_id}/members",
        json={"username_or_email": "bob_member", "role": "viewer"},
        headers=h1,
    )
    assert member_res.status_code == 201
    assert member_res.json()["user_id"] == u2_id
    assert member_res.json()["role"] == "viewer"

    # 5. Bob can now access the room and room document
    bob_room = await client.get(f"/api/rooms/{room_id}", headers=h2)
    assert bob_room.status_code == 200
    assert bob_room.json()["id"] == room_id
    assert bob_room.json()["user_role"] == "viewer"

    bob_doc = await client.get(f"/api/documents/{doc_id}/file", headers=h2)
    assert bob_doc.status_code == 200

    # 6. Bob has 'viewer' role: cannot upload or delete room files (403)
    bob_upload = await client.post(
        f"/api/rooms/{room_id}/upload",
        files={"files": ("unauthorized.txt", io.BytesIO(b"Nope"), "text/plain")},
        headers=h2,
    )
    assert bob_upload.status_code == 403

    # 7. Alice upgrades Bob to 'editor'
    upgrade_res = await client.post(
        f"/api/rooms/{room_id}/members",
        json={"username_or_email": "bob_member", "role": "editor"},
        headers=h1,
    )
    assert upgrade_res.status_code == 201
    assert upgrade_res.json()["role"] == "editor"

    # 8. Bob can now upload as editor
    bob_editor_upload = await client.post(
        f"/api/rooms/{room_id}/upload",
        files={"files": ("editor_contribution.txt", io.BytesIO(b"Bob contribution"), "text/plain")},
        headers=h2,
    )
    assert bob_editor_upload.status_code == 202

    # 9. Alice removes Bob from room
    del_mem_res = await client.delete(f"/api/rooms/{room_id}/members/{u2_id}", headers=h1)
    assert del_mem_res.status_code == 200

    # 10. Bob can no longer access room (403)
    bob_denied = await client.get(f"/api/rooms/{room_id}", headers=h2)
    assert bob_denied.status_code == 403
