"""API v1 router package with unified versioning and discovery metadata."""

from typing import Any, Dict
from fastapi import APIRouter
from app.config import get_settings

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

v1_router = APIRouter(prefix="/v1")

# Mount all v1 domain routers
v1_router.include_router(auth_router)
v1_router.include_router(rooms_router)
v1_router.include_router(projects_router)
v1_router.include_router(projects_direct_router)
v1_router.include_router(documents_router)
v1_router.include_router(chat_router)
v1_router.include_router(memory_router)
v1_router.include_router(settings_router)
v1_router.include_router(health_router)
v1_router.include_router(organizations_router)
v1_router.include_router(pricing_router)
v1_router.include_router(agents_router)
v1_router.include_router(mcp_router)
v1_router.include_router(audit_router)


@v1_router.get("/version", tags=["version"], summary="Get API v1 specification and client compatibility")
async def get_v1_version_info() -> Dict[str, Any]:
    """Return v1 API metadata, contract version, supported clients, and capabilities."""
    return {
        "api_version": "v1",
        "semantic_version": "1.0.0",
        "status": "stable",
        "deprecated": False,
        "environment": settings.APP_ENV,
        "docs_url": "/docs",
        "capabilities": {
            "auth": "JWT Bearer + Refresh Token Rotation",
            "chat": "Synchronous & Server-Sent Events (SSE) Streaming",
            "workspaces": "Multi-Tenant Isolated Rooms with Role-Based Access Control",
            "ingestion": "Multi-Format Documents (PDF, DOCX, TXT, MD, CSV, HTML)",
            "memory": "Short-Term Working & Long-Term Semantic Vector Memory",
            "billing": "Razorpay Recurring Mandates, One-Time Orders & Tax Invoicing",
        },
        "client_compatibility": {
            "web": "Supported",
            "mobile_flutter": "Fully Supported (Dart / http / web_socket_channel)",
            "mobile_react_native": "Fully Supported (TypeScript / fetch / EventSource)",
            "mobile_ios_swift": "Fully Supported (URLSession / AsyncSequence)",
            "mobile_android_kotlin": "Fully Supported (OkHttp / Ktor / Retrofit)",
        },
    }


__all__ = ["v1_router"]
