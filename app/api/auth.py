"""Authentication and Authorization API routes."""

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    create_id_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    utc_now,
    verify_password,
)
from app.core.logging import logger
from app.core.rate_limit import RateLimiter
from app.database import get_db
from app.models.user import RefreshToken, User
from app.schemas.auth import (
    RefreshTokenRequest,
    TokenRefreshResponse,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Rate limiters for authentication endpoints to prevent brute-force attacks and abuse
login_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)
register_rate_limiter = RateLimiter(max_requests=5, window_seconds=60)
refresh_rate_limiter = RateLimiter(max_requests=30, window_seconds=60)


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(register_rate_limiter)],
)
async def register(request: UserRegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user account and return JWT access token, ID token, and refresh token."""
    # Check for existing email or username
    existing_user_query = await db.execute(
        select(User).where(or_(User.email == request.email.lower(), User.username == request.username.lower()))
    )
    existing_user = existing_user_query.scalar_one_or_none()
    if existing_user:
        if existing_user.email == request.email.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email already exists.",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this username already exists.",
            )

    new_user = User(
        id=str(uuid.uuid4()),
        email=request.email.lower().strip(),
        username=request.username.lower().strip(),
        full_name=request.full_name.strip() if request.full_name else None,
        hashed_password=hash_password(request.password),
        role="user",
        is_active=True,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    # Issue JWT tokens
    access_token = create_access_token(new_user)
    id_token = create_id_token(new_user)
    refresh_token_str, _ = await create_refresh_token(db, new_user)

    return TokenResponse(
        access_token=access_token,
        id_token=id_token,
        refresh_token=refresh_token_str,
        token_type="Bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(new_user),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(login_rate_limiter)],
)
async def login(request: UserLoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate with username or email, and return JWT access, ID, and refresh tokens."""
    identifier = request.username.lower().strip()
    user_query = await db.execute(
        select(User).where(or_(User.email == identifier, User.username == identifier))
    )
    user = user_query.scalar_one_or_none()

    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive. Please contact support.",
        )

    access_token = create_access_token(user)
    id_token = create_id_token(user)
    refresh_token_str, _ = await create_refresh_token(db, user)

    return TokenResponse(
        access_token=access_token,
        id_token=id_token,
        refresh_token=refresh_token_str,
        token_type="Bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/refresh",
    response_model=TokenRefreshResponse,
    dependencies=[Depends(refresh_rate_limiter)],
)
async def refresh_tokens(request: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a valid refresh token for fresh access, id, and rotated refresh tokens."""
    res = await db.execute(select(RefreshToken).where(RefreshToken.token == request.refresh_token))
    token_record = res.scalar_one_or_none()

    if not token_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # REPLAY ATTACK DETECTION (RFC 6819)
    # If an already revoked token is submitted, assume a token compromise.
    # Invalidate ALL active refresh tokens for this user.
    if token_record.revoked:
        logger.warning(
            f"Security Alert: Replay attempt detected with revoked token for user_id={token_record.user_id}. "
            "Revoking all active refresh tokens for this user."
        )
        active_tokens_query = await db.execute(
            select(RefreshToken).where(RefreshToken.user_id == token_record.user_id, RefreshToken.revoked.is_(False))
        )
        for act in active_tokens_query.scalars().all():
            act.revoked = True
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Security violation: Revoked token reuse detected. All active sessions invalidated. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    exp = token_record.expires_at
    now = datetime.now(timezone.utc) if exp.tzinfo is not None else datetime.utcnow()
    if exp < now:
        token_record.revoked = True
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fetch user
    user_res = await db.execute(select(User).where(User.id == token_record.user_id))
    user = user_res.scalar_one_or_none()
    if not user or not user.is_active:
        token_record.revoked = True
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or deactivated.",
        )

    # REFRESH TOKEN ROTATION: Revoke old token and issue a fresh one
    token_record.revoked = True
    new_refresh_token_str, _ = await create_refresh_token(db, user)

    # Issue new access token and id token
    new_access_token = create_access_token(user)
    new_id_token = create_id_token(user)

    return TokenRefreshResponse(
        access_token=new_access_token,
        id_token=new_id_token,
        refresh_token=new_refresh_token_str,
        token_type="Bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(request: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    """Revoke a refresh token on logout."""
    res = await db.execute(select(RefreshToken).where(RefreshToken.token == request.refresh_token))
    token_record = res.scalar_one_or_none()
    if token_record:
        token_record.revoked = True
        await db.commit()
    return {"message": "Logged out successfully."}


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(user: User = Depends(get_current_user)):
    """Get the profile of the currently authenticated user."""
    return UserResponse.model_validate(user)
