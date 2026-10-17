"""Core authentication service: JWT tokens (access, id, refresh) and password hashing."""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
import bcrypt
import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.user import RefreshToken, User

settings = get_settings()

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
ID_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7

bearer_scheme = HTTPBearer(auto_error=False)


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def hash_password(plain_password: str) -> str:
    """Hash a plain text password using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain text password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user: User, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT access token for API authorization."""
    delta = expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = utc_now() + delta
    payload = {
        "sub": user.id,
        "email": user.email,
        "username": user.username,
        "role": user.role,
        "type": "access",
        "iat": utc_now(),
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_id_token(user: User, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed OIDC-compliant ID token representing user identity claims."""
    delta = expires_delta or timedelta(minutes=ID_TOKEN_EXPIRE_MINUTES)
    expire = utc_now() + delta
    payload = {
        "sub": user.id,
        "name": user.full_name or user.username,
        "preferred_username": user.username,
        "email": user.email,
        "role": user.role,
        "iss": "rag-agent-auth",
        "aud": "rag-agent-client",
        "type": "id_token",
        "iat": utc_now(),
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


async def create_refresh_token(db: AsyncSession, user: User) -> Tuple[str, datetime]:
    """Generate a cryptographically secure refresh token, store in database, and return."""
    raw_token = secrets.token_urlsafe(64)
    expires_at = utc_now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    token_record = RefreshToken(
        user_id=user.id,
        token=raw_token,
        expires_at=expires_at,
        revoked=False,
    )
    db.add(token_record)
    await db.commit()
    await db.refresh(token_record)
    return raw_token, expires_at


def decode_token(token: str, expected_type: Optional[str] = "access") -> Dict[str, Any]:
    """Decode and validate a JWT token signature and expiration."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
        if expected_type and payload.get("type") != expected_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token type. Expected '{expected_type}' token.",
            )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency to enforce Bearer token authentication and retrieve active user."""
    if not auth or not auth.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Missing Bearer access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(auth.credentials, expected_type="access")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject.")

    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account not found.")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is deactivated.")

    return user


async def get_optional_user(
    auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """FastAPI dependency to optionally authenticate user if token is provided."""
    if not auth or not auth.credentials:
        return None
    try:
        payload = decode_token(auth.credentials, expected_type="access")
        user_id = payload.get("sub")
        if not user_id:
            return None
        res = await db.execute(select(User).where(User.id == user_id))
        user = res.scalar_one_or_none()
        return user if user and user.is_active else None
    except Exception:
        return None
