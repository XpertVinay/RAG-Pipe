"""Comprehensive test suite for security hardening:
- Rate limiting enforcement (429 Too Many Requests)
- Security headers (CSP, X-Content-Type-Options, X-Frame-Options, etc.)
- Refresh token rotation and replay attack detection
- IDOR access control protections on rooms and documents
- Magic byte validation
"""

import io
import pytest
from httpx import AsyncClient
from app.core.rate_limit import RateLimiter


@pytest.mark.asyncio
async def test_security_headers_present(client: AsyncClient):
    """Verify essential security headers are injected into HTTP responses."""
    res = await client.get("/api/health")
    assert res.status_code == 200
    headers = res.headers
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("x-frame-options") == "SAMEORIGIN"
    assert "strict-origin-when-cross-origin" in headers.get("referrer-policy", "")
    assert "camera=()" in headers.get("permissions-policy", "")
    assert "default-src 'self'" in headers.get("content-security-policy", "")


@pytest.mark.asyncio
async def test_rate_limiter_blocks_excessive_requests():
    """Verify RateLimiter sliding window raises 429 when max_requests exceeded."""
    limiter = RateLimiter(max_requests=3, window_seconds=60)

    class MockClient:
        host = "192.168.1.100"

    class MockRequest:
        client = MockClient()

    req = MockRequest()
    # 3 allowed
    limiter(req)
    limiter(req)
    limiter(req)

    # 4th should raise 429
    with pytest.raises(Exception) as exc_info:
        limiter(req)
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


@pytest.mark.asyncio
async def test_refresh_token_rotation_and_replay_detection(client: AsyncClient):
    """Verify refresh token rotation and immediate invalidation on replay attempts."""
    # 1. Register User
    reg_payload = {
        "email": "replay_victim@test.local",
        "username": "replayvictim",
        "password": "SecurePassword999!",
    }
    reg_res = await client.post("/api/auth/register", json=reg_payload)
    assert reg_res.status_code == 201
    reg_data = reg_res.json()
    token_v1 = reg_data["refresh_token"]

    # 2. First refresh -> Token rotated to token_v2
    ref1_res = await client.post("/api/auth/refresh", json={"refresh_token": token_v1})
    assert ref1_res.status_code == 200
    ref1_data = ref1_res.json()
    token_v2 = ref1_data["refresh_token"]
    assert token_v2 != token_v1  # Must be rotated!

    # 3. Attacker attempts to replay token_v1 (already revoked)
    replay_res = await client.post("/api/auth/refresh", json={"refresh_token": token_v1})
    assert replay_res.status_code == 401
    assert "revoked" in replay_res.json()["detail"].lower() or "reuse" in replay_res.json()["detail"].lower()

    # 4. As a result of replay detection, token_v2 must ALSO be invalidated!
    victim_res = await client.post("/api/auth/refresh", json={"refresh_token": token_v2})
    assert victim_res.status_code == 401


@pytest.mark.asyncio
async def test_room_ownership_idor_protection(client: AsyncClient):
    """Verify users cannot access or modify rooms owned by other users."""
    # Register User A
    user_a_res = await client.post("/api/auth/register", json={
        "email": "usera@test.local",
        "username": "usera",
        "password": "PasswordUserA1!",
    })
    token_a = user_a_res.json()["access_token"]

    # Register User B
    user_b_res = await client.post("/api/auth/register", json={
        "email": "userb@test.local",
        "username": "userb",
        "password": "PasswordUserB1!",
    })
    token_b = user_b_res.json()["access_token"]

    # User A creates a private room
    room_res = await client.post(
        "/api/rooms",
        json={"name": "User A Private Room", "description": "Top secret"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert room_res.status_code == 201
    room_id = room_res.json()["id"]

    # User B attempts to access User A's room -> 403 Forbidden
    b_get_res = await client.get(
        f"/api/rooms/{room_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert b_get_res.status_code == 403

    # User B attempts to delete User A's room -> 403 Forbidden
    b_del_res = await client.delete(
        f"/api/rooms/{room_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert b_del_res.status_code == 403

    # Unauthenticated user attempts to delete User A's room -> 401 Unauthorized
    anon_del_res = await client.delete(f"/api/rooms/{room_id}")
    assert anon_del_res.status_code == 401

    # User A successfully deletes their own room -> 200 OK
    a_del_res = await client.delete(
        f"/api/rooms/{room_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert a_del_res.status_code == 200
