"""API tests for system health checks and settings."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Verify system health endpoint returns 200 and component statuses."""
    res = await client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ["healthy", "degraded"]
    assert "components" in data
    assert "database" in data["components"]
    assert "vector_store" in data["components"]


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
