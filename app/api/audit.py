"""Enterprise Audit Trail, Legal Compliance & Business Risk API endpoints."""

import csv
from datetime import datetime
import io
import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_admin_or_staff
from app.database import get_db
from app.models.user import User
from app.services.audit_backup import audit_backup_manager
from app.services.audit_service import audit_service
from app.services.risk_engine import business_risk_engine

router = APIRouter(prefix="/audit", tags=["audit-compliance"])


class ComplianceRemarkUpdateRequest(BaseModel):
    """Payload to update compliance remarks and auditor status."""
    compliance_remark: str = Field(..., min_length=3, description="Up-to-date compliance or auditor remark")
    compliance_status: Optional[str] = Field(None, description="'COMPLIANT', 'REVIEW_REQUIRED', 'FLAGGED', 'REMEDIATED'")


class BackupTriggerRequest(BaseModel):
    """Payload to trigger an audit backup archive."""
    retention_days: Optional[int] = Field(90, ge=1, le=3650, description="Retention window in days")
    compliance_remark: Optional[str] = Field(None, description="Auditor memo associated with backup generation")


@router.get("/risk-dashboard", status_code=status.HTTP_200_OK)
async def get_risk_dashboard(
    window_hours: int = Query(24, ge=1, le=720, description="Time window in hours for fluctuation tracking"),
    current_user: User = Depends(require_admin_or_staff),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve aggregated business risk metrics, domain fluctuations, and recommendations for Super Admins."""
    metrics = await business_risk_engine.get_risk_dashboard_metrics(db, window_hours=window_hours)
    return metrics


@router.get("/logs", status_code=status.HTTP_200_OK)
async def get_audit_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    domain_category: Optional[str] = Query(None, description="Filter by domain (core_logic, new_logic, exception_handling, third_party_failure, security_auth)"),
    risk_level: Optional[str] = Query(None, description="Filter by risk level (LOW, MEDIUM, HIGH, CRITICAL)"),
    execution_status: Optional[str] = Query(None, description="Filter by execution status (success, warning, degraded, failed, critical)"),
    compliance_status: Optional[str] = Query(None, description="Filter by compliance status (COMPLIANT, REVIEW_REQUIRED, FLAGGED, REMEDIATED)"),
    search: Optional[str] = Query(None, description="Full-text search in event name, error message, actor, or remarks"),
    start_time: Optional[datetime] = Query(None, description="Start date ISO timestamp"),
    end_time: Optional[datetime] = Query(None, description="End date ISO timestamp"),
    current_user: User = Depends(require_admin_or_staff),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Query paginated and filtered audit trail records."""
    records, total = await audit_service.get_logs(
        db=db,
        skip=skip,
        limit=limit,
        domain_category=domain_category,
        risk_level=risk_level,
        execution_status=execution_status,
        compliance_status=compliance_status,
        search_query=search,
        start_time=start_time,
        end_time=end_time,
    )
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [r.to_dict() for r in records],
    }


@router.get("/logs/{record_id}", status_code=status.HTTP_200_OK)
async def get_single_audit_record(
    record_id: str,
    current_user: User = Depends(require_admin_or_staff),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve details and cryptographic hash of a single audit log event."""
    from sqlalchemy import select
    from app.models.audit_trail import AuditTrailRecord

    stmt = select(AuditTrailRecord).where(AuditTrailRecord.id == record_id)
    rec = (await db.execute(stmt)).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit record not found.")
    return rec.to_dict()


@router.patch("/logs/{record_id}/remark", status_code=status.HTTP_200_OK)
async def update_audit_compliance_remark(
    record_id: str,
    payload: ComplianceRemarkUpdateRequest,
    current_user: User = Depends(require_admin_or_staff),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Attach or update up-to-date compliance remarks, auditor notes, and compliance status."""
    updated = await audit_service.update_compliance_remark(
        db=db,
        record_id=record_id,
        compliance_remark=payload.compliance_remark,
        compliance_status=payload.compliance_status,
        admin_username=current_user.username or "admin",
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit record not found.")
    return {
        "success": True,
        "record": updated.to_dict(),
        "message": "Compliance remark updated successfully.",
    }


@router.post("/backup", status_code=status.HTTP_201_CREATED)
async def trigger_audit_backup(
    payload: BackupTriggerRequest = BackupTriggerRequest(),
    current_user: User = Depends(require_admin_or_staff),
) -> Dict[str, Any]:
    """Trigger an immediate compressed backup archive of current audit logs with SHA-256 manifest."""
    backup_entry = audit_backup_manager.create_backup(
        retention_days=payload.retention_days,
        operator_username=current_user.username or "admin",
        compliance_remark=payload.compliance_remark,
    )
    return {
        "success": True,
        "backup": backup_entry,
        "message": "Audit backup created and cryptographically registered.",
    }


@router.get("/backups", status_code=status.HTTP_200_OK)
async def list_audit_backups(
    current_user: User = Depends(require_admin_or_staff),
) -> Dict[str, Any]:
    """List all legal backup archives with live on-disk cryptographic integrity validation."""
    archives = audit_backup_manager.list_backups()
    return {
        "total_backups": len(archives),
        "backups": archives,
    }


@router.get("/verify-integrity", status_code=status.HTTP_200_OK)
async def verify_audit_trail_chain(
    limit: int = Query(200, ge=1, le=1000),
    current_user: User = Depends(require_admin_or_staff),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Cryptographically verify the SHA-256 hash chaining of audit records for non-repudiation."""
    verification = await audit_service.verify_chain_integrity(db=db, limit=limit)
    return verification


@router.get("/export", status_code=status.HTTP_200_OK)
async def export_audit_logs(
    export_format: str = Query("json", regex="^(json|csv)$", description="Format: 'json' or 'csv'"),
    limit: int = Query(500, ge=1, le=5000),
    domain_category: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    current_user: User = Depends(require_admin_or_staff),
    db: AsyncSession = Depends(get_db),
):
    """Export audit records for legal preservation or external regulatory compliance reviews."""
    records, _ = await audit_service.get_logs(
        db=db,
        skip=0,
        limit=limit,
        domain_category=domain_category,
        risk_level=risk_level,
    )
    data = [r.to_dict() for r in records]

    if export_format == "csv":
        output = io.StringIO()
        fieldnames = [
            "id", "timestamp", "actor_username", "actor_role", "actor_ip",
            "domain_category", "event_name", "execution_status", "risk_level",
            "risk_score", "error_type", "compliance_status", "compliance_remark", "record_hash"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in data:
            writer.writerow(row)

        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=audit_export_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.csv"},
        )

    return Response(
        content=json.dumps(data, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=audit_export_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.json"},
    )
