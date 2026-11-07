"""Business Risk & Fluctuation Engine for telemetry, third-party failure tracking, and risk visualization."""

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_trail import AuditTrailRecord


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class BusinessRiskEngine:
    """Calculates real-time business risk scores and failure fluctuations across core, new logic, and external services."""

    # Weights for business risk calculation (out of 100)
    WEIGHT_CORE_LOGIC = 35.0
    WEIGHT_THIRD_PARTY = 30.0
    WEIGHT_EXCEPTIONS = 20.0
    WEIGHT_NEW_LOGIC = 15.0

    @classmethod
    def compute_record_risk(
        cls,
        domain_category: str,
        execution_status: str,
        error_type: Optional[str] = None,
        latency_ms: Optional[float] = None,
    ) -> tuple[float, str]:
        """Compute instantaneous risk score (0-100) and risk level for a single audit event."""
        score = 0.0

        if execution_status in ("success", "completed"):
            score = 5.0
            if latency_ms and latency_ms > 8000:
                score += 15.0  # High latency degradation penalty
        elif execution_status == "warning":
            score = 25.0
        elif execution_status == "degraded":
            score = 45.0
        elif execution_status in ("failed", "error"):
            if domain_category == "core_logic":
                score = 75.0
            elif domain_category == "third_party_failure":
                score = 65.0
            elif domain_category == "exception_handling":
                score = 70.0
            elif domain_category == "security_auth":
                score = 60.0
            else:
                score = 40.0
        elif execution_status in ("critical", "fatal"):
            score = 95.0

        # Classify risk level
        if score < 25.0:
            level = "LOW"
        elif score < 50.0:
            level = "MEDIUM"
        elif score < 75.0:
            level = "HIGH"
        else:
            level = "CRITICAL"

        return min(round(score, 1), 100.0), level

    @classmethod
    async def get_risk_dashboard_metrics(
        cls,
        db: AsyncSession,
        window_hours: int = 24,
    ) -> Dict[str, Any]:
        """Aggregate audit logs to calculate business risk indices, domain fluctuations, and third-party health."""
        now = utc_now()
        since_window = now - timedelta(hours=window_hours)
        since_1h = now - timedelta(hours=1)

        # 1. Total event counts in window
        total_stmt = select(func.count(AuditTrailRecord.id)).where(AuditTrailRecord.timestamp >= since_window)
        total_count = (await db.execute(total_stmt)).scalar() or 0

        # 2. Domain breakdown and failures in window
        domain_stats_stmt = (
            select(
                AuditTrailRecord.domain_category,
                func.count(AuditTrailRecord.id).label("total"),
                func.sum(
                    case(
                        (AuditTrailRecord.execution_status.in_(["failed", "critical", "degraded"]), 1),
                        else_=0,
                    )
                ).label("failures"),
                func.avg(AuditTrailRecord.risk_score).label("avg_risk"),
            )
            .where(AuditTrailRecord.timestamp >= since_window)
            .group_by(AuditTrailRecord.domain_category)
        )
        domain_rows = (await db.execute(domain_stats_stmt)).all()

        domain_data: Dict[str, Dict[str, Any]] = {
            "core_logic": {"total": 0, "failures": 0, "failure_rate": 0.0, "avg_risk": 0.0},
            "new_logic": {"total": 0, "failures": 0, "failure_rate": 0.0, "avg_risk": 0.0},
            "third_party_failure": {"total": 0, "failures": 0, "failure_rate": 0.0, "avg_risk": 0.0},
            "exception_handling": {"total": 0, "failures": 0, "failure_rate": 0.0, "avg_risk": 0.0},
            "security_auth": {"total": 0, "failures": 0, "failure_rate": 0.0, "avg_risk": 0.0},
            "audit_lifecycle": {"total": 0, "failures": 0, "failure_rate": 0.0, "avg_risk": 0.0},
        }

        for cat, count, fails, avg_risk in domain_rows:
            if cat in domain_data:
                cnt = count or 0
                fls = fails or 0
                rate = round((fls / cnt * 100), 2) if cnt > 0 else 0.0
                domain_data[cat] = {
                    "total": cnt,
                    "failures": fls,
                    "failure_rate": rate,
                    "avg_risk": round(float(avg_risk or 0.0), 1),
                }

        # 3. Fluctuation analysis: Compare last 1 hour vs 24 hours baseline
        stats_1h_stmt = (
            select(
                AuditTrailRecord.domain_category,
                func.count(AuditTrailRecord.id).label("total"),
                func.sum(
                    case(
                        (AuditTrailRecord.execution_status.in_(["failed", "critical", "degraded"]), 1),
                        else_=0,
                    )
                ).label("failures"),
            )
            .where(AuditTrailRecord.timestamp >= since_1h)
            .group_by(AuditTrailRecord.domain_category)
        )
        stats_1h_rows = (await db.execute(stats_1h_stmt)).all()
        stats_1h: Dict[str, float] = {}
        for cat, count, fails in stats_1h_rows:
            cnt = count or 0
            fls = fails or 0
            stats_1h[cat] = round((fls / cnt * 100), 2) if cnt > 0 else 0.0

        # Compute fluctuation deltas (+/- %)
        fluctuations = {
            "core_logic_delta": round(stats_1h.get("core_logic", 0.0) - domain_data["core_logic"]["failure_rate"], 2),
            "new_logic_delta": round(stats_1h.get("new_logic", 0.0) - domain_data["new_logic"]["failure_rate"], 2),
            "third_party_delta": round(stats_1h.get("third_party_failure", 0.0) - domain_data["third_party_failure"]["failure_rate"], 2),
            "exceptions_delta": round(stats_1h.get("exception_handling", 0.0) - domain_data["exception_handling"]["failure_rate"], 2),
        }

        # 4. Composite Business Risk Score (0-100)
        # Factor 1: Core logic failure rate (up to 35)
        core_rate = domain_data["core_logic"]["failure_rate"] / 100.0
        core_score = min(core_rate * 2.5 * cls.WEIGHT_CORE_LOGIC, cls.WEIGHT_CORE_LOGIC)

        # Factor 2: Third party failure rate (up to 30)
        tp_rate = domain_data["third_party_failure"]["failure_rate"] / 100.0
        tp_score = min(tp_rate * 2.0 * cls.WEIGHT_THIRD_PARTY, cls.WEIGHT_THIRD_PARTY)

        # Factor 3: Exception handling rate (up to 20)
        exc_rate = domain_data["exception_handling"]["failure_rate"] / 100.0
        exc_score = min(exc_rate * 2.0 * cls.WEIGHT_EXCEPTIONS, cls.WEIGHT_EXCEPTIONS)

        # Factor 4: New logic instability (up to 15)
        new_rate = domain_data["new_logic"]["failure_rate"] / 100.0
        new_score = min(new_rate * 1.5 * cls.WEIGHT_NEW_LOGIC, cls.WEIGHT_NEW_LOGIC)

        # Baseline baseline operating load (5.0) + weighted components
        total_risk_score = round(min(5.0 + core_score + tp_score + exc_score + new_score, 100.0), 1)

        if total_risk_score < 25.0:
            risk_level = "LOW"
            risk_summary = "System operates within optimal compliance boundaries. Core and third-party dependencies stable."
        elif total_risk_score < 50.0:
            risk_level = "MEDIUM"
            risk_summary = "Noticeable fluctuations detected in new logic or third-party integrations. Monitoring advised."
        elif total_risk_score < 75.0:
            risk_level = "HIGH"
            risk_summary = "Elevated failure rates in core logic or critical third-party dependencies. Action required."
        else:
            risk_level = "CRITICAL"
            risk_summary = "Critical business risk! Severe degradation in core execution pipelines or security violations."

        # 5. Risk level counts in window
        risk_dist_stmt = (
            select(AuditTrailRecord.risk_level, func.count(AuditTrailRecord.id))
            .where(AuditTrailRecord.timestamp >= since_window)
            .group_by(AuditTrailRecord.risk_level)
        )
        risk_dist_rows = (await db.execute(risk_dist_stmt)).all()
        risk_distribution = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
        for lvl, cnt in risk_dist_rows:
            if lvl in risk_distribution:
                risk_distribution[lvl] = cnt

        # 6. Compliance status distribution
        comp_dist_stmt = (
            select(AuditTrailRecord.compliance_status, func.count(AuditTrailRecord.id))
            .where(AuditTrailRecord.timestamp >= since_window)
            .group_by(AuditTrailRecord.compliance_status)
        )
        comp_dist_rows = (await db.execute(comp_dist_stmt)).all()
        compliance_distribution = {
            "COMPLIANT": 0,
            "REVIEW_REQUIRED": 0,
            "FLAGGED": 0,
            "REMEDIATED": 0,
        }
        for st, cnt in comp_dist_rows:
            if st in compliance_distribution:
                compliance_distribution[st] = cnt

        # 7. Actionable Super Admin Recommendations
        recommendations = []
        if fluctuations["third_party_delta"] > 5.0 or domain_data["third_party_failure"]["failure_rate"] > 10.0:
            recommendations.append(
                f"Third-Party Failures spiked by {fluctuations['third_party_delta']}%. Check external LLM provider quotas, network latency, or MCP server connectivity."
            )
        if fluctuations["core_logic_delta"] > 3.0 or domain_data["core_logic"]["failure_rate"] > 5.0:
            recommendations.append(
                "Core logic degradation observed in RAG vector search or database indexing. Inspect database connection pool and vector store health."
            )
        if domain_data["exception_handling"]["failures"] > 5:
            recommendations.append(
                f"{domain_data['exception_handling']['failures']} unhandled exceptions logged in the last {window_hours}h. Review error stack traces in Audit Explorer."
            )
        if compliance_distribution["FLAGGED"] > 0 or compliance_distribution["REVIEW_REQUIRED"] > 0:
            recommendations.append(
                f"{compliance_distribution['FLAGGED'] + compliance_distribution['REVIEW_REQUIRED']} audit logs require Super Admin compliance remarks or review."
            )
        if not recommendations:
            recommendations.append("All core pipelines, third parties, and compliance checkpoints are operating normally.")

        return {
            "generated_at": now.isoformat(),
            "window_hours": window_hours,
            "total_events_logged": total_count,
            "risk_index": total_risk_score,
            "risk_level": risk_level,
            "risk_summary": risk_summary,
            "domain_breakdown": domain_data,
            "fluctuations_1h_vs_24h": fluctuations,
            "risk_distribution": risk_distribution,
            "compliance_distribution": compliance_distribution,
            "recommendations": recommendations,
        }


business_risk_engine = BusinessRiskEngine()
