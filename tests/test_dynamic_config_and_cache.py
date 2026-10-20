"""Tests for dynamic configuration and pricing variables coming from cache and database."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pricing_plan import PricingPlan
from app.models.system_setting import SystemSetting
from app.services.config_service import config_service


@pytest.mark.asyncio
async def test_dynamic_settings_seeding_and_caching(test_db: AsyncSession):
    """Verify that settings are seeded into database and served via hot in-memory cache."""
    # Ensure seeded
    await config_service.seed_initial_config(test_db)

    # 1. Check database has system settings
    res = await test_db.execute(select(SystemSetting))
    db_settings = res.scalars().all()
    assert len(db_settings) > 0
    keys = [s.key for s in db_settings]
    assert "default_chat_provider" in keys
    assert "jwt_algorithm" in keys

    # 2. Check get_setting returns from cache
    val = await config_service.get_setting("default_chat_provider", db=test_db)
    assert val == "ollama"
    assert "default_chat_provider" in config_service._settings_cache

    # 3. Modify setting via service and verify DB & cache update
    await config_service.set_setting("retrieval_top_k", 8, db=test_db)
    assert config_service._settings_cache["retrieval_top_k"] == 8

    # Invalidate cache to verify database persistence fallback
    config_service._settings_cache.clear()
    fetched_from_db = await config_service.get_setting("retrieval_top_k", db=test_db)
    assert fetched_from_db == 8
    assert "retrieval_top_k" in config_service._settings_cache


@pytest.mark.asyncio
async def test_dynamic_pricing_plans_and_amounts(test_db: AsyncSession):
    """Verify pricing plans are stored in DB, served from cache, and amounts calculated dynamically."""
    await config_service.seed_initial_config(test_db)

    # 1. Fetch plans
    plans = await config_service.get_pricing_plans(test_db)
    assert len(plans) == 3
    plan_ids = [p.id for p in plans]
    assert "starter" in plan_ids
    assert "pro" in plan_ids
    assert "enterprise" in plan_ids

    # 2. Check cached plan lookup
    pro_plan = await config_service.get_plan_by_id("pro", test_db)
    assert pro_plan is not None
    assert pro_plan.name == "Professional"

    # 3. Dynamic calculate_plan_amount uses DB/cache rates
    pro_monthly_inr = await config_service.calculate_plan_amount("pro", "monthly", "INR", test_db)
    assert pro_monthly_inr == 3999.0

    pro_annual_inr = await config_service.calculate_plan_amount("pro", "annual", "INR", test_db)
    assert pro_annual_inr == round(3199.0 * 12, 2)

    pro_usd = await config_service.calculate_plan_amount("pro", "annual", "USD", test_db)
    assert pro_usd == round(39.0 * 12, 2)


@pytest.mark.asyncio
async def test_api_settings_and_pricing_integration(client: AsyncClient, test_db: AsyncSession):
    """Verify API endpoints serve and persist settings and pricing without hardcoded values."""
    await config_service.seed_initial_config(test_db)

    # 1. GET /api/pricing/plans
    res = await client.get("/api/pricing/plans")
    assert res.status_code == 200
    plans = res.json()
    assert len(plans) == 3

    # 2. Update setting through API
    update_res = await client.post(
        "/api/settings",
        json={"retrieval_top_k": 7, "similarity_threshold": 0.35},
    )
    assert update_res.status_code == 200
    data = update_res.json()
    assert data["retrieval_top_k"] == 7
    assert data["similarity_threshold"] == 0.35

    # 3. Read back settings from GET /api/settings
    get_res = await client.get("/api/settings")
    assert get_res.status_code == 200
    settings_data = get_res.json()
    assert settings_data["retrieval_top_k"] == 7
    assert settings_data["similarity_threshold"] == 0.35
