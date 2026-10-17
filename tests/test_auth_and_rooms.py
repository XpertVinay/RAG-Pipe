"""Test suite for JWT authentication, authorization, and room workspace endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_auth_registration_and_jwt_tokens(client: AsyncClient):
    """Verify that user registration yields Access Token, ID Token, and Refresh Token."""
    # Register new user
    reg_payload = {
        "email": "jwt_tester@test.local",
        "username": "jwttester",
        "password": "strongPassword123",
        "full_name": "JWT Tester",
    }
    res = await client.post("/api/auth/register", json=reg_payload)
    assert res.status_code == 201
    data = res.json()
    assert "access_token" in data
    assert "id_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "Bearer"
    assert data["user"]["username"] == "jwttester"

    access_token = data["access_token"]
    refresh_token = data["refresh_token"]

    # Access protected endpoint with Bearer token
    me_res = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["username"] == "jwttester"

    # Refresh access and ID tokens
    ref_res = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert ref_res.status_code == 200
    ref_data = ref_res.json()
    assert "access_token" in ref_data
    assert "id_token" in ref_data


@pytest.mark.asyncio
async def test_room_creation_and_context_references(client: AsyncClient):
    """Verify Room creation, attaching files, and database reference extraction."""
    # Create a room
    room_payload = {
        "name": "Integration Test Room",
        "description": "Room for verifying multi-file context persistence",
    }
    res = await client.post("/api/rooms", json=room_payload)
    assert res.status_code == 201
    room = res.json()
    assert room["name"] == "Integration Test Room"
    room_id = room["id"]
    assert "active_conversation_id" in room

    # List rooms
    list_res = await client.get("/api/rooms")
    assert list_res.status_code == 200
    rooms = list_res.json()
    assert any(r["id"] == room_id for r in rooms)

    # Get room details with references
    detail_res = await client.get(f"/api/rooms/{room_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["id"] == room_id
    assert "references" in detail
