"""Tests for API Versioning (v1), version discovery, and static asset optimization pipeline."""

import json
from pathlib import Path
import pytest
from httpx import AsyncClient

from app.config import get_settings

settings = get_settings()


@pytest.mark.asyncio
async def test_api_version_discovery_endpoints(client: AsyncClient):
    """Test both /api/version and /api/v1/version discovery endpoints."""
    # 1. Base /api/version
    res = await client.get("/api/version")
    assert res.status_code == 200
    data = res.json()
    assert data["current_version"] == "v1"
    assert "v1" in data["supported_versions"]
    assert "endpoints" in data
    assert data["endpoints"]["auth"] == "/api/v1/auth"
    assert data["endpoints"]["pricing"] == "/api/v1/pricing"

    # 2. Versioned /api/v1/version
    res_v1 = await client.get("/api/v1/version")
    assert res_v1.status_code == 200
    data_v1 = res_v1.json()
    assert data_v1["api_version"] == "v1"
    assert data_v1["deprecated"] is False
    assert "capabilities" in data_v1
    assert "client_compatibility" in data_v1
    assert "mobile_flutter" in data_v1["client_compatibility"]
    assert "mobile_react_native" in data_v1["client_compatibility"]
    assert "mobile_ios_swift" in data_v1["client_compatibility"]


@pytest.mark.asyncio
async def test_versioned_routes_execution(client: AsyncClient):
    """Test that official /api/v1/* routes return identical status and data as legacy /api/*."""
    # Health check on v1
    v1_health = await client.get("/api/v1/health")
    assert v1_health.status_code == 200
    assert "status" in v1_health.json()

    # Legacy health check
    leg_health = await client.get("/api/health")
    assert leg_health.status_code == 200
    assert leg_health.json()["status"] == v1_health.json()["status"]

    # Pricing plans on v1
    v1_plans = await client.get("/api/v1/pricing/plans")
    assert v1_plans.status_code == 200
    assert len(v1_plans.json()) >= 3

    # Legacy pricing plans
    leg_plans = await client.get("/api/pricing/plans")
    assert leg_plans.status_code == 200
    assert len(leg_plans.json()) == len(v1_plans.json())

    # Header check
    assert v1_health.headers.get("X-API-Version") == "1.0.0"


@pytest.mark.asyncio
async def test_asset_manifest_and_dist_files():
    """Verify that build artifacts exist, are valid JSON, and contain minified/precompressed outputs."""
    base_dir = Path(__file__).resolve().parent.parent
    manifest_path = base_dir / "app" / "static" / "dist" / "manifest.json"
    assert manifest_path.exists(), "Asset build manifest.json must exist in app/static/dist"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "files" in manifest
    assert "bundle.min.css" in manifest["files"]
    assert "bundle.min.js" in manifest["files"]
    assert "pricing.min.js" in manifest["files"]

    # Verify files physically exist on disk
    css_bundle = base_dir / "app" / "static" / "dist" / "bundle.min.css"
    js_bundle = base_dir / "app" / "static" / "dist" / "bundle.min.js"
    pricing_min = base_dir / "app" / "static" / "dist" / "pricing.min.js"

    assert css_bundle.exists() and css_bundle.stat().st_size > 0
    assert js_bundle.exists() and js_bundle.stat().st_size > 0
    assert pricing_min.exists() and pricing_min.stat().st_size > 0

    # Verify precompressed gzip files exist
    assert css_bundle.with_suffix(".css.gz").exists()
    assert js_bundle.with_suffix(".js.gz").exists()
    assert pricing_min.with_suffix(".js.gz").exists()


@pytest.mark.asyncio
async def test_ui_renders_with_optimized_assets(client: AsyncClient, monkeypatch):
    """Test dashboard and pricing pages render bundle references when optimized assets are active."""
    # Force USE_OPTIMIZED_ASSETS = True
    monkeypatch.setattr(settings, "USE_OPTIMIZED_ASSETS", True)

    res = await client.get("/")
    assert res.status_code == 200
    html = res.text
    assert "/static/dist/bundle.min.css" in html
    assert "/static/dist/bundle.min.js" in html

    # Pricing page
    res_pricing = await client.get("/pricing")
    assert res_pricing.status_code == 200
    pricing_html = res_pricing.text
    assert "/static/dist/bundle.min.css" in pricing_html
    assert "/static/dist/pricing.min.js" in pricing_html
