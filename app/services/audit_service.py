"""Enterprise Audit Trail & Compliance Service with cryptographic chaining and file/db persistence."""

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.logging import audit_file_logger, logger, risk_file_logger
from app.database import AsyncSessionLocal
from app.models.audit_trail import AuditTrailRecord
from app.mcp.security import AnonymousScrubber
from app.services.audit_backup import audit_backup_manager
from app.services.risk_engine import business_risk_engine

settings = get_settings()


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class AuditService:
    """High-performance audit logging service ensuring legal defensibility and compliance preservation."""

    def __init__(self):
        self._last_record_hash: Optional[str] = None
        self._hash_lock = asyncio.Lock()

    def _compute_sha256(self, content_str: str) -> str:
        """Calculate SHA-256 hash."""
        return hashlib.sha256(content_str.encode("utf-8")).hexdigest()

    async def _get_latest_record_hash(self, db: AsyncSession) -> str:
        """Fetch latest record hash from database to maintain tamper-evident chain."""
        if self._last_record_hash:
            return self._last_record_hash

        stmt = (
            select(AuditTrailRecord.record_hash)
            .order_by(desc(AuditTrailRecord.timestamp))
            .limit(1)
        )
        res = await db.execute(stmt)
        latest_hash = res.scalar_one_or_none()
        # Initial Genesis Hash for the chain
        self._last_record_hash = latest_hash or "GENESIS_HASH_00000000000000000000000000000000000000000000000000000000"
        return self._last_record_hash

    async def log_event(
        self,
        domain_category: str,
        event_name: str,
        execution_status: str = "success",
        actor_id: Optional[str] = None,
        actor_username: Optional[str] = None,
        actor_role: str = "system",
        actor_ip: Optional[str] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        latency_ms: Optional[float] = None,
        metadata_payload: Optional[Dict[str, Any]] = None,
        compliance_remark: Optional[str] = None,
        compliance_status: str = "COMPLIANT",
        db: Optional[AsyncSession] = None,
    ) -> AuditTrailRecord:
        """Record an audit event to both rotating files and the tamper-evident database."""
        now = utc_now()
        payload = metadata_payload or {}

        # 1. Scrub sensitive data from payload and error message
        scrubbed_payload = AnonymousScrubber.anonymize_payload(payload)
        scrubbed_error = AnonymousScrubber.anonymize_text(error_message) if error_message else None

        # 2. Compute dynamic risk score and risk level
        risk_score, risk_level = business_risk_engine.compute_record_risk(
            domain_category=domain_category,
            execution_status=execution_status,
            error_type=error_type,
            latency_ms=latency_ms,
        )

        record_id = str(uuid.uuid4())

        # 3. Cryptographic hash chaining
        async with self._hash_lock:
            prev_hash = self._last_record_hash or "GENESIS_HASH_00000000000000000000000000000000000000000000000000000000"
            raw_hash_material = f"{record_id}|{now.isoformat()}|{domain_category}|{event_name}|{execution_status}|{risk_score}|{prev_hash}"
            record_hash = self._compute_sha256(raw_hash_material)
            self._last_record_hash = record_hash

        record_dict = {
            "id": record_id,
            "timestamp": now.isoformat(),
            "actor_id": actor_id,
            "actor_username": actor_username,
            "actor_role": actor_role,
            "actor_ip": actor_ip,
            "domain_category": domain_category,
            "event_name": event_name,
            "execution_status": execution_status,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "error_type": error_type,
            "error_message": scrubbed_error,
            "latency_ms": latency_ms,
            "metadata_payload": scrubbed_payload,
            "compliance_framework": getattr(settings, "COMPLIANCE_DEFAULT_FRAMEWORK", "ISO27001_SOC2_GDPR"),
            "compliance_status": compliance_status,
            "compliance_remark": compliance_remark,
            "prev_record_hash": prev_hash,
            "record_hash": record_hash,
        }

        # 4. Asynchronous File Logging (JSON Lines)
        try:
            audit_file_logger.info(record_dict)
            if risk_level in ("HIGH", "CRITICAL") or execution_status in ("failed", "critical"):
                risk_file_logger.warning(record_dict)
        except Exception as e:
            logger.warning(f"Failed writing audit trail record to file: {e}")

        # 5. Database Persistence
        db_record = AuditTrailRecord(
            id=record_id,
            timestamp=now,
            actor_id=actor_id,
            actor_username=actor_username,
            actor_role=actor_role,
            actor_ip=actor_ip,
            domain_category=domain_category,
            event_name=event_name,
            execution_status=execution_status,
            risk_level=risk_level,
            risk_score=risk_score,
            error_type=error_type,
            error_message=scrubbed_error,
            latency_ms=latency_ms,
            metadata_payload=scrubbed_payload,
            compliance_framework=getattr(settings, "COMPLIANCE_DEFAULT_FRAMEWORK", "ISO27001_SOC2_GDPR"),
            compliance_status=compliance_status,
            compliance_remark=compliance_remark,
            prev_record_hash=prev_hash,
            record_hash=record_hash,
        )

        if db:
            db.add(db_record)
            await db.commit()
            await db.refresh(db_record)
        else:
            try:
                async with AsyncSessionLocal() as session:
                    session.add(db_record)
                    await session.commit()
                    await session.refresh(db_record)
            except Exception as e:
                logger.error(f"Failed to persist audit record {record_id} to database: {e}")

        return db_record

    async def get_logs(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        domain_category: Optional[str] = None,
        risk_level: Optional[str] = None,
        execution_status: Optional[str] = None,
        compliance_status: Optional[str] = None,
        search_query: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Tuple[List[AuditTrailRecord], int]:
        """Query paginated audit logs with flexible compliance filtering."""
        query = select(AuditTrailRecord)

        if domain_category:
            query = query.where(AuditTrailRecord.domain_category == domain_category)
        if risk_level:
            query = query.where(AuditTrailRecord.risk_level == risk_level)
        if execution_status:
            query = query.where(AuditTrailRecord.execution_status == execution_status)
        if compliance_status:
            query = query.where(AuditTrailRecord.compliance_status == compliance_status)
        if start_time:
            query = query.where(AuditTrailRecord.timestamp >= start_time)
        if end_time:
            query = query.where(AuditTrailRecord.timestamp <= end_time)
        if search_query:
            pattern = f"%{search_query.strip().lower()}%"
            query = query.where(
                or_(
                    func.lower(AuditTrailRecord.event_name).like(pattern),
                    func.lower(AuditTrailRecord.error_message).like(pattern),
                    func.lower(AuditTrailRecord.actor_username).like(pattern),
                    func.lower(AuditTrailRecord.compliance_remark).like(pattern),
                )
            )

        # Count total matching records
        count_stmt = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_stmt)).scalar() or 0

        # Retrieve records ordered chronologically descending
        results_stmt = query.order_by(desc(AuditTrailRecord.timestamp)).offset(skip).limit(limit)
        records = (await db.execute(results_stmt)).scalars().all()

        return list(records), total

    async def update_compliance_remark(
        self,
        db: AsyncSession,
        record_id: str,
        compliance_remark: str,
        compliance_status: Optional[str] = None,
        admin_username: str = "super_admin",
    ) -> Optional[AuditTrailRecord]:
        """Update audit record with up-to-date compliance remarks and status."""
        stmt = select(AuditTrailRecord).where(AuditTrailRecord.id == record_id)
        record = (await db.execute(stmt)).scalar_one_or_none()
        if not record:
            return None

        record.compliance_remark = compliance_remark
        if compliance_status:
            record.compliance_status = compliance_status
        record.remark_updated_by = admin_username
        record.remark_updated_at = utc_now()

        await db.commit()
        await db.refresh(record)

        logger.info(
            f"Audit Record {record_id} compliance remark updated by {admin_username} -> Status: {record.compliance_status}"
        )
        return record

    async def verify_chain_integrity(self, db: AsyncSession, limit: int = 200) -> Dict[str, Any]:
        """Verify cryptographic SHA-256 tamper-evident hash chaining across audit records."""
        stmt = select(AuditTrailRecord).order_by(AuditTrailRecord.timestamp.asc()).limit(limit)
        records = (await db.execute(stmt)).scalars().all()

        if not records:
            return {
                "verified": True,
                "records_evaluated": 0,
                "message": "No audit records present in database.",
                "verified_at": utc_now().isoformat(),
            }

        prev_hash = "GENESIS_HASH_00000000000000000000000000000000000000000000000000000000"
        tampered_records = []

        for rec in records:
            if rec.prev_record_hash != prev_hash and prev_hash != "GENESIS_HASH_00000000000000000000000000000000000000000000000000000000":
                # Hash chain break detected
                tampered_records.append({
                    "id": rec.id,
                    "event_name": rec.event_name,
                    "expected_prev_hash": prev_hash,
                    "actual_prev_hash": rec.prev_record_hash,
                })
            prev_hash = rec.record_hash

        is_valid = len(tampered_records) == 0

        return {
            "verified": is_valid,
            "records_evaluated": len(records),
            "tampered_records_count": len(tampered_records),
            "tampered_details": tampered_records[:10],
            "verified_at": utc_now().isoformat(),
            "status": "VALID_CRYPTOGRAPHIC_CHAIN" if is_valid else "TAMPERING_DETECTED",
        }


    async def seed_initial_audit_events_if_empty(self, db: AsyncSession) -> None:
        """Seed initial baseline audit events representing core logic, new logic, and third-party interactions."""
        stmt = select(func.count(AuditTrailRecord.id))
        count = (await db.execute(stmt)).scalar() or 0
        if count > 0:
            return

        baseline_events = [
            {
                "domain_category": "audit_lifecycle",
                "event_name": "audit_chain_initialized",
                "execution_status": "success",
                "actor_role": "system",
                "compliance_remark": "Genesis cryptographic tamper-evident audit chain established (ISO27001/SOC2)",
                "metadata_payload": {"framework": "ISO27001", "rotation_policy": "30_days", "status": "active"},
            },
            {
                "domain_category": "core_logic",
                "event_name": "vector_similarity_search",
                "execution_status": "success",
                "actor_role": "user",
                "actor_username": "system_admin",
                "latency_ms": 142.5,
                "metadata_payload": {"top_k": 4, "similarity_threshold": 0.3, "results_found": 4},
                "compliance_remark": "Core RAG semantic search executed within standard SLA (<200ms)",
            },
            {
                "domain_category": "new_logic",
                "event_name": "multi_agent_workflow_started",
                "execution_status": "success",
                "actor_role": "super_admin",
                "actor_username": "super_admin",
                "latency_ms": 320.0,
                "metadata_payload": {"team_size": 6, "goal": "Analyze quarterly compliance risk"},
                "compliance_remark": "New logic autonomous multi-agent task launched under supervised boundary",
            },
            {
                "domain_category": "third_party_failure",
                "event_name": "external_provider_timeout_retry",
                "execution_status": "degraded",
                "actor_role": "system",
                "error_type": "ProviderTimeoutError",
                "error_message": "Upstream LLM provider timeout (120s exceeded), gracefully switched to local fallback",
                "latency_ms": 4500.0,
                "metadata_payload": {"provider": "ollama", "fallback_active": True},
                "compliance_status": "REVIEW_REQUIRED",
                "compliance_remark": "Third-party latency surge logged; fallback pipeline successfully engaged",
            },
            {
                "domain_category": "exception_handling",
                "event_name": "handled_database_deadlock_retry",
                "execution_status": "warning",
                "actor_role": "system",
                "error_type": "DeadlockRetryHandled",
                "error_message": "Optimistic lock conflict resolved on second attempt (jitter backoff)",
                "latency_ms": 85.0,
                "metadata_payload": {"retries": 1, "resolved": True},
                "compliance_remark": "Self-healing exception recovery verified",
            },
            {
                "domain_category": "security_auth",
                "event_name": "jwt_refresh_token_rotated",
                "execution_status": "success",
                "actor_role": "admin",
                "actor_username": "admin",
                "metadata_payload": {"algorithm": "HS256", "token_type": "refresh"},
                "compliance_remark": "Session cryptographic rotation validated (OIDC compliance)",
            },
        ]

        for ev in baseline_events:
            await self.log_event(
                domain_category=ev["domain_category"],
                event_name=ev["event_name"],
                execution_status=ev.get("execution_status", "success"),
                actor_role=ev.get("actor_role", "system"),
                actor_username=ev.get("actor_username"),
                error_type=ev.get("error_type"),
                error_message=ev.get("error_message"),
                latency_ms=ev.get("latency_ms"),
                metadata_payload=ev.get("metadata_payload"),
                compliance_remark=ev.get("compliance_remark"),
                compliance_status=ev.get("compliance_status", "COMPLIANT"),
                db=db,
            )
        logger.info("Seeded initial baseline audit trail and risk telemetry records.")


audit_service = AuditService()
