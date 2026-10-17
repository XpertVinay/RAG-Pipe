"""API endpoints for system and component health checks."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.ingestion.vector_store import vector_store
from app.providers.factory import ModelFactory
from app.schemas.health import ServiceHealth, SystemHealthResponse

router = APIRouter(prefix="/api/health", tags=["health"])
settings = get_settings()


@router.get("", response_model=SystemHealthResponse)
async def check_system_health(db: AsyncSession = Depends(get_db)):
    """Perform a deep health check of Database, Vector Store, and configured LLM providers."""
    components = {}
    overall_status = "healthy"

    # 1. Database check
    try:
        await db.execute(text("SELECT 1"))
        components["database"] = ServiceHealth(status="healthy", message="Database connection active.")
    except Exception as e:
        components["database"] = ServiceHealth(status="unhealthy", message=f"DB error: {str(e)}")
        overall_status = "degraded"

    # 2. Vector Store check
    try:
        v_health = vector_store.check_health()
        components["vector_store"] = ServiceHealth(
            status=v_health.get("status", "unknown"),
            message="Vector store operational.",
            details=v_health,
        )
        if v_health.get("status") != "healthy":
            overall_status = "degraded"
    except Exception as e:
        components["vector_store"] = ServiceHealth(status="unhealthy", message=str(e))
        overall_status = "degraded"

    # 3. LLM / Providers check
    try:
        prov_info = await ModelFactory.get_providers_info()
        components["providers"] = ServiceHealth(
            status="healthy",
            message=f"Default provider: {settings.DEFAULT_CHAT_PROVIDER}",
            details={"chat_providers": [p.model_dump() for p in prov_info.get("chat", [])]},
        )
    except Exception as e:
        components["providers"] = ServiceHealth(status="degraded", message=str(e))

    return SystemHealthResponse(
        status=overall_status,
        version="1.0.0",
        environment=settings.APP_ENV,
        components=components,
    )
