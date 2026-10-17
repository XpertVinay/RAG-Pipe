"""Pydantic schemas for Authentication and Authorization."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class UserRegisterRequest(BaseModel):
    """Payload for user registration."""
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", description="User email address")
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(..., min_length=6, max_length=100)
    full_name: Optional[str] = Field(None, max_length=100)


class UserLoginRequest(BaseModel):
    """Payload for user authentication."""
    username: str = Field(..., description="Username or email address")
    password: str = Field(..., min_length=1)


class RefreshTokenRequest(BaseModel):
    """Payload for refreshing JWT access & id tokens."""
    refresh_token: str = Field(..., description="Opaque refresh token string")


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
