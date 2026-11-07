"""Pydantic schemas for Organizations, Invites, and Subscription Checkout."""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class InviteCreateRequest(BaseModel):
    """Payload to create an admin invitation link."""
    assigned_role: str = Field("staff", description="Assigned role: 'staff', 'admin', or 'user'")
    email: Optional[str] = Field(None, description="Optional target email address to bind the invite")
    expires_in_days: int = Field(7, ge=1, le=90, description="Validity period in days")

    @field_validator("assigned_role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        role = v.strip().lower()
        if role in ("staffs", "staff"):
            return "staff"
        if role not in ("user", "staff", "admin"):
            raise ValueError("Role must be 'user', 'staff', or 'admin'.")
        return role

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        cleaned = v.strip().lower()
        if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", cleaned):
            raise ValueError("Invalid target email address format.")
        return cleaned


class InviteResponse(BaseModel):
    """Details of an invitation link."""
    id: str
    token: str
    invite_url: str
    assigned_role: str
    email: Optional[str] = None
    organization_id: Optional[str] = None
    organization_name: Optional[str] = None
    expires_at: datetime
    is_used: bool
    used_by_user_id: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InviteVerifyResponse(BaseModel):
    """Public details returned when verifying an invite token."""
    valid: bool
    token: str
    assigned_role: str
    email: Optional[str] = None
    organization_name: Optional[str] = None
    expires_at: datetime


class OrganizationResponse(BaseModel):
    """Organization details."""
    id: str
    name: str
    slug: str
    owner_id: str
    plan_tier: str
    billing_cycle: str
    subscription_status: str
    max_seats: int
    member_count: int = 1
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlanTierResponse(BaseModel):
    """Pricing plan details."""
    id: str
    name: str
    monthly_price: float
    annual_price_per_month: float
    description: str
    badge: Optional[str] = None
    features: List[str]
    limits: Dict[str, Any]


class RazorpayOrderCreateRequest(BaseModel):
    """Payload to initiate a Razorpay order without capturing or sending any sensitive card credentials."""
    plan_id: str = Field(..., description="Target plan tier ('starter', 'pro', 'enterprise')")
    billing_cycle: str = Field("monthly", description="'monthly' or 'annual'")
    billing_name: Optional[str] = Field(None, min_length=2, max_length=150)
    billing_email: Optional[str] = None

    @field_validator("plan_id")
    @classmethod
    def validate_plan_id(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if cleaned not in ("starter", "pro", "enterprise"):
            raise ValueError("Invalid plan. Choose 'starter', 'pro', or 'enterprise'.")
        return cleaned

    @field_validator("billing_cycle")
    @classmethod
    def validate_billing_cycle(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if cleaned not in ("monthly", "annual"):
            raise ValueError("Billing cycle must be 'monthly' or 'annual'.")
        return cleaned

    @field_validator("billing_email")
    @classmethod
    def validate_billing_email(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        cleaned = v.strip().lower()
        if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", cleaned):
            raise ValueError("Invalid billing email address.")
        return cleaned


class RazorpayOrderResponse(BaseModel):
    """Razorpay order initialization response for client checkout."""
    order_id: str
    amount: float
    amount_paise: int
    currency: str
    key_id: str
    plan_id: str
    plan_name: str
    billing_cycle: str
    billing_name: str
    billing_email: str
    organization_id: Optional[str] = None


class RazorpayPaymentVerifyRequest(BaseModel):
    """Payload verifying Razorpay payment signature without passing any payment credentials."""
    razorpay_order_id: str = Field(..., min_length=5, description="Razorpay Order ID")
    razorpay_payment_id: str = Field(..., min_length=5, description="Razorpay Payment ID")
    razorpay_signature: str = Field(..., min_length=10, description="Cryptographic HMAC SHA256 Signature")


class RazorpayPaymentVerifyResponse(BaseModel):
    """Verified payment confirmation response."""
    success: bool
    order_id: str
    transaction_id: str
    plan_id: str
    plan_name: str
    amount: float
    currency: str
    payment_status: str
    message: str
    organization_id: Optional[str] = None


class CheckoutRequest(BaseModel):
    """Payload for subscription payment checkout (supports both direct and gateway flows)."""
    plan_id: str = Field(..., description="Target plan ID ('starter', 'pro', 'enterprise')")
    billing_cycle: str = Field("monthly", description="'monthly' or 'annual'")
    billing_name: str = Field(..., min_length=2, max_length=150)
    billing_email: str = Field(...)
    card_number: Optional[str] = Field(None, description="Optional legacy test card number (never stored in DB)")
    card_exp: Optional[str] = Field(None, description="Optional expiration MM/YY")
    card_cvv: Optional[str] = Field(None, min_length=3, max_length=4)

    @field_validator("plan_id")
    @classmethod
    def validate_plan_id(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if cleaned not in ("starter", "pro", "enterprise"):
            raise ValueError("Invalid plan. Choose 'starter', 'pro', or 'enterprise'.")
        return cleaned

    @field_validator("billing_cycle")
    @classmethod
    def validate_billing_cycle(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if cleaned not in ("monthly", "annual"):
            raise ValueError("Billing cycle must be 'monthly' or 'annual'.")
        return cleaned

    @field_validator("billing_name")
    @classmethod
    def validate_billing_name(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 2:
            raise ValueError("Cardholder name must be at least 2 characters.")
        return cleaned

    @field_validator("billing_email")
    @classmethod
    def validate_billing_email(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", cleaned):
            raise ValueError("Invalid billing email address.")
        return cleaned


class CheckoutResponse(BaseModel):
    """Payment checkout receipt response."""
    success: bool
    order_id: str
    transaction_id: str
    plan_id: str
    plan_name: str
    amount_usd: float
    billing_cycle: str
    card_last4: Optional[str] = None
    message: str
    organization_id: Optional[str] = None


# -----------------------------------------------------------------------------
# Mandates & Transparency Invoices Schemas
# -----------------------------------------------------------------------------

class MandateCreateRequest(BaseModel):
    """Payload to create a recurring Razorpay mandate for a plan purchase.
    
    Mandates are executed on a strict monthly recurring auto-debit basis.
    """
    plan_id: str = Field(..., description="Target plan tier ('starter', 'pro', 'enterprise')")
    billing_cycle: str = Field("monthly", description="Mandates operate strictly on a monthly recurring basis.")
    billing_name: Optional[str] = Field(None, min_length=2, max_length=150)
    billing_email: Optional[str] = None
    total_count: Optional[int] = Field(12, description="Total monthly billing cycles (default 12 months)")
    immediate_charge: Optional[bool] = Field(True, description="Charge initial monthly cycle immediately")

    @field_validator("plan_id")
    @classmethod
    def validate_plan_id(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if cleaned not in ("starter", "pro", "enterprise"):
            raise ValueError("Invalid plan. Choose 'starter', 'pro', or 'enterprise'.")
        return cleaned

    @field_validator("billing_cycle")
    @classmethod
    def validate_billing_cycle(cls, v: str) -> str:
        # Mandates strictly operate on a monthly basis, not yearly
        return "monthly"


class MandateCreateResponse(BaseModel):
    """Response returned when initiating a Razorpay subscription mandate."""
    subscription_id: str
    order_id: Optional[str] = None
    plan_id: str
    plan_name: str
    amount: float
    amount_paise: int
    currency: str
    key_id: str
    billing_cycle: str
    billing_name: str
    billing_email: str
    is_mandate: bool = True
    organization_id: Optional[str] = None


class MandateVerifyRequest(BaseModel):
    """Payload verifying Razorpay subscription / mandate authorization."""
    razorpay_payment_id: str = Field(..., min_length=5, description="Razorpay Payment ID")
    razorpay_subscription_id: str = Field(..., min_length=5, description="Razorpay Subscription / Mandate ID")
    razorpay_signature: str = Field(..., min_length=10, description="Cryptographic HMAC SHA256 Signature")


class MandateVerifyResponse(BaseModel):
    """Response returned upon successful mandate authorization and invoice generation."""
    success: bool
    subscription_id: str
    mandate_status: str
    transaction_id: str
    plan_id: str
    plan_name: str
    invoice_id: str
    invoice_number: str
    amount: float
    currency: str
    message: str
    organization_id: Optional[str] = None


class InvoiceResponse(BaseModel):
    """Detailed invoice receipt representing a transparently recorded mandate transaction."""
    id: str
    invoice_number: str
    organization_id: Optional[str] = None
    razorpay_invoice_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    razorpay_subscription_id: Optional[str] = None
    plan_id: str
    plan_name: str
    billing_cycle: str
    amount: float
    currency: str
    status: str
    billing_name: str
    billing_email: str
    paid_at: Optional[datetime] = None
    invoice_pdf_url: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MandateStatusResponse(BaseModel):
    """Current organization mandate status and recurring billing schedule."""
    has_active_mandate: bool
    mandate_id: Optional[str] = None
    mandate_status: str
    plan_tier: str
    billing_cycle: str
    next_charge_at: Optional[datetime] = None
    mandate_next_charge_at: Optional[datetime] = None
    invoices_count: int = 0
    latest_invoice: Optional[InvoiceResponse] = None


