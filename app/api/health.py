import asyncio
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.ingestion.vector_store import vector_store
from app.providers.factory import ModelFactory
from app.schemas.health import ServiceHealth, SystemHealthResponse

router = APIRouter(prefix="/health", tags=["health"])
settings = get_settings()


@router.get("", response_model=SystemHealthResponse)
async def check_system_health(db: AsyncSession = Depends(get_db)):
    """Perform a high-speed concurrent health check of Database, Vector Store, LLM providers, and Queue."""
    # 1. Database check
    async def _check_db():
        try:
            await db.execute(text("SELECT 1"))
            return "database", ServiceHealth(status="healthy", message="Database connection active.")
        except Exception as e:
            return "database", ServiceHealth(status="unhealthy", message=f"DB error: {str(e)}")

    # 2. Vector Store check (offloaded to threadpool to avoid blocking async event loop)
    async def _check_vector():
        try:
            loop = asyncio.get_running_loop()
            v_health = await loop.run_in_executor(None, vector_store.check_health)
            status = v_health.get("status", "unknown")
            return "vector_store", ServiceHealth(
                status=status,
                message="Vector store operational." if status == "healthy" else v_health.get("message", "Vector store degraded"),
                details=v_health,
            )
        except Exception as e:
            return "vector_store", ServiceHealth(status="unhealthy", message=str(e))

    # 3. LLM / Providers check (concurrent and cached)
    async def _check_providers():
        try:
            prov_info = await ModelFactory.get_providers_info()
            return "providers", ServiceHealth(
                status="healthy",
                message=f"Default provider: {settings.DEFAULT_CHAT_PROVIDER}",
                details={"chat_providers": [p.model_dump() for p in prov_info.get("chat", [])]},
            )
        except Exception as e:
            return "providers", ServiceHealth(status="degraded", message=str(e))

    # 4. RabbitMQ Queue check
    async def _check_queue():
        try:
            from app.services.queue_service import queue_service
            q_health = await queue_service.check_health()
            return "queue", ServiceHealth(
                status=q_health.get("status", "unknown"),
                message=q_health.get("message", "RabbitMQ status"),
                details=q_health,
            )
        except Exception as e:
            return "queue", ServiceHealth(status="degraded", message=str(e))

    # Run all 4 checks concurrently
    results = await asyncio.gather(_check_db(), _check_vector(), _check_providers(), _check_queue())

    components = {}
    overall_status = "healthy"
    for comp_name, comp_health in results:
        components[comp_name] = comp_health
        if comp_health.status == "unhealthy":
            overall_status = "degraded" if overall_status == "healthy" else overall_status
        elif comp_health.status == "degraded" and overall_status == "healthy":
            overall_status = "degraded"

    return SystemHealthResponse(
        status=overall_status,
        version="1.0.0",
        environment=settings.APP_ENV,
        components=components,
    )


@router.get("/liveness")
@router.get("/ready")
async def liveness_probe():
    """Ultra-fast sub-millisecond liveness probe for Docker, Kubernetes, and load balancers."""
    return {"status": "ok"}
