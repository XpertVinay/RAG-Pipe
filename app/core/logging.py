"""Structured enterprise logging setup with credential redaction and rotating file audit logging."""

import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict

from app.config import get_settings

settings = get_settings()

SENSITIVE_PATTERNS = [
    re.compile(r"(api[-_]?key\s*[:=]\s*['\"]?)([\w\-]+)(['\"]?)", re.IGNORECASE),
    re.compile(r"(bearer\s+)([\w\-]+)()", re.IGNORECASE),
    re.compile(r"(password\s*[:=]\s*['\"]?)([^'\"\s]+)(['\"]?)", re.IGNORECASE),
    re.compile(r"(secret[-_]?key\s*[:=]\s*['\"]?)([^'\"\s]+)(['\"]?)", re.IGNORECASE),
    re.compile(r"(rzp_(?:live|test)_[a-zA-Z0-9]+)", re.IGNORECASE),
    re.compile(r"(sk-[a-zA-Z0-9]{20,})", re.IGNORECASE),
    re.compile(r"(AIza[0-9A-Za-z-_]{35})", re.IGNORECASE),
]


def redact_sensitive_string(text: str) -> str:
    """Mask credentials, tokens, and sensitive patterns regardless of capture group count."""
    if not isinstance(text, str):
        text = str(text)
    for pattern in SENSITIVE_PATTERNS:
        if pattern.groups >= 3:
            text = pattern.sub(r"\1***REDACTED***\3", text)
        elif pattern.groups == 2:
            text = pattern.sub(r"\1***REDACTED***", text)
        else:
            text = pattern.sub(r"***REDACTED***", text)
    return text


class RedactingFormatter(logging.Formatter):
    """Logging formatter that redacts API keys, credentials, and sensitive tokens."""

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        return redact_sensitive_string(msg)


class JSONLFormatter(logging.Formatter):
    """JSON Lines formatter for audit trail preservation and SIEM ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        if isinstance(record.msg, dict):
            payload = record.msg.copy()
        else:
            payload = {"message": str(record.msg)}

        payload.setdefault("level", record.levelname)
        payload.setdefault("logger", record.name)
        payload.setdefault("timestamp", self.formatTime(record, self.datefmt or "%Y-%m-%dT%H:%M:%SZ"))

        serialized = json.dumps(payload, ensure_ascii=False)
        return redact_sensitive_string(serialized)


def _ensure_logs_dir() -> Path:
    """Ensure logs directory exists with fallback to data/logs or /tmp/logs if permissions fail."""
    candidate_paths = [
        Path(getattr(settings, "LOGS_DIR", "./logs")),
        Path("./data/logs"),
        Path("/tmp/logs"),
    ]
    for p in candidate_paths:
        try:
            p.mkdir(parents=True, exist_ok=True)
            test_file = p / ".write_probe"
            test_file.touch()
            test_file.unlink()
            return p
        except Exception:
            continue
    return Path(getattr(settings, "LOGS_DIR", "./logs"))


def setup_logging() -> logging.Logger:
    """Initialize structured application logger with console and rotating file output."""
    level = logging.DEBUG if settings.DEBUG else logging.INFO
    main_logger = logging.getLogger("rag_agent")
    main_logger.setLevel(level)

    # Avoid duplicate handlers on reloads
    if not main_logger.handlers:
        # 1. Console Stream Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_formatter = RedactingFormatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_handler.setFormatter(console_formatter)
        main_logger.addHandler(console_handler)

        # 2. Main Application Rotating File Handler
        if getattr(settings, "ENABLE_FILE_LOGGING", True):
            try:
                logs_dir = _ensure_logs_dir()
                app_log_path = logs_dir / "app.log"
                file_handler = RotatingFileHandler(
                    filename=str(app_log_path),
                    maxBytes=getattr(settings, "LOG_ROTATION_MAX_BYTES", 10 * 1024 * 1024),
                    backupCount=getattr(settings, "LOG_ROTATION_BACKUP_COUNT", 10),
                    encoding="utf-8",
                )
                file_handler.setLevel(level)
                file_handler.setFormatter(console_formatter)
                main_logger.addHandler(file_handler)
            except Exception as e:
                print(f"[Warning] Failed to initialize file logger: {e}", file=sys.stderr)

    return main_logger


def setup_audit_file_logger() -> logging.Logger:
    """Initialize dedicated audit trail logger writing to audit_trail.jsonl."""
    audit_logger = logging.getLogger("rag_agent.audit_trail")
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False  # Keep audit stream isolated from standard stdout

    if not audit_logger.handlers:
        try:
            logs_dir = _ensure_logs_dir()
            audit_log_path = logs_dir / "audit_trail.jsonl"
            handler = RotatingFileHandler(
                filename=str(audit_log_path),
                maxBytes=getattr(settings, "LOG_ROTATION_MAX_BYTES", 10 * 1024 * 1024),
                backupCount=getattr(settings, "LOG_ROTATION_BACKUP_COUNT", 30),
                encoding="utf-8",
            )
            handler.setFormatter(JSONLFormatter())
            audit_logger.addHandler(handler)
        except Exception as e:
            print(f"[Warning] Failed to initialize audit file logger: {e}", file=sys.stderr)

    return audit_logger


def setup_risk_file_logger() -> logging.Logger:
    """Initialize dedicated business risk logger writing to business_risk.jsonl."""
    risk_logger = logging.getLogger("rag_agent.business_risk")
    risk_logger.setLevel(logging.INFO)
    risk_logger.propagate = False

    if not risk_logger.handlers:
        try:
            logs_dir = _ensure_logs_dir()
            risk_log_path = logs_dir / "business_risk.jsonl"
            handler = RotatingFileHandler(
                filename=str(risk_log_path),
                maxBytes=getattr(settings, "LOG_ROTATION_MAX_BYTES", 10 * 1024 * 1024),
                backupCount=getattr(settings, "LOG_ROTATION_BACKUP_COUNT", 30),
                encoding="utf-8",
            )
            handler.setFormatter(JSONLFormatter())
            risk_logger.addHandler(handler)
        except Exception as e:
            print(f"[Warning] Failed to initialize risk file logger: {e}", file=sys.stderr)

    return risk_logger


logger = setup_logging()
audit_file_logger = setup_audit_file_logger()
risk_file_logger = setup_risk_file_logger()
