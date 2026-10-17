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
    DEFAULT_EMBEDDING_PROVIDER: Literal["ollama", "openai", "huggingface", "gemini", "google"] = "gemini"
    DEFAULT_EMBEDDING_MODEL: str = "models/gemini-embedding-001"

    # Ollama Settings
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"
    OLLAMA_TIMEOUT: float = 120.0

    # External Provider Keys
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    ANTHROPIC_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None

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

    @property
    def allowed_extensions_list(self) -> List[str]:
        """Return allowed file extensions as a lowercased list."""
        return [ext.strip().lower().lstrip(".") for ext in self.ALLOWED_EXTENSIONS.split(",") if ext.strip()]

    @property
    def max_upload_bytes(self) -> int:
        """Return maximum upload size in bytes."""
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    def ensure_directories(self) -> None:
        """Ensure all required local directories exist."""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    settings = Settings()
    settings.ensure_directories()
    return settings
