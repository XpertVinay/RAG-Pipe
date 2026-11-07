"""Comprehensive test suite for Enterprise Audit Trail, Legal Compliance, Backups, and Business Risk Engine."""

import os
from pathlib import Path
import pytest
import pytest_asyncio
from httpx import AsyncClient

from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal
from app.models.audit_trail import AuditTrailRecord
from app.services.audit_backup import audit_backup_manager
from app.services.audit_service import audit_service
from app.services.risk_engine import business_risk_engine


@pytest.mark.asyncio
async def test_audit_backup_creation_and_integrity(tmp_path):
    """Verify creating a compressed legal audit archive and checking SHA-256 integrity."""
    # Ensure logs exist
    logs_dir = Path("./logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    test_log = logs_dir / "audit_trail.jsonl"
    test_log.write_text('{"event": "test_compliance_event", "status": "success"}\n', encoding="utf-8")

    # Create backup archive
    backup_result = audit_backup_manager.create_backup(
        retention_days=30,
        operator_username="test_super_admin",
        compliance_remark="Test backup for legal preservation",
    )

    assert backup_result["filename"].endswith(".tar.gz")
    assert backup_result["sha256"] is not None
    assert len(backup_result["sha256"]) == 64
    assert backup_result["operator"] == "test_super_admin"

    # List backups
    backups = audit_backup_manager.list_backups()
    assert len(backups) >= 1
    target = next((b for b in backups if b["filename"] == backup_result["filename"]), None)
    assert target is not None
    assert target["integrity_verified"] is True

    # Verify single backup
    verification = audit_backup_manager.verify_backup(backup_result["filename"])
    assert verification["verified"] is True
    assert verification["expected_sha256"] == backup_result["sha256"]


@pytest.mark.asyncio
async def test_business_risk_engine_instantaneous_risk():
    """Verify calculation of risk scores and classifications."""
    # Success event
    score_success, level_success = business_risk_engine.compute_record_risk(
        domain_category="core_logic",
        execution_status="success",
        latency_ms=120.0,
    )
    assert level_success == "LOW"
    assert score_success <= 20.0

    # High latency warning
    score_warn, level_warn = business_risk_engine.compute_record_risk(
        domain_category="third_party_failure",
        execution_status="warning",
        latency_ms=9000.0,
    )
    assert level_warn == "MEDIUM"

    # Core logic failure
    score_fail, level_fail = business_risk_engine.compute_record_risk(
        domain_category="core_logic",
        execution_status="failed",
        error_type="VectorStoreError",
    )
    assert level_fail in ("HIGH", "CRITICAL")
    assert score_fail >= 70.0


@pytest.mark.asyncio
async def test_audit_service_logging_and_tamper_chain(test_db: AsyncSession):
    """Verify audit record creation, SHA-256 tamper-evident chaining, and remarks update."""
    db = test_db
    # 1. Log an event
    rec1 = await audit_service.log_event(
        domain_category="core_logic",
        event_name="rag_semantic_search",
        execution_status="success",
        actor_username="alice",
        actor_role="user",
        latency_ms=95.0,
        metadata_payload={"top_k": 3, "query": "Test legal compliance"},
        compliance_remark="Clean search execution",
        db=db,
    )
    assert rec1.id is not None
    assert rec1.record_hash is not None
    assert len(rec1.record_hash) == 64

    # 2. Log subsequent event to test hash chaining
    rec2 = await audit_service.log_event(
        domain_category="third_party_failure",
        event_name="llm_timeout_exception",
        execution_status="failed",
        actor_username="system",
        error_type="TimeoutError",
        error_message="OpenAI timeout after 120s",
        db=db,
    )
    assert rec2.prev_record_hash == rec1.record_hash

    # 3. Verify cryptographic chain
    chain_verification = await audit_service.verify_chain_integrity(db=db)
    assert chain_verification["verified"] is True
    assert chain_verification["status"] == "VALID_CRYPTOGRAPHIC_CHAIN"

    # 4. Update compliance remark
    updated = await audit_service.update_compliance_remark(
        db=db,
        record_id=rec2.id,
        compliance_remark="Third-party timeout verified; fallbacks operated smoothly",
        compliance_status="REMEDIATED",
        admin_username="super_admin",
    )
    assert updated is not None
    assert updated.compliance_remark == "Third-party timeout verified; fallbacks operated smoothly"
    assert updated.compliance_status == "REMEDIATED"
    assert updated.remark_updated_by == "super_admin"


@pytest.mark.asyncio
async def test_audit_api_endpoints(client: AsyncClient, test_db: AsyncSession):
    """Verify FastAPI audit API endpoints for risk metrics, logs, backups, and exports."""
    # Seed baseline events in test database
    await audit_service.seed_initial_audit_events_if_empty(test_db)

    # 1. Risk dashboard
    resp = await client.get("/api/v1/audit/risk-dashboard?window_hours=24")
    assert resp.status_code == 200
    data = resp.json()
    assert "risk_index" in data
    assert "risk_level" in data
    assert "domain_breakdown" in data
    assert "fluctuations_1h_vs_24h" in data
    assert "recommendations" in data

    # 2. Query logs
    logs_resp = await client.get("/api/v1/audit/logs?limit=10")
    assert logs_resp.status_code == 200
    logs_data = logs_resp.json()
    assert "items" in logs_data
    assert "total" in logs_data
    assert len(logs_data["items"]) > 0

    first_record_id = logs_data["items"][0]["id"]

    # 3. Query single record
    single_resp = await client.get(f"/api/v1/audit/logs/{first_record_id}")
    assert single_resp.status_code == 200
    assert single_resp.json()["id"] == first_record_id

    # 4. Update compliance remark
    remark_resp = await client.patch(
        f"/api/v1/audit/logs/{first_record_id}/remark",
        json={
            "compliance_remark": "Audited during Q4 legal review by Super Admin",
            "compliance_status": "COMPLIANT",
        },
    )
    assert remark_resp.status_code == 200
    assert remark_resp.json()["record"]["compliance_status"] == "COMPLIANT"

    # 5. List and trigger backups
    backup_resp = await client.post(
        "/api/v1/audit/backup",
        json={"retention_days": 60, "compliance_remark": "Triggered via test suite"},
    )
    assert backup_resp.status_code == 201
    assert "backup" in backup_resp.json()

    list_backup_resp = await client.get("/api/v1/audit/backups")
    assert list_backup_resp.status_code == 200
    assert list_backup_resp.json()["total_backups"] >= 1

    # 6. Verify cryptographic chain
    verify_resp = await client.get("/api/v1/audit/verify-integrity")
    assert verify_resp.status_code == 200
    assert verify_resp.json()["verified"] is True

    # 7. Export audit logs as CSV
    export_csv = await client.get("/api/v1/audit/export?export_format=csv&limit=50")
    assert export_csv.status_code == 200
    assert "text/csv" in export_csv.headers["content-type"]
    assert "record_hash" in export_csv.text
