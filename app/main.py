"""FastAPI application entrypoint, lifespan, middleware, and route mounting."""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from fastapi.exceptions import RequestValidationError

from app.api import api_router
from app.config import get_settings
from app.core.exceptions import (
    RAGException,
    global_exception_handler,
    rag_exception_handler,
    validation_exception_handler,
)
from app.core.logging import logger
from app.core.tracing import configure_langsmith_tracing
from app.database import init_db
from app.services.mandate_scheduler import (
    start_mandate_sync_scheduler,
    stop_mandate_sync_scheduler,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize local directories, SQLite DB, mandate scheduler, and tracing."""
    logger.info("Initializing Production RAG Agent...")
    logger.info(f"fetch_external_data:{await fetch_external_data()}")
    if settings.APP_ENV.lower() == "production" and "dev-secret-key" in settings.SECRET_KEY:
        logger.critical(
            "SECURITY WARNING: Running in production with default insecure SECRET_KEY! "
            "Please configure a cryptographically secure SECRET_KEY in your environment."
        )
    settings.ensure_directories()
    await init_db()
    from app.services.config_service import config_service
    await config_service.seed_initial_config()
    configure_langsmith_tracing()

    # Initialize enterprise audit trail, backup directories, and baseline risk telemetry
    try:
        from app.services.audit_backup import audit_backup_manager
        from app.services.audit_service import audit_service
        from app.database import AsyncSessionLocal
        audit_backup_manager._ensure_directories()
        async with AsyncSessionLocal() as session:
            await audit_service.seed_initial_audit_events_if_empty(session)
    except Exception as e:
        logger.warning(f"Audit trail initialization note: {e}")

    logger.info("Database, dynamic cache, audit trail, and storage directories ready.")

    # Start Razorpay Mandate recurring sync scheduler
    start_mandate_sync_scheduler()

    # Start embedded RabbitMQ document worker consumer if enabled & recover any orphaned processing jobs
    from app.services.document_worker import (
        recover_orphaned_processing_jobs,
        start_embedded_worker,
        stop_embedded_worker,
    )
    await recover_orphaned_processing_jobs()
    start_embedded_worker()

    yield

    logger.info("Shutting down RAG Agent...")
    await stop_mandate_sync_scheduler()
    await stop_embedded_worker()


app = FastAPI(
    title=settings.APP_NAME,
    description="Production-Ready Document Ingestion and Real-Time RAG Agent with LangChain & LangGraph.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# GZip Compression Middleware (compresses responses > 1KB)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Hardened CORS Middleware (avoid invalid wildcard credentials)
is_wildcard = "*" in settings.allowed_origins_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=not is_wildcard,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# Security Headers Middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://checkout.razorpay.com https://cdn.razorpay.com https://api.razorpay.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: https: https://fastapi.tiangolo.com https://cdn.jsdelivr.net https://cdn.razorpay.com; "
        "frame-src 'self' https://api.razorpay.com https://checkout.razorpay.com https://cdn.razorpay.com; "
        "worker-src 'self' blob:; "
        "connect-src 'self' http: https: ws: wss: https://api.razorpay.com https://lumberjack.razorpay.com https://lumberjack-cx.razorpay.com https://cdn.razorpay.com https://checkout.razorpay.com;"
    )
    response.headers["X-API-Version"] = "1.0.0"
    return response

# Exception handlers
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(RAGException, rag_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# Mount static files and templates
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Select templates directory: use optimized templates if enabled and available
templates_dir = (
    str(BASE_DIR / "templates_dist")
    if settings.should_use_optimized_assets and (BASE_DIR / "templates_dist").exists()
    else str(BASE_DIR / "templates")
)
def get_asset_manifest() -> dict:
    """Load asset optimization manifest with fallback defaults."""
    manifest_file = BASE_DIR / "static" / "dist" / "manifest.json"
    if manifest_file.exists():
        try:
            import json
            return json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"files": {}, "version": "1.0.0"}


def asset_context_processor(request: Request) -> dict:
    return {
        "use_optimized_assets": lambda: settings.should_use_optimized_assets,
        "get_asset_manifest": get_asset_manifest,
    }


templates = Jinja2Templates(
    directory=templates_dir,
    context_processors=[asset_context_processor],
)

# Register Jinja2 global helpers for template asset selection
templates.env.globals["use_optimized_assets"] = lambda: settings.should_use_optimized_assets
templates.env.globals["get_asset_manifest"] = get_asset_manifest

# Mount API routes (includes official /api/v1/* and legacy /api/* compatibility)
app.include_router(api_router)


@app.get("/", response_class=HTMLResponse, tags=["ui"])
async def render_dashboard(request: Request):
    """Render the main server-side Jinja2 dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_name": settings.APP_NAME,
            "default_provider": settings.DEFAULT_CHAT_PROVIDER,
            "default_model": settings.DEFAULT_CHAT_MODEL,
        },
    )


@app.get("/pricing", response_class=HTMLResponse, tags=["ui"])
async def render_pricing_page(request: Request):
    """Render the dedicated Plan and Pricing page with checkout payment."""
    return templates.TemplateResponse(
        request=request,
        name="pricing.html",
        context={
            "app_name": settings.APP_NAME,
        },
    )


# -------------------------------------------------------------------------
# Legal & Compliance Routes
# -------------------------------------------------------------------------
@app.get("/privacy", response_class=HTMLResponse, tags=["legal"])
@app.get("/legal/privacy", response_class=HTMLResponse, tags=["legal"])
async def render_privacy_page(request: Request):
    """Render Privacy Policy page."""
    return templates.TemplateResponse(
        request=request,
        name="legal.html",
        context={
            "app_name": settings.APP_NAME,
            "active_tab": "privacy",
            "page_title": "Privacy Policy",
            "page_description": "Our commitments to enterprise data privacy, document non-training guarantees, and multi-tenant security.",
        },
    )


@app.get("/terms", response_class=HTMLResponse, tags=["legal"])
@app.get("/terms-of-service", response_class=HTMLResponse, tags=["legal"])
@app.get("/legal/terms", response_class=HTMLResponse, tags=["legal"])
async def render_terms_page(request: Request):
    """Render Terms of Service page."""
    return templates.TemplateResponse(
        request=request,
        name="legal.html",
        context={
            "app_name": settings.APP_NAME,
            "active_tab": "terms",
            "page_title": "Terms of Service",
            "page_description": "Terms and conditions governing the use of the RAG Agent multi-tenant intelligence and retrieval platform.",
        },
    )


@app.get("/refund", response_class=HTMLResponse, tags=["legal"])
@app.get("/refund-policy", response_class=HTMLResponse, tags=["legal"])
@app.get("/legal/refund", response_class=HTMLResponse, tags=["legal"])
async def render_refund_page(request: Request):
    """Render Refund Policy page."""
    return templates.TemplateResponse(
        request=request,
        name="legal.html",
        context={
            "app_name": settings.APP_NAME,
            "active_tab": "refund",
            "page_title": "Refund Policy",
            "page_description": "Details regarding our 14-day satisfaction guarantee, recurring mandate cancellations, and Razorpay refund procedures.",
        },
    )


@app.get("/ai-policy", response_class=HTMLResponse, tags=["legal"])
@app.get("/ai-usage", response_class=HTMLResponse, tags=["legal"])
@app.get("/ai-agent-policy", response_class=HTMLResponse, tags=["legal"])
@app.get("/legal/ai-policy", response_class=HTMLResponse, tags=["legal"])
@app.get("/legal/ai-usage", response_class=HTMLResponse, tags=["legal"])
async def render_ai_policy_page(request: Request):
    """Render AI Usage and AI Agent Policy page."""
    return templates.TemplateResponse(
        request=request,
        name="legal.html",
        context={
            "app_name": settings.APP_NAME,
            "active_tab": "ai-policy",
            "page_title": "AI Usage & AI Agent Policy",
            "page_description": "Standards and safety guardrails governing our agent autonomous architecture, tool executions, and RAG grounding.",
        },
    )


@app.get("/legal", response_class=HTMLResponse, tags=["legal"])
async def render_legal_hub_page(request: Request):
    """Render Legal Center overview defaulting to Privacy Policy."""
    return templates.TemplateResponse(
        request=request,
        name="legal.html",
        context={
            "app_name": settings.APP_NAME,
            "active_tab": "privacy",
            "page_title": "Legal Center & Policies",
            "page_description": "Comprehensive legal agreements, privacy guarantees, refund terms, and AI governance policies.",
        },
    )


@app.get("/racing-game", response_class=HTMLResponse, tags=["ui"])
@app.get("/demo/racing", response_class=HTMLResponse, tags=["ui"])
async def render_racing_game_page(request: Request):
    """Render the interactive retro arcade Car Racing Game project demonstrating multi-agent orchestration."""
    return templates.TemplateResponse(
        request=request,
        name="racing_game.html",
        context={
            "app_name": settings.APP_NAME,
        },
    )


@app.get("/api/docs", include_in_schema=False)
async def api_docs_redirect():
    """Redirect /api/docs to OpenAPI Swagger documentation."""
    return RedirectResponse(url="/docs")


@app.get("/api/redoc", include_in_schema=False)
async def api_redoc_redirect():
    """Redirect /api/redoc to OpenAPI ReDoc documentation."""
    return RedirectResponse(url="/redoc")


async def fetch_external_data():
    import httpx
    from fastapi import HTTPException

    EXTERNAL_API_URL = "http://host.docker.internal:11434/api/tags"
    # Initialize the async HTTP client
    async with httpx.AsyncClient() as client:
        try:
            # Make the GET request to the external API
            response = await client.get(EXTERNAL_API_URL)

            print("response=======", str(response.text))

            # Raise an exception if the request returned an error status code
            response.raise_for_status()

            # Return the JSON payload received from the external API
            return response.json()

        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code, 
                detail=f"External API error: {exc}"
            )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=503, 
                detail=f"Could not connect to external server: {exc}"
            )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
