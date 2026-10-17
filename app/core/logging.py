"""Structured logging setup with credential redaction."""

import logging
import re
import sys
from typing import Any

from app.config import get_settings

settings = get_settings()

SENSITIVE_PATTERNS = [
    re.compile(r"(api[-_]?key\s*[:=]\s*['\"]?)([\w\-]+)(['\"]?)", re.IGNORECASE),
    re.compile(r"(bearer\s+)([\w\-]+)()", re.IGNORECASE),
    re.compile(r"(password\s*[:=]\s*['\"]?)([^'\"\s]+)(['\"]?)", re.IGNORECASE),
]


class RedactingFormatter(logging.Formatter):
    """Logging formatter that redacts API keys and sensitive tokens."""

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        for pattern in SENSITIVE_PATTERNS:
            msg = pattern.sub(r"\1***REDACTED***\3", msg)
        return msg


def setup_logging() -> logging.Logger:
    """Initialize structured application logger."""
    level = logging.DEBUG if settings.DEBUG else logging.INFO
    logger = logging.getLogger("rag_agent")
    logger.setLevel(level)

    # Avoid duplicate handlers on reloads
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = RedactingFormatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


logger = setup_logging()
