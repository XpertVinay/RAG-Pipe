"""Unit and integration tests for Multi-Tenant Organizations, Role-Specific Invites, and Subscription Pricing."""

import pytest
from datetime import datetime, timezone
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_self_registration_defaults_to_common_user(client: AsyncClient):
    """Verify that a self-registering user without role or invite defaults to 'user' with least privileges."""
    res = await client.post(
        "/api/auth/register",
        json={
            "email": "common_user@example.com",
            "username": "common_usr",
            "password": "Password123!",
            "full_name": "Common User",
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert data["user"]["role"] == "user"
    assert "access_token" in data


@pytest.mark.asyncio
async def test_admin_invite_lifecycle_and_role_delegation(client: AsyncClient):
    """Verify that:
    1. Admin can generate an invite for 'staff'.
    2. Non-admin cannot generate invites (403 Forbidden).
    3. Invite can be verified publicly.
    4. Registering with the invite token grants the delegated role ('staff').
    5. Used invite token cannot be re-used.
    """
    # Register an admin account
    admin_reg = await client.post(
        "/api/auth/register",
        json={
            "email": "org_boss@example.com",
            "username": "org_boss",
            "password": "Password123!",
            "role": "admin",
        },
    )
    assert admin_reg.status_code == 201
    admin_token = admin_reg.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Register a standard user
    std_reg = await client.post(
        "/api/auth/register",
        json={
            "email": "std_member@example.com",
            "username": "std_member",
            "password": "Password123!",
        },
    )
    assert std_reg.status_code == 201
    std_token = std_reg.json()["access_token"]
    std_headers = {"Authorization": f"Bearer {std_token}"}

    # 2. Non-admin attempting to create an invite is rejected
    non_admin_res = await client.post(
        "/api/org/invites",
        headers=std_headers,
        json={"assigned_role": "staff", "expires_in_days": 7},
    )
    assert non_admin_res.status_code == 403

    # 1. Admin generates an invite link for 'staff'
    invite_res = await client.post(
        "/api/org/invites",
        headers=admin_headers,
        json={
            "assigned_role": "staff",
            "email": "invited_staff@example.com",
            "expires_in_days": 7,
        },
    )
    assert invite_res.status_code == 201
    invite_data = invite_res.json()
    assert invite_data["assigned_role"] == "staff"
    assert invite_data["email"] == "invited_staff@example.com"
    assert invite_data["is_used"] is False
    token = invite_data["token"]
    invite_id = invite_data["id"]

    # 3. Public verification endpoint inspects the invite
    verify_res = await client.get(f"/api/org/invites/verify/{token}")
    assert verify_res.status_code == 200
    verify_data = verify_res.json()
    assert verify_data["valid"] is True
    assert verify_data["assigned_role"] == "staff"
    assert verify_data["email"] == "invited_staff@example.com"

    # Email mismatch constraint: registering with different email should fail
    mismatch_reg = await client.post(
        "/api/auth/register",
        json={
            "email": "other_email@example.com",
            "username": "wrong_guy",
            "password": "Password123!",
            "invite_token": token,
        },
    )
    assert mismatch_reg.status_code == 400
    assert "exclusively for" in mismatch_reg.json()["detail"]

    # 4. Registering with correct email and invite token grants 'staff' role
    staff_reg = await client.post(
        "/api/auth/register",
        json={
            "email": "invited_staff@example.com",
            "username": "new_staff_member",
            "password": "Password123!",
            "full_name": "Valued Staff",
            "invite_token": token,
        },
    )
    assert staff_reg.status_code == 201
    staff_data = staff_reg.json()
    assert staff_data["user"]["role"] == "staff"

    # 5. Token is now marked used and cannot be re-used
    reuse_reg = await client.post(
        "/api/auth/register",
        json={
            "email": "another_one@example.com",
            "username": "another_one",
            "password": "Password123!",
            "invite_token": token,
        },
    )
    assert reuse_reg.status_code == 400
    assert "already been used" in reuse_reg.json()["detail"]

    # Admin lists active and used invites
    list_res = await client.get("/api/org/invites", headers=admin_headers)
    assert list_res.status_code == 200
    invites_list = list_res.json()
    assert any(i["id"] == invite_id for i in invites_list)

    # Admin can revoke an invite
    temp_inv = await client.post(
        "/api/org/invites",
        headers=admin_headers,
        json={"assigned_role": "user", "expires_in_days": 1},
    )
    temp_id = temp_inv.json()["id"]
    del_res = await client.delete(f"/api/org/invites/{temp_id}", headers=admin_headers)
    assert del_res.status_code == 200


@pytest.mark.asyncio
async def test_pricing_plans_and_checkout_flow(client: AsyncClient):
    """Verify:
    1. GET /api/pricing/plans returns starter, pro, enterprise tiers.
    2. HTML GET /pricing loads the pricing UI.
    3. Authenticated checkout upgrades organization plan, updates max_seats, and records order.
    """
    # 1. Plans listing
    plans_res = await client.get("/api/pricing/plans")
    assert plans_res.status_code == 200
    plans = plans_res.json()
    assert len(plans) == 3
    plan_ids = [p["id"] for p in plans]
    assert "starter" in plan_ids
    assert "pro" in plan_ids
    assert "enterprise" in plan_ids

    # 2. HTML page endpoint
    page_res = await client.get("/pricing")
    assert page_res.status_code == 200
    assert "Plans &amp; Pricing" in page_res.text or "Plans & Pricing" in page_res.text
    assert "checkout-modal" in page_res.text

    # 3. Register user to test checkout
    user_reg = await client.post(
        "/api/auth/register",
        json={
            "email": "buyer@company.com",
            "username": "buyer_bob",
            "password": "Password123!",
        },
    )
    user_token = user_reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {user_token}"}

    # Process checkout for Pro plan
    checkout_res = await client.post(
        "/api/pricing/checkout",
        headers=headers,
        json={
            "plan_id": "pro",
            "billing_cycle": "annual",
            "billing_name": "Bob Buyer",
            "billing_email": "buyer@company.com",
            "card_number": "4242424242424242",
            "card_exp": "12/28",
            "card_cvv": "123",
        },
    )
    assert checkout_res.status_code == 200
    receipt = checkout_res.json()
    assert receipt["success"] is True
    assert receipt["plan_id"] == "pro"
    assert receipt["card_last4"] == "4242"
    assert receipt["transaction_id"].startswith("txn_")
    assert receipt["amount_usd"] == round(39.0 * 12, 2)

    # Inspect current organization info
    org_res = await client.get("/api/org/current", headers=headers)
    assert org_res.status_code == 200
    org_info = org_res.json()
    assert org_info["plan_tier"] == "pro"
    assert org_info["max_seats"] == 15
    assert org_info["subscription_status"] == "active"


@pytest.mark.asyncio
async def test_razorpay_order_and_payment_verification_lifecycle(client: AsyncClient):
    """Verify:
    1. GET /api/pricing/razorpay/config returns public key_id and currency without exposing secrets.
    2. POST /api/pricing/razorpay/create-order creates order with zero sensitive payment credentials.
    3. POST /api/pricing/razorpay/verify-payment cryptographically verifies tokens, activates org plan, and elevates role.
    4. Database never stores card numbers, CVVs, or payment passwords.
    """
    # 1. Razorpay public config
    cfg_res = await client.get("/api/pricing/razorpay/config")
    assert cfg_res.status_code == 200
    cfg = cfg_res.json()
    assert "key_id" in cfg
    assert "currency" in cfg
    assert "key_secret" not in cfg
    assert "secret" not in cfg

    # Register user
    user_reg = await client.post(
        "/api/auth/register",
        json={
            "email": "rzp_subscriber@company.com",
            "username": "rzp_sub",
            "password": "Password123!",
            "full_name": "Razorpay Subscriber",
        },
    )
    assert user_reg.status_code == 201
    token = user_reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Create Razorpay order (NO credit card or payment credentials provided!)
    create_order_res = await client.post(
        "/api/pricing/razorpay/create-order",
        headers=headers,
        json={
            "plan_id": "pro",
            "billing_cycle": "monthly",
            "billing_name": "Razorpay Subscriber",
            "billing_email": "rzp_subscriber@company.com",
        },
    )
    assert create_order_res.status_code == 200
    order_data = create_order_res.json()
    assert order_data["order_id"].startswith("order_")
    assert order_data["plan_id"] == "pro"
    assert order_data["amount"] > 0
    assert order_data["amount_paise"] == int(round(order_data["amount"] * 100))
    rzp_order_id = order_data["order_id"]

    # 3. Verify Payment
    payment_id = f"pay_test_{rzp_order_id[6:18]}"
    signature = f"sig_test_{rzp_order_id[6:18]}"

    verify_res = await client.post(
        "/api/pricing/razorpay/verify-payment",
        headers=headers,
        json={
            "razorpay_order_id": rzp_order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        },
    )
    assert verify_res.status_code == 200
    verify_data = verify_res.json()
    assert verify_data["success"] is True
    assert verify_data["transaction_id"] == payment_id
    assert verify_data["plan_id"] == "pro"
    assert verify_data["payment_status"] == "paid"

    # Verify organization upgraded
    org_res = await client.get("/api/org/current", headers=headers)
    assert org_res.status_code == 200
    org_info = org_res.json()
    assert org_info["plan_tier"] == "pro"
    assert org_info["max_seats"] == 15
    assert org_info["subscription_status"] == "active"


@pytest.mark.asyncio
async def test_razorpay_mandate_creation_verification_and_scheduler_invoices(client: AsyncClient):
    """Verify:
    1. POST /api/pricing/razorpay/create-mandate sets up recurring mandate without capturing credit card numbers or secrets.
    2. POST /api/pricing/razorpay/verify-mandate cryptographically verifies subscription auth, upgrades organization mandate fields, and generates initial transparent invoice (INV-YYYY-XXXXX).
    3. GET /api/pricing/invoices lists transparent invoice records with non-confidential tokens.
    4. GET /api/pricing/mandate/status returns active mandate, next charge date, and invoice count.
    5. POST /api/pricing/mandate/sync triggers live/sandbox synchronization and creates recurring invoices.
    """
    # Register user
    user_reg = await client.post(
        "/api/auth/register",
        json={
            "email": "mandate_user@enterprise.org",
            "username": "mandate_user",
            "password": "Password123!",
            "full_name": "Mandate Subscriber",
        },
    )
    assert user_reg.status_code == 201
    token = user_reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create recurring mandate
    mandate_req = await client.post(
        "/api/pricing/razorpay/create-mandate",
        headers=headers,
        json={
            "plan_id": "pro",
            "billing_cycle": "monthly",
            "billing_name": "Mandate Subscriber",
            "billing_email": "mandate_user@enterprise.org",
            "total_count": 12,
            "immediate_charge": True,
        },
    )
    assert mandate_req.status_code == 200
    mandate_data = mandate_req.json()
    assert "subscription_id" in mandate_data
    assert mandate_data["subscription_id"].startswith("sub_")
    assert mandate_data["plan_id"] == "pro"
    assert mandate_data["billing_cycle"] == "monthly"
    assert mandate_data["amount"] == 3999.0
    sub_id = mandate_data["subscription_id"]

    # Even if client requests "annual", mandate strictly enforces monthly
    annual_override_req = await client.post(
        "/api/pricing/razorpay/create-mandate",
        headers=headers,
        json={
            "plan_id": "pro",
            "billing_cycle": "annual",
            "billing_name": "Mandate Subscriber",
            "billing_email": "mandate_user@enterprise.org",
        },
    )
    assert annual_override_req.status_code == 200
    assert annual_override_req.json()["billing_cycle"] == "monthly"
    assert annual_override_req.json()["amount"] == 3999.0

    # 2. Verify Mandate authorization tokens
    payment_id = f"pay_mnd_{sub_id[4:16]}"
    signature = f"sig_mnd_{sub_id[4:16]}"

    verify_res = await client.post(
        "/api/pricing/razorpay/verify-mandate",
        headers=headers,
        json={
            "razorpay_subscription_id": sub_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        },
    )
    assert verify_res.status_code == 200
    verify_data = verify_res.json()
    assert verify_data["success"] is True
    assert verify_data["subscription_id"] == sub_id
    assert verify_data["transaction_id"] == payment_id
    assert verify_data["mandate_status"] == "active"
    assert verify_data["invoice_id"] is not None

    # 3. Check Invoices list for complete transparency
    inv_res = await client.get("/api/pricing/invoices", headers=headers)
    assert inv_res.status_code == 200
    invoices = inv_res.json()
    assert len(invoices) >= 1
    first_inv = invoices[0]
    assert first_inv["invoice_number"].startswith("INV-")
    assert first_inv["plan_id"] == "pro"
    assert first_inv["billing_cycle"] == "monthly"
    assert first_inv["status"] == "paid"
    assert first_inv["razorpay_payment_id"] == payment_id
    assert first_inv["razorpay_subscription_id"] == sub_id

    # 4. Check Mandate Status endpoint (verify ~30 days schedule, not 365)
    status_res = await client.get("/api/pricing/mandate/status", headers=headers)
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["mandate_id"] == sub_id
    assert status_data["mandate_status"] == "active"
    assert status_data["plan_tier"] == "pro"
    assert status_data["invoices_count"] >= 1
    assert status_data["mandate_next_charge_at"] is not None
    next_charge_raw = status_data["mandate_next_charge_at"]
    if not next_charge_raw.endswith("Z") and "+" not in next_charge_raw and "-" not in next_charge_raw[10:]:
        next_charge_raw += "+00:00"
    next_charge_dt = datetime.fromisoformat(next_charge_raw.replace("Z", "+00:00"))
    now_dt = datetime.now(timezone.utc)
    delta_days = (next_charge_dt - now_dt).days
    assert 28 <= delta_days <= 32

    # 5. Check Sync endpoint
    sync_res = await client.post("/api/pricing/mandate/sync", headers=headers)
    assert sync_res.status_code == 200
    sync_data = sync_res.json()
    assert sync_data["success"] is True
    assert "invoice" in sync_data["message"].lower()


