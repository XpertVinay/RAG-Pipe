"""API tests for system health checks and settings."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Verify system health endpoint returns 200 and component statuses."""
    # Test legacy and versioned health endpoints
    res = await client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ["healthy", "degraded"]
    assert "components" in data
    assert "database" in data["components"]
    assert "vector_store" in data["components"]

    # Test root-level /health endpoint (required for Docker, Nginx, ALB)
    root_res = await client.get("/health")
    assert root_res.status_code == 200
    assert root_res.json()["status"] in ["healthy", "degraded"]

    # Test ultra-fast liveness probes
    assert (await client.get("/healthz")).status_code == 200
    assert (await client.get("/ping")).status_code == 200
    assert (await client.get("/health/ping")).status_code == 200
    assert (await client.get("/health/ready")).status_code == 200
    assert (await client.get("/health/liveness")).status_code == 200


@pytest.mark.asyncio
async def test_get_and_update_settings(client: AsyncClient):
    """Verify reading and updating settings."""
    # 1. Read settings
    get_res = await client.get("/api/settings")
    assert get_res.status_code == 200
    settings = get_res.json()
    assert "default_chat_provider" in settings
    assert "available_chat_providers" in settings

    # 2. Update settings
    update_res = await client.post(
        "/api/settings",
        json={"retrieval_top_k": 6, "default_chat_provider": "ollama"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["retrieval_top_k"] == 6
