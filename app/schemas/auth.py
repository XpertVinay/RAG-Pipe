"""Pydantic schemas for Authentication and Authorization."""

import re
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserRegisterRequest(BaseModel):
    """Payload for user registration."""
    email: str = Field(..., max_length=255, description="User email address")
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)
    full_name: Optional[str] = Field(None, max_length=100)
    role: Optional[str] = Field("user", description="Account role: 'user', 'staff', 'admin'")
    invite_token: Optional[str] = Field(None, description="Optional organization invite token")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", cleaned):
            raise ValueError("Invalid email format. Must be a valid email address (e.g. user@example.com).")
        return cleaned

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if len(cleaned) < 3 or len(cleaned) > 50:
            raise ValueError("Username must be between 3 and 50 characters.")
        if not re.match(r"^[a-zA-Z0-9_-]+$", cleaned):
            raise ValueError("Username can only contain letters, numbers, hyphens, and underscores.")
        return cleaned

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters.")
        if len(v) > 100:
            raise ValueError("Password cannot exceed 100 characters.")
        if v.isspace():
            raise ValueError("Password cannot consist solely of whitespace.")
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: Optional[str]) -> str:
        if not v:
            return "user"
        cleaned = v.strip().lower()
        if cleaned in ("staffs", "staff"):
            return "staff"
        if cleaned not in ("user", "staff", "admin"):
            raise ValueError("Role must be one of: 'user', 'staff', 'admin'.")
        return cleaned

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned if cleaned else None


class UserLoginRequest(BaseModel):
    """Payload for user authentication."""
    username: str = Field(..., min_length=3, max_length=100, description="Username or email address")
    password: str = Field(..., min_length=6, max_length=100)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 3:
            raise ValueError("Username or email must be at least 3 characters.")
        return cleaned

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters.")
        return v


class RefreshTokenRequest(BaseModel):
    """Payload for refreshing JWT access & id tokens."""
    refresh_token: str = Field(..., min_length=10, max_length=500, description="Opaque refresh token string")

    @field_validator("refresh_token")
    @classmethod
    def validate_refresh_token(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Refresh token cannot be empty.")
        return cleaned


class UserResponse(BaseModel):
    """Public user profile representation."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    username: str
    full_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """JWT Token bundle including access token, id token, and refresh token."""
    access_token: str
    id_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600  # seconds
    user: UserResponse


class TokenRefreshResponse(BaseModel):
    """Updated token pair response."""
    access_token: str
    id_token: str
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    expires_in: int = 3600
