"""SQLAlchemy ORM model for subscription pricing plans and tier configurations."""

from datetime import datetime, timezone
from typing import Any, Dict, List
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class PricingPlan(Base):
    """Database model for dynamic subscription pricing tiers and plan quotas."""

    __tablename__ = "pricing_plans"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # starter, pro, enterprise
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    monthly_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    annual_price_per_month: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    inr_monthly_price: Mapped[float] = mapped_column(Float, default=0.0)
    inr_annual_monthly_price: Mapped[float] = mapped_column(Float, default=0.0)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    badge: Mapped[str] = mapped_column(String(50), default="")
    features: Mapped[List[str]] = mapped_column(JSON, default=list)
    limits: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
