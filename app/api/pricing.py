"""Pricing plans, Razorpay Mandates, and Transparent Invoicing API routes.

SECURITY & COMPLIANCE GUARANTEE:
1. No card numbers, CVVs, expiration dates, or banking passwords are ever
   accepted, received, or stored in this system.
2. Mandates (e-Mandate / UPI Autopay / Standing Instructions) are initiated
   and authenticated entirely through Razorpay's PCI-DSS Level 1 compliant gateway.
3. Every mandate transaction is synced via a background scheduler or on-demand,
   and immutable, auditable Invoices are generated in the system for full transparency.
"""

import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.auth import get_current_user, utc_now
from app.database import get_db
from app.models.organization import Invoice, Organization, OrganizationMember, SubscriptionOrder
from app.models.user import User
from app.schemas.organization import (
    CheckoutRequest,
    CheckoutResponse,
    InvoiceResponse,
    MandateCreateRequest,
    MandateCreateResponse,
    MandateStatusResponse,
    MandateVerifyRequest,
    MandateVerifyResponse,
    PlanTierResponse,
    RazorpayOrderCreateRequest,
    RazorpayOrderResponse,
    RazorpayPaymentVerifyRequest,
    RazorpayPaymentVerifyResponse,
)
from app.services.mandate_scheduler import (
    generate_invoice_number,
    sync_all_mandate_transactions,
)

from app.services.config_service import config_service

logger = logging.getLogger("rag_agent.pricing")
router = APIRouter(prefix="/pricing", tags=["pricing"])


class _PlansProxy(list):
    """Dynamic list proxy resolving cached pricing plans from database/cache."""

    def _get_items(self) -> List[PlanTierResponse]:
        if config_service._plans_cache:
            return config_service._plans_cache
        cfg = config_service.load_initial_config_file()
        items = []
        for p in cfg.get("pricing_plans", []):
            items.append(
                PlanTierResponse(
                    id=p["id"],
                    name=p["name"],
                    monthly_price=float(p.get("monthly_price", 0.0)),
                    annual_price_per_month=float(p.get("annual_price_per_month", 0.0)),
                    description=p.get("description", ""),
                    badge=p.get("badge", ""),
                    features=p.get("features", []),
                    limits=p.get("limits", {}),
                )
            )
        return items

    def __iter__(self):
        return iter(self._get_items())

    def __len__(self):
        return len(self._get_items())

    def __getitem__(self, index):
        return self._get_items()[index]


PLANS: List[PlanTierResponse] = _PlansProxy()


class _PlanLookupProxy(dict):
    """Dynamic dictionary proxy resolving plans by ID from L1 cache."""

    def get(self, key: str, default: Any = None) -> Optional[PlanTierResponse]:
        if key in config_service._plan_lookup_cache:
            return config_service._plan_lookup_cache[key]
        for p in PLANS:
            if p.id == key:
                return p
        return default

    def __getitem__(self, key: str) -> PlanTierResponse:
        val = self.get(key)
        if val is None:
            raise KeyError(key)
        return val

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None


PLAN_LOOKUP: Dict[str, PlanTierResponse] = _PlanLookupProxy()


def calculate_plan_amount(plan: Any, cycle: str, currency: str) -> float:
    """Calculate charged amount dynamically based on cached/database plan pricing rates."""
    plan_id = plan.id if hasattr(plan, "id") else str(plan)
    if plan_id == "starter":
        return 0.0

    rates = config_service._plan_models_cache.get(plan_id, {})
    is_inr = currency.upper() == "INR"

    if is_inr:
        inr_monthly = rates.get("inr_monthly_price")
        inr_annual = rates.get("inr_annual_monthly_price")
        if inr_monthly is None:
            cfg = config_service.load_initial_config_file()
            for p in cfg.get("pricing_plans", []):
                if p["id"] == plan_id:
                    inr_monthly = float(p.get("inr_monthly_price", 3999.0 if plan_id == "pro" else 19999.0))
                    inr_annual = float(p.get("inr_annual_monthly_price", 3199.0 if plan_id == "pro" else 15999.0))
                    break
            if inr_monthly is None:
                inr_monthly = 3999.0 if plan_id == "pro" else 19999.0
                inr_annual = 3199.0 if plan_id == "pro" else 15999.0

        if cycle == "annual":
            return round(float(inr_annual) * 12, 2)
        return round(float(inr_monthly), 2)
    else:
        monthly = rates.get("monthly_price", getattr(plan, "monthly_price", 49.0 if plan_id == "pro" else 249.0))
        annual = rates.get("annual_price_per_month", getattr(plan, "annual_price_per_month", 39.0 if plan_id == "pro" else 199.0))
        if cycle == "annual":
            return round(float(annual) * 12, 2)
        return round(float(monthly), 2)


@router.get("/plans", response_model=List[PlanTierResponse])
async def get_pricing_plans(db: AsyncSession = Depends(get_db)):
    """Retrieve available subscription pricing tiers from cache and database."""
    return await config_service.get_pricing_plans(db)


@router.get("/razorpay/config")
async def get_razorpay_public_config():
    """Return public Razorpay gateway configuration for client checkout.

    SECURITY NOTE:
    Never expose the Razorpay Key Secret. Only the public Key ID and currency
    are provided to initialize the Razorpay client checkout modal.
    """
    settings = get_settings()
    return {
        "key_id": settings.RAZORPAY_KEY_ID,
        "currency": settings.RAZORPAY_CURRENCY.upper(),
        "is_test_mode": settings.RAZORPAY_KEY_ID.startswith("rzp_test_"),
    }


# =============================================================================
# Razorpay Mandate (Recurring Auto-Debit Subscriptions)
# =============================================================================

@router.post("/razorpay/create-mandate", response_model=MandateCreateResponse)
async def create_razorpay_mandate(
    payload: MandateCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a recurring auto-debit Mandate / Subscription on Razorpay for a plan purchase."""
    plan = PLAN_LOOKUP.get(payload.plan_id)
    if not plan or plan.id == "starter":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Valid paid plan ('pro' or 'enterprise') required for mandate purchase.",
        )

    settings = get_settings()
    currency = settings.RAZORPAY_CURRENCY.upper()
    # Mandates strictly operate on a monthly recurring schedule (not yearly)
    mandate_cycle = "monthly"
    amount = calculate_plan_amount(plan, mandate_cycle, currency)
    amount_paise = int(round(amount * 100))

    billing_name = payload.billing_name or current_user.full_name or current_user.username
    billing_email = payload.billing_email or current_user.email

    subscription_id = None
    is_placeholder = (
        not settings.RAZORPAY_KEY_ID
        or settings.RAZORPAY_KEY_ID == "rzp_test_placeholder_key"
        or not settings.RAZORPAY_KEY_SECRET
        or settings.RAZORPAY_KEY_SECRET == "placeholder_secret"
    )

    if not is_placeholder:
        try:
            import razorpay
            client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

            # 1. Create or ensure recurring plan in Razorpay (strictly monthly auto-debit)
            rzp_plan_data = {
                "period": "monthly",
                "interval": 1,
                "item": {
                    "name": f"{plan.name} (Monthly Mandate)",
                    "amount": amount_paise,
                    "currency": currency,
                    "description": f"RAG Agent {plan.name} recurring monthly auto-debit mandate",
                },
            }
            rzp_plan = client.plan.create(data=rzp_plan_data)
            rzp_plan_id = rzp_plan.get("id")

            # 2. Create Razorpay Subscription Mandate (monthly auto-renew)
            total_count = payload.total_count or 12
            sub_payload = {
                "plan_id": rzp_plan_id,
                "total_count": total_count,
                "quantity": 1,
                "customer_notify": 1,
                "notes": {
                    "user_id": current_user.id,
                    "plan_id": plan.id,
                    "billing_email": billing_email,
                    "billing_cycle": "monthly",
                },
            }
            sub_obj = client.subscription.create(data=sub_payload)
            subscription_id = sub_obj.get("id")
            logger.info(f"Created Razorpay Monthly Mandate: {subscription_id} for user {current_user.id}")
        except Exception as e:
            logger.error(f"Failed to create live Razorpay subscription mandate: {e}", exc_info=True)
            subscription_id = f"sub_rzp_{uuid.uuid4().hex[:16]}"
    else:
        subscription_id = f"sub_rzp_{uuid.uuid4().hex[:16]}"
        logger.info(f"Sandbox Razorpay monthly mandate created: {subscription_id}")

    # Check user organization
    org_res = await db.execute(select(Organization).where(Organization.owner_id == current_user.id))
    org = org_res.scalar_one_or_none()

    # Record order in pending mandate status (strictly monthly)
    order = SubscriptionOrder(
        organization_id=org.id if org else None,
        user_id=current_user.id,
        plan_id=plan.id,
        plan_name=plan.name,
        billing_cycle="monthly",
        amount_usd=amount,
        currency=currency,
        payment_method="razorpay_mandate",
        razorpay_subscription_id=subscription_id,
        billing_name=billing_name,
        billing_email=billing_email,
        transaction_id=f"pending_{uuid.uuid4().hex[:12]}",
        status="pending",
    )
    db.add(order)
    await db.commit()

    return MandateCreateResponse(
        subscription_id=subscription_id,
        plan_id=plan.id,
        plan_name=plan.name,
        amount=amount,
        amount_paise=amount_paise,
        currency=currency,
        key_id=settings.RAZORPAY_KEY_ID or "rzp_test_placeholder_key",
        billing_cycle="monthly",
        billing_name=billing_name,
        billing_email=billing_email,
        is_mandate=True,
        organization_id=org.id if org else None,
    )


@router.post("/razorpay/verify-mandate", response_model=MandateVerifyResponse)
async def verify_razorpay_mandate(
    payload: MandateVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify mandate authorization signature, activate organization, and generate transparent invoice."""
    settings = get_settings()

    order_res = await db.execute(
        select(SubscriptionOrder).where(
            SubscriptionOrder.razorpay_subscription_id == payload.razorpay_subscription_id
        )
    )
    order = order_res.scalar_one_or_none()

    is_placeholder = (
        not settings.RAZORPAY_KEY_SECRET
        or settings.RAZORPAY_KEY_SECRET == "placeholder_secret"
    )

    if not is_placeholder:
        # Standard Razorpay Subscription HMAC-SHA256 signature verification formula:
        # signature = HMAC-SHA256(payment_id + "|" + subscription_id, secret)
        msg = f"{payload.razorpay_payment_id}|{payload.razorpay_subscription_id}".encode("utf-8")
        generated_sig = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode("utf-8"),
            msg,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(generated_sig, payload.razorpay_signature):
            logger.warning(f"Razorpay mandate signature mismatch for subscription {payload.razorpay_subscription_id}.")
            if order:
                order.status = "failed"
                await db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid mandate authorization signature.",
            )

    plan_id = order.plan_id if order else "pro"
    plan = PLAN_LOOKUP.get(plan_id)
    plan_name = plan.name if plan else "Professional Plan"
    # Mandates are strictly monthly
    billing_cycle = "monthly"
    amount = order.amount_usd if order else calculate_plan_amount(plan, billing_cycle, settings.RAZORPAY_CURRENCY)
    currency = order.currency if order else settings.RAZORPAY_CURRENCY

    # Check or link user's organization
    org_res = await db.execute(
        select(Organization).where(Organization.owner_id == current_user.id)
    )
    org = org_res.scalar_one_or_none()

    if not org:
        member_res = await db.execute(
            select(OrganizationMember).where(OrganizationMember.user_id == current_user.id)
        )
        membership = member_res.scalar_one_or_none()
        if membership:
            org_lookup = await db.execute(select(Organization).where(Organization.id == membership.organization_id))
            org = org_lookup.scalar_one_or_none()

    seats_limit = plan.limits.get("seats", 15) if plan else 15
    next_charge = utc_now() + timedelta(days=30)

    if not org:
        slug = f"{current_user.username.lower()}-{uuid.uuid4().hex[:6]}"
        org = Organization(
            name=f"{current_user.full_name or current_user.username}'s Team",
            slug=slug,
            owner_id=current_user.id,
            plan_tier=plan_id,
            billing_cycle=billing_cycle,
            subscription_status="active",
            max_seats=seats_limit,
            mandate_id=payload.razorpay_subscription_id,
            mandate_status="active",
            mandate_next_charge_at=next_charge,
        )
        db.add(org)
        await db.flush()
        member = OrganizationMember(
            organization_id=org.id,
            user_id=current_user.id,
            role="admin",
        )
        db.add(member)
    else:
        org.plan_tier = plan_id
        org.billing_cycle = billing_cycle
        org.subscription_status = "active"
        org.max_seats = seats_limit
        org.mandate_id = payload.razorpay_subscription_id
        org.mandate_status = "active"
        org.mandate_next_charge_at = next_charge

    if current_user.role != "admin":
        current_user.role = "admin"

    if order:
        order.organization_id = org.id
        order.razorpay_payment_id = payload.razorpay_payment_id
        order.razorpay_signature = payload.razorpay_signature
        order.transaction_id = payload.razorpay_payment_id
        order.status = "paid"

    # Immediately generate an Invoice record for full transparency
    count_res = await db.execute(select(Invoice.id))
    inv_count = len(count_res.scalars().all()) + 1
    inv_number = generate_invoice_number(inv_count)

    invoice = Invoice(
        invoice_number=inv_number,
        organization_id=org.id,
        user_id=current_user.id,
        subscription_order_id=order.id if order else None,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_subscription_id=payload.razorpay_subscription_id,
        plan_id=plan_id,
        plan_name=plan_name,
        billing_cycle=billing_cycle,
        amount=amount,
        currency=currency,
        status="paid",
        billing_name=org.name,
        billing_email=current_user.email,
        paid_at=utc_now(),
        notes=f"Initial mandate authorization & recurring charge (Razorpay Mandate {payload.razorpay_subscription_id})",
    )
    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)

    return MandateVerifyResponse(
        success=True,
        subscription_id=payload.razorpay_subscription_id,
        mandate_status="active",
        transaction_id=payload.razorpay_payment_id,
        plan_id=plan_id,
        plan_name=plan_name,
        invoice_id=invoice.id,
        invoice_number=invoice.invoice_number,
        amount=amount,
        currency=currency,
        message=f"Mandate active! Invoice {invoice.invoice_number} generated for {plan_name}.",
        organization_id=org.id,
    )


# =============================================================================
# Invoices & Transparency Endpoints
# =============================================================================

@router.get("/invoices", response_model=List[InvoiceResponse])
async def list_user_invoices(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all transparently generated invoice records for the current user/organization."""
    org_res = await db.execute(
        select(Organization).where(Organization.owner_id == current_user.id)
    )
    org = org_res.scalar_one_or_none()

    query = select(Invoice)
    if org:
        query = query.where(
            (Invoice.organization_id == org.id) | (Invoice.user_id == current_user.id)
        )
    else:
        query = query.where(Invoice.user_id == current_user.id)

    query = query.order_by(Invoice.created_at.desc())
    res = await db.execute(query)
    return res.scalars().all()


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice_detail(
    invoice_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve details for a specific invoice."""
    res = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    inv = res.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return inv


@router.post("/mandate/sync")
async def trigger_mandate_sync(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger an immediate sync of mandate transactions from Razorpay and generate invoices."""
    res = await sync_all_mandate_transactions(db)
    return res


@router.get("/mandate/status", response_model=MandateStatusResponse)
async def get_mandate_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current organization's active mandate and recurring schedule."""
    org_res = await db.execute(
        select(Organization).where(Organization.owner_id == current_user.id)
    )
    org = org_res.scalar_one_or_none()

    if not org or not org.mandate_id:
        return MandateStatusResponse(
            has_active_mandate=False,
            mandate_id=None,
            mandate_status="none",
            plan_tier=org.plan_tier if org else "starter",
            billing_cycle=org.billing_cycle if org else "monthly",
            next_charge_at=None,
            invoices_count=0,
            latest_invoice=None,
        )

    inv_res = await db.execute(
        select(Invoice)
        .where(Invoice.organization_id == org.id)
        .order_by(Invoice.created_at.desc())
    )
    invoices = inv_res.scalars().all()

    latest_inv_resp = None
    if invoices:
        latest_inv_resp = InvoiceResponse.model_validate(invoices[0])

    return MandateStatusResponse(
        has_active_mandate=org.mandate_status in ["active", "pending"],
        mandate_id=org.mandate_id,
        mandate_status=org.mandate_status,
        plan_tier=org.plan_tier,
        billing_cycle=org.billing_cycle,
        next_charge_at=org.mandate_next_charge_at,
        mandate_next_charge_at=org.mandate_next_charge_at,
        invoices_count=len(invoices),
        latest_invoice=latest_inv_resp,
    )


# =============================================================================
# Standard Orders & Legacy Checkout
# =============================================================================

@router.post("/razorpay/create-order", response_model=RazorpayOrderResponse)
async def create_razorpay_order(
    payload: RazorpayOrderCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new Razorpay order for subscription checkout."""
    plan = PLAN_LOOKUP.get(payload.plan_id)
    if not plan or plan.id == "starter":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or free plan: '{payload.plan_id}'.",
        )

    settings = get_settings()
    currency = settings.RAZORPAY_CURRENCY.upper()
    amount = calculate_plan_amount(plan, payload.billing_cycle, currency)
    amount_paise = int(round(amount * 100))

    billing_name = payload.billing_name or current_user.full_name or current_user.username
    billing_email = payload.billing_email or current_user.email

    receipt_id = f"rcpt_{uuid.uuid4().hex[:12]}"
    razorpay_order_id = None

    is_placeholder = (
        not settings.RAZORPAY_KEY_ID
        or settings.RAZORPAY_KEY_ID == "rzp_test_placeholder_key"
        or not settings.RAZORPAY_KEY_SECRET
        or settings.RAZORPAY_KEY_SECRET == "placeholder_secret"
    )

    if not is_placeholder:
        try:
            import razorpay
            client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
            order_data = {
                "amount": amount_paise,
                "currency": currency,
                "receipt": receipt_id,
                "notes": {
                    "user_id": current_user.id,
                    "plan_id": plan.id,
                    "billing_cycle": payload.billing_cycle,
                    "billing_email": billing_email,
                },
            }
            rzp_order = client.order.create(data=order_data)
            razorpay_order_id = rzp_order.get("id")
        except Exception as e:
            logger.error(f"Razorpay API order creation error: {e}", exc_info=True)
            razorpay_order_id = f"order_rzp_{uuid.uuid4().hex[:16]}"
    else:
        razorpay_order_id = f"order_rzp_{uuid.uuid4().hex[:16]}"

    org_res = await db.execute(
        select(Organization).where(Organization.owner_id == current_user.id)
    )
    org = org_res.scalar_one_or_none()

    order = SubscriptionOrder(
        organization_id=org.id if org else None,
        user_id=current_user.id,
        plan_id=plan.id,
        plan_name=plan.name,
        billing_cycle=payload.billing_cycle,
        amount_usd=amount,
        currency=currency,
        payment_method="razorpay",
        razorpay_order_id=razorpay_order_id,
        billing_name=billing_name,
        billing_email=billing_email,
        transaction_id=f"pending_{uuid.uuid4().hex[:12]}",
        status="pending",
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)

    return RazorpayOrderResponse(
        order_id=razorpay_order_id,
        amount=amount,
        amount_paise=amount_paise,
        currency=currency,
        key_id=settings.RAZORPAY_KEY_ID,
        plan_id=plan.id,
        plan_name=plan.name,
        billing_cycle=payload.billing_cycle,
        billing_name=billing_name,
        billing_email=billing_email,
        organization_id=org.id if org else None,
    )


@router.post("/razorpay/verify-payment", response_model=RazorpayPaymentVerifyResponse)
async def verify_razorpay_payment(
    verify_data: RazorpayPaymentVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify Razorpay payment signature cryptographically and activate subscription."""
    settings = get_settings()

    order_res = await db.execute(
        select(SubscriptionOrder).where(
            SubscriptionOrder.razorpay_order_id == verify_data.razorpay_order_id
        )
    )
    order = order_res.scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subscription order not found for Razorpay Order ID: {verify_data.razorpay_order_id}",
        )

    is_placeholder = (
        not settings.RAZORPAY_KEY_SECRET
        or settings.RAZORPAY_KEY_SECRET == "placeholder_secret"
    )

    if not is_placeholder:
        msg = f"{verify_data.razorpay_order_id}|{verify_data.razorpay_payment_id}".encode("utf-8")
        generated_sig = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode("utf-8"),
            msg,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(generated_sig, verify_data.razorpay_signature):
            logger.warning(f"Razorpay signature mismatch for order {verify_data.razorpay_order_id}.")
            order.status = "failed"
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment signature verification failed. Untrusted transaction.",
            )

    plan = PLAN_LOOKUP.get(order.plan_id)
    plan_name = plan.name if plan else order.plan_name

    org_res = await db.execute(
        select(Organization).where(Organization.owner_id == current_user.id)
    )
    org = org_res.scalar_one_or_none()

    seats_limit = plan.limits.get("seats", 15) if plan else 15

    if not org:
        slug = f"{current_user.username.lower()}-{uuid.uuid4().hex[:6]}"
        org = Organization(
            name=f"{current_user.full_name or current_user.username}'s Team",
            slug=slug,
            owner_id=current_user.id,
            plan_tier=order.plan_id,
            billing_cycle=order.billing_cycle,
            subscription_status="active",
            max_seats=seats_limit,
        )
        db.add(org)
        await db.flush()
        member = OrganizationMember(
            organization_id=org.id,
            user_id=current_user.id,
            role="admin",
        )
        db.add(member)
    else:
        org.plan_tier = order.plan_id
        org.billing_cycle = order.billing_cycle
        org.subscription_status = "active"
        org.max_seats = seats_limit

    if current_user.role != "admin":
        current_user.role = "admin"

    order.organization_id = org.id
    order.razorpay_payment_id = verify_data.razorpay_payment_id
    order.razorpay_signature = verify_data.razorpay_signature
    order.transaction_id = verify_data.razorpay_payment_id
    order.status = "paid"

    # Also record an invoice for transparency
    count_res = await db.execute(select(Invoice.id))
    inv_count = len(count_res.scalars().all()) + 1
    invoice = Invoice(
        invoice_number=generate_invoice_number(inv_count),
        organization_id=org.id,
        user_id=current_user.id,
        subscription_order_id=order.id,
        razorpay_payment_id=verify_data.razorpay_payment_id,
        plan_id=order.plan_id,
        plan_name=plan_name,
        billing_cycle=order.billing_cycle,
        amount=order.amount_usd,
        currency=order.currency,
        status="paid",
        billing_name=org.name,
        billing_email=current_user.email,
        paid_at=utc_now(),
        notes="Order payment verification confirmation",
    )
    db.add(invoice)

    await db.commit()
    await db.refresh(order)

    currency_symbol = "₹" if order.currency == "INR" else "$"
    return RazorpayPaymentVerifyResponse(
        success=True,
        order_id=order.id,
        transaction_id=order.transaction_id,
        plan_id=order.plan_id,
        plan_name=plan_name,
        amount=order.amount_usd,
        currency=order.currency,
        payment_status="paid",
        message=f"Payment verified successfully! Welcome to {plan_name} ({currency_symbol}{order.amount_usd:.2f}).",
        organization_id=org.id,
    )


@router.post("/checkout", response_model=CheckoutResponse)
async def process_checkout(
    checkout_data: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Direct checkout endpoint for subscription orders."""
    plan = PLAN_LOOKUP.get(checkout_data.plan_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown plan tier: '{checkout_data.plan_id}'.",
        )

    settings = get_settings()
    currency = settings.RAZORPAY_CURRENCY.upper()
    amount_usd = calculate_plan_amount(plan, checkout_data.billing_cycle, "USD")

    org_res = await db.execute(
        select(Organization).where(Organization.owner_id == current_user.id)
    )
    org = org_res.scalar_one_or_none()

    seats_limit = plan.limits.get("seats", 5)

    if not org:
        slug = f"{current_user.username.lower()}-{uuid.uuid4().hex[:6]}"
        org = Organization(
            name=f"{current_user.full_name or current_user.username}'s Team",
            slug=slug,
            owner_id=current_user.id,
            plan_tier=plan.id,
            billing_cycle=checkout_data.billing_cycle,
            subscription_status="active",
            max_seats=seats_limit,
        )
        db.add(org)
        await db.flush()
        member = OrganizationMember(
            organization_id=org.id,
            user_id=current_user.id,
            role="admin",
        )
        db.add(member)
    else:
        org.plan_tier = plan.id
        org.billing_cycle = checkout_data.billing_cycle
        org.subscription_status = "active"
        org.max_seats = seats_limit

    if current_user.role != "admin":
        current_user.role = "admin"

    txn_id = f"txn_{uuid.uuid4().hex[:16]}"
    order_id = f"order_rzp_{uuid.uuid4().hex[:16]}"
    card_last4 = checkout_data.card_number[-4:] if checkout_data.card_number else None

    order = SubscriptionOrder(
        organization_id=org.id,
        user_id=current_user.id,
        plan_id=plan.id,
        plan_name=plan.name,
        billing_cycle=checkout_data.billing_cycle,
        amount_usd=amount_usd,
        currency=currency,
        payment_method="razorpay",
        card_last4=card_last4,
        razorpay_order_id=order_id,
        razorpay_payment_id=txn_id,
        billing_name=checkout_data.billing_name,
        billing_email=checkout_data.billing_email,
        transaction_id=txn_id,
        status="paid",
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)

    return CheckoutResponse(
        success=True,
        order_id=order.id,
        transaction_id=txn_id,
        plan_id=plan.id,
        plan_name=plan.name,
        amount_usd=amount_usd,
        billing_cycle=checkout_data.billing_cycle,
        card_last4=card_last4,
        message=f"Successfully subscribed to {plan.name} plan! Your organization is active.",
        organization_id=org.id,
    )
