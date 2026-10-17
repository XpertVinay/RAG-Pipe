"""FastAPI application entrypoint, lifespan, middleware, and route mounting."""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import api_router
from app.config import get_settings
from app.core.exceptions import RAGException, global_exception_handler, rag_exception_handler
from app.core.logging import logger
from app.core.tracing import configure_langsmith_tracing
from app.database import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize local directories, SQLite DB, and tracing."""
    logger.info("Initializing Production RAG Agent...")
    if settings.APP_ENV.lower() == "production" and "dev-secret-key" in settings.SECRET_KEY:
        logger.critical(
            "SECURITY WARNING: Running in production with default insecure SECRET_KEY! "
            "Please configure a cryptographically secure SECRET_KEY in your environment."
        )
    settings.ensure_directories()
    await init_db()
    configure_langsmith_tracing()
    logger.info("Database and storage directories ready.")
    yield
    logger.info("Shutting down RAG Agent...")


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
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: https:; "
        "connect-src 'self' http: https: ws: wss:;"
    )
    return response

# Exception handlers
app.add_exception_handler(RAGException, rag_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# Mount static files and templates
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Mount API routes
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
