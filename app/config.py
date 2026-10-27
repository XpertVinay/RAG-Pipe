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
    LOGS_DIR: Path = Field(default=Path("./data/logs"))
    LOG_BACKUP_DIR: Path = Field(default=Path("./data/logs/backups"))

    # Enterprise Audit Trail, Legal Compliance & Risk Logging
    ENABLE_FILE_LOGGING: bool = True
    LOG_ROTATION_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB
    LOG_ROTATION_BACKUP_COUNT: int = 10
    AUDIT_LOG_RETENTION_DAYS: int = 90
    AUDIT_TAMPER_EVIDENT_CHAIN: bool = True
    COMPLIANCE_DEFAULT_FRAMEWORK: str = "ISO27001_SOC2_GDPR"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_agent"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "rag_agent"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 3600

    # Default LLM & Embedding Providers
    DEFAULT_CHAT_PROVIDER: Literal["ollama", "openai", "anthropic", "openai-compatible", "gemini", "google"] = "ollama"
    DEFAULT_CHAT_MODEL: str = "llama3.2"
    DEFAULT_EMBEDDING_PROVIDER: Literal["ollama", "openai", "huggingface", "gemini", "google"] = "ollama"
    DEFAULT_EMBEDDING_MODEL: str = "nomic-embed-text"

    # Ollama Settings & Local LLM Optimization Flags
    USE_LOCAL_LLM: bool = True
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"
    OLLAMA_TIMEOUT: float = 300.0
    OLLAMA_KEEP_ALIVE: str = "60m"
    OLLAMA_NUM_THREADS: Optional[int] = None
    EMBEDDING_BATCH_SIZE: int = 8

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
    DOCUMENT_PROCESSING_TIMEOUT_SECONDS: int = 600  # 10 mins for recovery of orphaned/crashed jobs after server reboot

    # RabbitMQ Queue Settings for High-Traffic Document Ingestion
    RABBITMQ_ENABLED: bool = True
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"
    RABBITMQ_QUEUE_NAME: str = "document_processing_queue"
    RABBITMQ_CHUNK_QUEUE_NAME: str = "document_chunks_queue"
    RABBITMQ_PREFETCH_COUNT: int = 2
    RABBITMQ_MAX_RETRIES: int = 3
    RABBITMQ_RETRY_DELAY_SECONDS: int = 5
    RABBITMQ_EMBEDDED_WORKER: bool = True
    RABBITMQ_HEARTBEAT: int = 120

    # Multi-Worker Concurrency & Chunk Partitioning (Flag basis configuration)
    ENABLE_CONCURRENT_CHUNK_PROCESSING: bool = False
    WORKER_CONCURRENCY: int = 1
    NUM_CHUNKING_WORKERS: int = 1
    CHUNK_PARTITION_SIZE_MB: float = 3.0
    CHUNK_PARTITION_THRESHOLD_MB: float = 1.0

    # Reverse Proxy / Load Balancer Settings
    LOAD_BALANCER_ENABLED: bool = False
    LOAD_BALANCER_PORT: int = 80
    PROXY_PORT: int = 8181

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

    # LLM Request/Response Logging (Non-Prod / Non-Preprod Only)
    ENABLE_LLM_LOGGING: bool = True
    FORCE_LLM_LOGGING: bool = False  # Allows overriding production ban for debugging
    LLM_LOG_ENVIRONMENTS: str = "local,development,dev,stage,staging,test"
    LLM_LOG_MAX_CHARS: int = 10000
    LLM_LOG_FORMAT: Literal["text", "json"] = "text"

    @field_validator("DEFAULT_CHAT_PROVIDER", "DEFAULT_EMBEDDING_PROVIDER", mode="before")
    @classmethod
    def normalize_provider(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("OLLAMA_NUM_THREADS", mode="before")
    @classmethod
    def parse_optional_threads(cls, v: Any) -> Optional[int]:
        if v is None or v == "" or (isinstance(v, str) and not v.strip()):
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        """Resolve relative SQLite paths and normalize PostgreSQL async driver prefixes."""
        if "sqlite" in v:
            prefix, sep, path_str = v.partition(":///")
            if sep and not path_str.startswith("/"):
                base_dir = Path(__file__).resolve().parent.parent
                abs_path = (base_dir / path_str).resolve()
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                return f"{prefix}:///{abs_path}"
        elif v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        return v

    @property
    def vector_database_url(self) -> str:
        """Return PostgreSQL URL configured for psycopg driver for vector store operations."""
        url = self.DATABASE_URL
        if "postgresql+asyncpg://" in url:
            return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
        elif "postgresql://" in url:
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        elif "postgres://" in url:
            return url.replace("postgres://", "postgresql+psycopg://", 1)
        return url

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

    @property
    def is_llm_logging_enabled(self) -> bool:
        """Determine whether LLM request/response logging is permitted.

        STRICT SAFETY RULE:
        Logging is strictly disabled on preprod and production instances
        to eliminate security risks, secret leakage, and user data exposure.
        """
        if getattr(self, "FORCE_LLM_LOGGING", False):
            return bool(self.ENABLE_LLM_LOGGING)

        env = (self.APP_ENV or "").strip().lower()
        disallowed = {"production", "prod", "preprod", "pre-production", "pre_prod"}
        if env in disallowed:
            return False

        if not self.ENABLE_LLM_LOGGING:
            return False

        allowed = {e.strip().lower() for e in self.LLM_LOG_ENVIRONMENTS.split(",") if e.strip()}
        return env in allowed

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
