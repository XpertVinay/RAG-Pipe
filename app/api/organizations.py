"""Organization and Multi-User Invitation Management API routes."""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_admin, utc_now
from app.database import get_db
from app.models.organization import Organization, OrganizationInvite, OrganizationMember
from app.models.user import User
from app.schemas.organization import (
    InviteCreateRequest,
    InviteResponse,
    InviteVerifyResponse,
    OrganizationResponse,
)

router = APIRouter(prefix="/org", tags=["organization"])


async def get_or_create_admin_org(user: User, db: AsyncSession) -> Organization:
    """Retrieve existing organization owned by the admin user, or create a default one."""
    res = await db.execute(select(Organization).where(Organization.owner_id == user.id))
    org = res.scalar_one_or_none()
    if not org:
        # Check if user is member of any org as admin
        member_res = await db.execute(
            select(OrganizationMember)
            .where(OrganizationMember.user_id == user.id)
            .where(OrganizationMember.role == "admin")
        )
        membership = member_res.scalar_one_or_none()
        if membership:
            org_res = await db.execute(select(Organization).where(Organization.id == membership.organization_id))
            org = org_res.scalar_one_or_none()

    if not org:
        slug = f"{user.username.lower()}-{uuid.uuid4().hex[:6]}"
        org = Organization(
            name=f"{user.full_name or user.username}'s Team",
            slug=slug,
            owner_id=user.id,
            plan_tier="starter",
            billing_cycle="monthly",
            subscription_status="active",
            max_seats=5,
        )
        db.add(org)
        await db.flush()

        member = OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role="admin",
        )
        db.add(member)
        await db.commit()
        await db.refresh(org)

    return org


@router.get("/current", response_model=OrganizationResponse)
async def get_current_organization(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the organization associated with the current user."""
    # Find user's membership or ownership
    org_res = await db.execute(
        select(Organization).where(Organization.owner_id == current_user.id)
    )
    org = org_res.scalar_one_or_none()

    if not org:
        mem_res = await db.execute(
            select(OrganizationMember).where(OrganizationMember.user_id == current_user.id)
        )
        membership = mem_res.scalar_one_or_none()
        if membership:
            org_lookup = await db.execute(
                select(Organization).where(Organization.id == membership.organization_id)
            )
            org = org_lookup.scalar_one_or_none()

    if not org:
        if current_user.role == "admin":
            org = await get_or_create_admin_org(current_user, db)
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No organization associated with this account.",
            )

    # Count members
    member_count_res = await db.execute(
        select(func.count(OrganizationMember.id)).where(OrganizationMember.organization_id == org.id)
    )
    member_count = member_count_res.scalar_one() or 1

    return OrganizationResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        owner_id=org.owner_id,
        plan_tier=org.plan_tier,
        billing_cycle=org.billing_cycle,
        subscription_status=org.subscription_status,
        max_seats=org.max_seats,
        member_count=member_count,
        created_at=org.created_at,
    )


@router.post("/invites", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
async def create_invite(
    request_data: InviteCreateRequest,
    req: Request,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Generate a secure, shareable registration invite link with a specified role (Admin only)."""
    org = await get_or_create_admin_org(admin_user, db)

    token = secrets.token_urlsafe(32)
    expires_at = utc_now() + timedelta(days=request_data.expires_in_days)

    invite = OrganizationInvite(
        token=token,
        organization_id=org.id,
        invited_by_user_id=admin_user.id,
        email=request_data.email,
        assigned_role=request_data.assigned_role,
        expires_at=expires_at,
        is_used=False,
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    base_url = str(req.base_url).rstrip("/")
    invite_url = f"{base_url}/?invite={token}"

    return InviteResponse(
        id=invite.id,
        token=invite.token,
        invite_url=invite_url,
        assigned_role=invite.assigned_role,
        email=invite.email,
        organization_id=org.id,
        organization_name=org.name,
        expires_at=invite.expires_at,
        is_used=invite.is_used,
        used_by_user_id=invite.used_by_user_id,
        created_at=invite.created_at,
    )


@router.get("/invites", response_model=List[InviteResponse])
async def list_invites(
    req: Request,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all invitation links issued by the current admin (Admin only)."""
    org = await get_or_create_admin_org(admin_user, db)

    res = await db.execute(
        select(OrganizationInvite)
        .where(OrganizationInvite.organization_id == org.id)
        .order_by(OrganizationInvite.created_at.desc())
    )
    invites = res.scalars().all()

    base_url = str(req.base_url).rstrip("/")
    return [
        InviteResponse(
            id=inv.id,
            token=inv.token,
            invite_url=f"{base_url}/?invite={inv.token}",
            assigned_role=inv.assigned_role,
            email=inv.email,
            organization_id=org.id,
            organization_name=org.name,
            expires_at=inv.expires_at,
            is_used=inv.is_used,
            used_by_user_id=inv.used_by_user_id,
            created_at=inv.created_at,
        )
        for inv in invites
    ]


@router.delete("/invites/{invite_id}", status_code=status.HTTP_200_OK)
async def revoke_invite(
    invite_id: str,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Revoke or delete an invitation link (Admin only)."""
    org = await get_or_create_admin_org(admin_user, db)

    res = await db.execute(
        select(OrganizationInvite).where(
            OrganizationInvite.id == invite_id,
            OrganizationInvite.organization_id == org.id,
        )
    )
    invite = res.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite link not found.")

    await db.delete(invite)
    await db.commit()
    return {"message": "Invite link revoked successfully."}


@router.get("/invites/verify/{token}", response_model=InviteVerifyResponse)
async def verify_invite_token(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public verification endpoint to inspect invite token status."""
    res = await db.execute(
        select(OrganizationInvite).where(OrganizationInvite.token == token.strip())
    )
    invite = res.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid invitation link.")

    if invite.is_used:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This invitation link has already been used.")

    now = utc_now()
    invite_exp = invite.expires_at
    if invite_exp.tzinfo is None:
        invite_exp = invite_exp.replace(tzinfo=timezone.utc)
    if invite_exp < now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This invitation link has expired.")

    org_name = None
    if invite.organization_id:
        org_res = await db.execute(select(Organization).where(Organization.id == invite.organization_id))
        org = org_res.scalar_one_or_none()
        if org:
            org_name = org.name

    return InviteVerifyResponse(
        valid=True,
        token=invite.token,
        assigned_role=invite.assigned_role,
        email=invite.email,
        organization_name=org_name,
        expires_at=invite.expires_at,
    )
