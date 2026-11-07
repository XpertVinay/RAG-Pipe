"""Core authentication service: JWT tokens (access, id, refresh) and password hashing."""

import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.user import RefreshToken, User

settings = get_settings()

JWT_ALGORITHM = getattr(settings, "JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = getattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 60)
ID_TOKEN_EXPIRE_MINUTES = getattr(settings, "ID_TOKEN_EXPIRE_MINUTES", 60)
REFRESH_TOKEN_EXPIRE_DAYS = getattr(settings, "REFRESH_TOKEN_EXPIRE_DAYS", 7)


def get_auth_config() -> Dict[str, Any]:
    """Retrieve dynamic JWT algorithm and expiration windows from cache or settings."""
    try:
        from app.services.config_service import config_service
        return {
            "algorithm": config_service._settings_cache.get("jwt_algorithm", settings.JWT_ALGORITHM),
            "access_token_expire_minutes": int(config_service._settings_cache.get("access_token_expire_minutes", settings.ACCESS_TOKEN_EXPIRE_MINUTES)),
            "id_token_expire_minutes": int(config_service._settings_cache.get("id_token_expire_minutes", settings.ID_TOKEN_EXPIRE_MINUTES)),
            "refresh_token_expire_days": int(config_service._settings_cache.get("refresh_token_expire_days", settings.REFRESH_TOKEN_EXPIRE_DAYS)),
        }
    except Exception:
        return {
            "algorithm": getattr(settings, "JWT_ALGORITHM", "HS256"),
            "access_token_expire_minutes": getattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 60),
            "id_token_expire_minutes": getattr(settings, "ID_TOKEN_EXPIRE_MINUTES", 60),
            "refresh_token_expire_days": getattr(settings, "REFRESH_TOKEN_EXPIRE_DAYS", 7),
        }


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
    auth_cfg = get_auth_config()
    delta = expires_delta or timedelta(minutes=auth_cfg["access_token_expire_minutes"])
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
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=auth_cfg["algorithm"])


def create_id_token(user: User, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed OIDC-compliant ID token representing user identity claims."""
    auth_cfg = get_auth_config()
    delta = expires_delta or timedelta(minutes=auth_cfg["id_token_expire_minutes"])
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
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=auth_cfg["algorithm"])


async def create_refresh_token(db: AsyncSession, user: User) -> Tuple[str, datetime]:
    """Generate a cryptographically secure refresh token, store in database, and return."""
    auth_cfg = get_auth_config()
    raw_token = secrets.token_urlsafe(64)
    expires_at = utc_now() + timedelta(days=auth_cfg["refresh_token_expire_days"])

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
    auth_cfg = get_auth_config()
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[auth_cfg["algorithm"], "HS256"],
            options={"verify_aud": False},
        )
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


def extract_token_from_request(
    request: Optional[Request] = None,
    auth: Optional[HTTPAuthorizationCredentials] = None,
) -> Optional[str]:
    """Extract JWT token from Bearer header, URL query parameter, or browser cookies."""
    if auth and auth.credentials:
        return auth.credentials
    if request:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:].strip()
        query_token = request.query_params.get("token")
        if query_token:
            return query_token.strip()
        cookie_token = request.cookies.get("access_token") or request.cookies.get("token")
        if cookie_token:
            return cookie_token.strip()
    return None


# High-concurrency in-memory user cache with bounded size and TTL
_USER_CACHE: Dict[str, Tuple[User, float]] = {}
_USER_CACHE_MAX_SIZE = 2000


def get_cached_user(user_id: str) -> Optional[User]:
    """Retrieve user from in-memory cache if still valid."""
    entry = _USER_CACHE.get(user_id)
    if entry:
        user, expires_at = entry
        if time.time() < expires_at and getattr(user, "is_active", False):
            return user
        _USER_CACHE.pop(user_id, None)
    return None


def set_cached_user(user: User, db: Optional[AsyncSession] = None) -> None:
    """Store user in in-memory cache, expunging from session to detach safely."""
    ttl = float(getattr(settings, "AUTH_USER_CACHE_TTL_SECONDS", 60))
    if len(_USER_CACHE) > _USER_CACHE_MAX_SIZE:
        now = time.time()
        expired = [k for k, (_, exp) in _USER_CACHE.items() if now >= exp]
        for k in expired:
            _USER_CACHE.pop(k, None)
        if len(_USER_CACHE) > _USER_CACHE_MAX_SIZE:
            _USER_CACHE.clear()
    if db:
        try:
            db.expunge(user)
        except Exception:
            pass
    _USER_CACHE[user.id] = (user, time.time() + ttl)


def invalidate_user_cache(user_id: str) -> None:
    """Invalidate cached user instance on profile / permission changes."""
    _USER_CACHE.pop(user_id, None)


async def get_current_user(
    request: Request,
    auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency to enforce authentication (Bearer, query parameter, or cookie) and retrieve active user."""
    token = extract_token_from_request(request, auth)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Missing Bearer access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(token, expected_type="access")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject.")

    cached = get_cached_user(user_id)
    if cached:
        return cached

    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account not found.")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is deactivated.")

    set_cached_user(user, db)
    return user


async def get_optional_user(
    request: Request,
    auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """FastAPI dependency to optionally authenticate user if token is provided via Bearer, query, or cookie."""
    token = extract_token_from_request(request, auth)
    if not token:
        return None
    try:
        payload = decode_token(token, expected_type="access")
        user_id = payload.get("sub")
        if not user_id:
            return None
        cached = get_cached_user(user_id)
        if cached:
            return cached
        res = await db.execute(select(User).where(User.id == user_id))
        user = res.scalar_one_or_none()
        if user and user.is_active:
            set_cached_user(user, db)
            return user
        return None
    except Exception:
        return None


def is_admin_or_staff(user: Optional[User]) -> bool:
    """Return True if user has administrator, super admin, or staff privileges."""
    if not user:
        return False
    return getattr(user, "role", "user") in ("admin", "super_admin", "staff", "staffs")


async def require_admin_or_staff(
    user: User = Depends(get_current_user),
) -> User:
    """FastAPI dependency requiring authenticated user to have admin, super admin, or staff role."""
    if not is_admin_or_staff(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted. Admin, Super Admin, or Staff privileges required.",
        )
    return user


def is_admin(user: Optional[User]) -> bool:
    """Return True if user has super admin or admin privileges."""
    if not user:
        return False
    return getattr(user, "role", "user") in ("admin", "super_admin", "superadmin", "super-admin")


async def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    """FastAPI dependency requiring authenticated user to have admin or super_admin role."""
    if not is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted. Super Admin or Administrator privileges required.",
        )
    return user


def is_super_admin(user: Optional[User]) -> bool:
    """Return True if user has super admin privileges."""
    if not user:
        return False
    return getattr(user, "role", "user") in ("super_admin", "superadmin", "super-admin")


async def require_super_admin(
    user: User = Depends(get_current_user),
) -> User:
    """FastAPI dependency requiring authenticated user to have super_admin role."""
    if not is_super_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted. Super Admin privileges required.",
        )
    return user

