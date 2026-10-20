"""Application configuration module using Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from typing import Any, List, Literal, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """System-wide configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # General App Settings
    APP_NAME: str = "Production RAG Agent"
    APP_ENV: str = "development"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    SECRET_KEY: str = "dev-secret-key-change-in-production-rag-agent-key-32"
    ALLOWED_ORIGINS: str = "http://localhost:8000,http://127.0.0.1:8000"
    USE_OPTIMIZED_ASSETS: bool = False

    # JWT & Auth Settings
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ID_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Rate Limiting Settings
    RATE_LIMIT_LOGIN_MAX: int = 100
    RATE_LIMIT_REGISTER_MAX: int = 100
    RATE_LIMIT_REFRESH_MAX: int = 200
    RATE_LIMIT_UPLOAD_MAX: int = 15
    RATE_LIMIT_CHAT_MAX: int = 60

    # Memory Cache & Expiration Settings
    MEMORY_L1_MAX_ITEMS: int = 512
    MEMORY_L1_MAX_BYTES: int = 2097152
    MEMORY_STM_TTL_HOURS: int = 2
    MEMORY_LTM_TTL_DAYS: int = 90
    MEMORY_REVALUATION_INTERVAL_SECONDS: int = 86400

    # Mandate Scheduler Settings
    MANDATE_SYNC_INTERVAL_SECONDS: int = 3600

    # Directory Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = Field(default=Path("./data"))
    UPLOAD_DIR: Path = Field(default=Path("./data/uploads"))
    CHROMA_PERSIST_DIR: Path = Field(default=Path("./data/chroma"))

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/sqlite.db"

    # Default LLM & Embedding Providers
    DEFAULT_CHAT_PROVIDER: Literal["ollama", "openai", "anthropic", "openai-compatible", "gemini", "google"] = "ollama"
    DEFAULT_CHAT_MODEL: str = "llama3.2"
    DEFAULT_EMBEDDING_PROVIDER: Literal["ollama", "openai", "huggingface", "gemini", "google"] = "ollama"
    DEFAULT_EMBEDDING_MODEL: str = "nomic-embed-text"

    # Ollama Settings
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"
    OLLAMA_TIMEOUT: float = 120.0

    # External Provider Keys
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    ANTHROPIC_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None

    # Razorpay Payment Gateway Settings
    RAZORPAY_KEY_ID: str = Field(default="rzp_test_placeholder_key")
    RAZORPAY_KEY_SECRET: Optional[str] = Field(default="placeholder_secret")
    RAZORPAY_CURRENCY: str = Field(default="INR")

    # Ingestion & Chunking
    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 150
    MAX_UPLOAD_SIZE_MB: int = 25
    ALLOWED_EXTENSIONS: str = "pdf,docx,txt,md,csv,html"
    MAX_INGESTION_CONCURRENCY: int = 3

    # RAG Retrieval & LangGraph Workflow
    RETRIEVAL_TOP_K: int = 4
    SIMILARITY_THRESHOLD: float = 0.3
    MAX_RETRIEVAL_RETRIES: int = 2
    ENABLE_QUERY_REWRITING: bool = True
    ENABLE_ANSWER_GRADING: bool = True

    # LangSmith Observability
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGCHAIN_API_KEY: Optional[str] = None
    LANGCHAIN_PROJECT: str = "rag-agent-production"
    REDACT_SENSITIVE_TRACES: bool = True

    @field_validator("DEFAULT_CHAT_PROVIDER", "DEFAULT_EMBEDDING_PROVIDER", mode="before")
    @classmethod
    def normalize_provider(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        """Resolve relative SQLite paths to absolute paths relative to BASE_DIR."""
        if "sqlite" in v:
            prefix, sep, path_str = v.partition(":///")
            if sep and not path_str.startswith("/"):
                base_dir = Path(__file__).resolve().parent.parent
                abs_path = (base_dir / path_str).resolve()
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                return f"{prefix}:///{abs_path}"
        return v

    @property
    def allowed_origins_list(self) -> List[str]:
        """Return allowed CORS origins as a list."""
        raw = self.ALLOWED_ORIGINS.strip()
        if raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def allowed_extensions_list(self) -> List[str]:
        """Return allowed file extensions as a lowercased list."""
        return [ext.strip().lower().lstrip(".") for ext in self.ALLOWED_EXTENSIONS.split(",") if ext.strip()]

    @property
    def max_upload_bytes(self) -> int:
        """Return maximum upload size in bytes."""
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def should_use_optimized_assets(self) -> bool:
        """Determine whether to serve bundled/minified static assets."""
        if self.USE_OPTIMIZED_ASSETS:
            return True
        if self.APP_ENV.lower() == "production":
            dist_bundle = self.BASE_DIR / "app" / "static" / "dist" / "bundle.min.js"
            return dist_bundle.exists()
        return False

    def ensure_directories(self) -> None:
        """Ensure all required local directories exist and have write permissions."""
        import os
        import logging
        log = logging.getLogger("rag_agent")
        for d in (self.DATA_DIR, self.UPLOAD_DIR, self.CHROMA_PERSIST_DIR):
            d.mkdir(parents=True, exist_ok=True)
            if not os.access(d, os.W_OK):
                uid = os.getuid() if hasattr(os, "getuid") else "N/A"
                log.error(
                    f"Directory '{d.resolve()}' is not writable by the current process (UID {uid}). "
                    f"SQLite and document ingestion require write permissions. "
                    f"Fix by running: chmod -R 777 {d.resolve()} or chown -R {uid} {d.resolve()}"
                )


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    settings = Settings()
    settings.ensure_directories()
    return settings
