"""SQLAlchemy models for Multi-Tenant Organizations, Invites, and Subscription Orders."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class Organization(Base):
    """Multi-tenant organization account model."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_tier: Mapped[str] = mapped_column(String(50), default="starter")  # starter, pro, enterprise
    billing_cycle: Mapped[str] = mapped_column(String(20), default="monthly")  # monthly, annual
    subscription_status: Mapped[str] = mapped_column(String(50), default="active")  # active, canceled
    max_seats: Mapped[int] = mapped_column(Integer, default=5)
    # Razorpay Recurring Mandate Fields
    mandate_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)  # sub_... or mandate token
    mandate_status: Mapped[str] = mapped_column(String(50), default="none")  # none, active, pending, paused, cancelled
    mandate_next_charge_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    members: Mapped[List["OrganizationMember"]] = relationship(
        "OrganizationMember",
        back_populates="organization",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    invites: Mapped[List["OrganizationInvite"]] = relationship(
        "OrganizationInvite",
        back_populates="organization",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    invoices: Mapped[List["Invoice"]] = relationship(
        "Invoice",
        back_populates="organization",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class OrganizationMember(Base):
    """Membership mapping users to organizations with role privileges."""

    __tablename__ = "organization_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(30), default="user")  # admin, staff, user
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="members")


class OrganizationInvite(Base):
    """Admin-generated invitation link for registering with a designated role."""

    __tablename__ = "organization_invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    organization_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    invited_by_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Optional target email constraint
    assigned_role: Mapped[str] = mapped_column(String(30), default="staff")  # staff, admin, user
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    used_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    organization: Mapped[Optional["Organization"]] = relationship("Organization", back_populates="invites")


class SubscriptionOrder(Base):
    """Persisted checkout orders and payment confirmation records.

    SECURITY NOTE:
    No card numbers, CVVs, expiration dates, or banking passwords/credentials
    are ever saved or stored in this system. Only secure, non-confidential
    payment gateway transaction references (Razorpay order ID, payment ID,
    signature, amount, and verification status) are recorded.
    """

    __tablename__ = "subscription_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(String(50), nullable=False)
    plan_name: Mapped[str] = mapped_column(String(100), nullable=False)
    billing_cycle: Mapped[str] = mapped_column(String(20), default="monthly")
    amount_usd: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    payment_method: Mapped[str] = mapped_column(String(50), default="razorpay")
    card_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    razorpay_order_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    razorpay_subscription_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    razorpay_signature: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    billing_name: Mapped[str] = mapped_column(String(150), nullable=False)
    billing_email: Mapped[str] = mapped_column(String(255), nullable=False)
    transaction_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, paid, failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Invoice(Base):
    """Persisted billing invoice records fetched from Razorpay mandate transactions.

    COMPLETE TRANSPARENCY:
    Every mandate transaction processed by Razorpay creates an immutable,
    auditable invoice in this table with the gateway payment reference,
    status, and line-item breakdown.
    """

    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    invoice_number: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)  # e.g. INV-2026-0001
    organization_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_order_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("subscription_orders.id", ondelete="SET NULL"), nullable=True, index=True)
    razorpay_invoice_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True, nullable=True)
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    razorpay_subscription_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    plan_id: Mapped[str] = mapped_column(String(50), nullable=False)
    plan_name: Mapped[str] = mapped_column(String(100), nullable=False)
    billing_cycle: Mapped[str] = mapped_column(String(20), default="monthly")
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    status: Mapped[str] = mapped_column(String(50), default="paid")  # paid, issued, pending, failed
    billing_name: Mapped[str] = mapped_column(String(150), nullable=False)
    billing_email: Mapped[str] = mapped_column(String(255), nullable=False)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=True)
    invoice_pdf_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    organization: Mapped[Optional["Organization"]] = relationship("Organization", back_populates="invoices")


