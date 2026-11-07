"""Test suite verifying backend input validation on API requests and Pydantic schemas."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_auth_registration_validation(client: AsyncClient):
    """Verify backend rejects invalid registration payloads with 422."""
    # 1. Invalid email format
    res = await client.post("/api/auth/register", json={
        "email": "not-an-email",
        "username": "validuser",
        "password": "validPassword123",
    })
    assert res.status_code == 422
    data = res.json()
    assert "detail" in data
    assert "email" in data["detail"].lower()

    # 2. Too short username (< 3 chars)
    res = await client.post("/api/auth/register", json={
        "email": "valid@example.com",
        "username": "ab",
        "password": "validPassword123",
    })
    assert res.status_code == 422
    data = res.json()
    assert "username" in data["detail"].lower()

    # 3. Invalid characters in username
    res = await client.post("/api/auth/register", json={
        "email": "valid@example.com",
        "username": "invalid user!",
        "password": "validPassword123",
    })
    assert res.status_code == 422

    # 4. Too short password (< 6 chars)
    res = await client.post("/api/auth/register", json={
        "email": "valid@example.com",
        "username": "validuser",
        "password": "123",
    })
    assert res.status_code == 422
    data = res.json()
    assert "password" in data["detail"].lower()

    # 5. Whitespace-only password
    res = await client.post("/api/auth/register", json={
        "email": "valid@example.com",
        "username": "validuser",
        "password": "      ",
    })
    assert res.status_code == 422

    # 6. Invalid role
    res = await client.post("/api/auth/register", json={
        "email": "valid@example.com",
        "username": "validuser",
        "password": "validPassword123",
        "role": "superadmin_hacker",
    })
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_auth_login_validation(client: AsyncClient):
    """Verify backend rejects invalid login payloads."""
    # Short username
    res = await client.post("/api/auth/login", json={
        "username": "a",
        "password": "password123",
    })
    assert res.status_code == 422

    # Short password
    res = await client.post("/api/auth/login", json={
        "username": "validuser",
        "password": "123",
    })
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_chat_message_validation(client: AsyncClient):
    """Verify chat endpoint rejects empty, whitespace, and oversized messages."""
    # Empty string
    res = await client.post("/api/chat/query", json={"message": ""})
    assert res.status_code == 422

    # Whitespace only
    res = await client.post("/api/chat/query", json={"message": "    \n\t   "})
    assert res.status_code == 422
    assert "whitespace" in res.json()["detail"].lower()

    # Oversized message (> 4000 characters)
    oversized = "A" * 4001
    res = await client.post("/api/chat/query", json={"message": oversized})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_room_creation_validation(client: AsyncClient):
    """Verify room creation validation on name and description."""
    # Whitespace only room name (< 2 chars stripped)
    res = await client.post("/api/rooms", json={"name": "   "})
    assert res.status_code == 422
    assert "room name" in res.json()["detail"].lower()

    # Single character name
    res = await client.post("/api/rooms", json={"name": "X"})
    assert res.status_code == 422

    # Excessively long name (> 150 chars)
    res = await client.post("/api/rooms", json={"name": "A" * 151})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_room_member_validation(client: AsyncClient):
    """Verify room member invitation validation."""
    # Register user
    reg = await client.post("/api/auth/register", json={
        "email": "roomowner_val@test.local",
        "username": "roomowner_val",
        "password": "Password123!",
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create valid room first
    create_res = await client.post("/api/rooms", json={"name": "Member Validation Room"}, headers=headers)
    assert create_res.status_code == 201
    room_id = create_res.json()["id"]

    # 2. Too short identifier
    res = await client.post(f"/api/rooms/{room_id}/members", json={
        "username_or_email": "a",
        "role": "viewer",
    }, headers=headers)
    assert res.status_code == 422

    # 3. Invalid role
    res = await client.post(f"/api/rooms/{room_id}/members", json={
        "username_or_email": "valid_member",
        "role": "unauthorized_role",
    }, headers=headers)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_settings_validation(client: AsyncClient):
    """Verify runtime settings validation for provider and model."""
    # Invalid chat provider
    res = await client.post("/api/settings", json={
        "default_chat_provider": "unsupported_llm_xyz",
    })
    assert res.status_code == 422
    assert "provider" in res.json()["detail"].lower()

    # Invalid embedding provider
    res = await client.post("/api/settings", json={
        "default_embedding_provider": "unsupported_embedding_xyz",
    })
    assert res.status_code == 422

    # Retrieval top_k out of bounds (> 20)
    res = await client.post("/api/settings", json={
        "retrieval_top_k": 99,
    })
    assert res.status_code == 422
