"""LangSmith tracing configuration and observability integration."""

import os
from typing import Optional
from app.config import get_settings
from app.core.logging import logger

settings = get_settings()


def configure_langsmith_tracing() -> bool:
    """Configure LangSmith tracing environment variables if enabled.

    Returns:
        bool: True if LangSmith tracing is active and configured.
    """
    if not settings.LANGCHAIN_TRACING_V2 or not settings.LANGCHAIN_API_KEY:
        logger.info("LangSmith tracing is disabled or no API key is provided.")
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return False

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT
    os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
    os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT

    logger.info(f"LangSmith tracing enabled for project: {settings.LANGCHAIN_PROJECT}")
    return True


def get_tracing_run_name(query: str) -> str:
    """Generate a clean, sanitized run name for LangSmith traces."""
    clean_query = query.strip()[:40]
    return f"rag_query_{clean_query}"
