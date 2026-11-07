"""SQLAlchemy model for enterprise audit trails, legal compliance records, and risk tracking."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy import DateTime, Float, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class AuditTrailRecord(Base):
    """Tamper-evident legal audit log record with risk scoring and compliance tracking."""

    __tablename__ = "audit_trail_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    # Actor identity
    actor_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    actor_username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    actor_role: Mapped[str] = mapped_column(String(50), default="system", index=True)
    actor_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    # Classification & domain
    # Categories: 'core_logic', 'new_logic', 'exception_handling', 'third_party_failure', 'security_auth', 'audit_lifecycle'
    domain_category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    event_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Execution telemetry
    # Status: 'success', 'warning', 'degraded', 'failed', 'critical'
    execution_status: Mapped[str] = mapped_column(String(30), default="success", index=True)
    # Risk Level: 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    risk_level: Mapped[str] = mapped_column(String(20), default="LOW", index=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0 to 100.0

    # Error details (PII and secrets redacted)
    error_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Contextual payload
    metadata_payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    # Legal & Compliance
    compliance_framework: Mapped[str] = mapped_column(String(60), default="ISO27001_SOC2_GDPR")
    # Compliance Status: 'COMPLIANT', 'REVIEW_REQUIRED', 'FLAGGED', 'REMEDIATED'
    compliance_status: Mapped[str] = mapped_column(String(40), default="COMPLIANT", index=True)
    compliance_remark: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    remark_updated_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    remark_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Cryptographic tamper-evidence chain (SHA-256)
    prev_record_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    record_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    def to_dict(self) -> Dict[str, Any]:
        """Convert record to JSON-serializable dictionary."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "actor_id": self.actor_id,
            "actor_username": self.actor_username,
            "actor_role": self.actor_role,
            "actor_ip": self.actor_ip,
            "domain_category": self.domain_category,
            "event_name": self.event_name,
            "execution_status": self.execution_status,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "latency_ms": self.latency_ms,
            "metadata_payload": self.metadata_payload,
            "compliance_framework": self.compliance_framework,
            "compliance_status": self.compliance_status,
            "compliance_remark": self.compliance_remark,
            "remark_updated_by": self.remark_updated_by,
            "remark_updated_at": self.remark_updated_at.isoformat() if self.remark_updated_at else None,
            "prev_record_hash": self.prev_record_hash,
            "record_hash": self.record_hash,
        }
