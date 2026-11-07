"""API package export with versioned routing (v1) and legacy compatibility layer."""

from typing import Any, Dict
from fastapi import APIRouter
from app.config import get_settings

from app.api.v1 import v1_router
from app.api.auth import router as auth_router
from app.api.rooms import router as rooms_router
from app.api.documents import router as documents_router
from app.api.chat import router as chat_router
from app.api.memory import router as memory_router
from app.api.settings import router as settings_router
from app.api.health import router as health_router
from app.api.organizations import router as organizations_router
from app.api.pricing import router as pricing_router
from app.api.agents import router as agents_router
from app.api.mcp import router as mcp_router
from app.api.audit import router as audit_router
from app.api.projects import router as projects_router, projects_direct_router

settings = get_settings()

api_router = APIRouter(prefix="/api")

# 1. Mount Official Versioned v1 Router -> /api/v1/*
api_router.include_router(v1_router)

# 2. Mount Legacy Compatibility Layer -> /api/*
# Ensures 100% backward compatibility for existing frontend clients and test suites.
api_router.include_router(auth_router, include_in_schema=False)
api_router.include_router(rooms_router, include_in_schema=False)
api_router.include_router(projects_router, include_in_schema=False)
api_router.include_router(projects_direct_router, include_in_schema=False)
api_router.include_router(documents_router, include_in_schema=False)
api_router.include_router(chat_router, include_in_schema=False)
api_router.include_router(memory_router, include_in_schema=False)
api_router.include_router(settings_router, include_in_schema=False)
api_router.include_router(health_router, include_in_schema=False)
api_router.include_router(organizations_router, include_in_schema=False)
api_router.include_router(pricing_router, include_in_schema=False)
api_router.include_router(agents_router, include_in_schema=False)
api_router.include_router(mcp_router, include_in_schema=False)
api_router.include_router(audit_router, include_in_schema=False)


@api_router.get("/version", tags=["version"], summary="API Version Discovery Endpoint")
async def get_api_discovery() -> Dict[str, Any]:
    """Provide API version discovery for web, mobile, and third-party API clients."""
    return {
        "current_version": "v1",
        "supported_versions": ["v1"],
        "latest_version": "v1",
        "environment": settings.APP_ENV,
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "endpoints": {
            "v1": "/api/v1",
            "v1_docs": "/docs#/v1",
            "auth": "/api/v1/auth",
            "rooms": "/api/v1/rooms",
            "documents": "/api/v1/documents",
            "chat": "/api/v1/chat",
            "memory": "/api/v1/memory",
            "settings": "/api/v1/settings",
            "health": "/api/v1/health",
            "organizations": "/api/v1/org",
            "pricing": "/api/v1/pricing",
            "agents": "/api/v1/agents",
            "mcp": "/api/v1/mcp",
        },
    }


__all__ = ["api_router"]
