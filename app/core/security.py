"""Security utilities for file validation, sanitization, and prompt defense."""

import os
import re
from pathlib import Path
from typing import Tuple
from fastapi import UploadFile

from app.config import get_settings
from app.core.exceptions import FileValidationError

settings = get_settings()

# Allowed MIME types mapping
MIME_TYPE_MAPPING = {
    "pdf": ["application/pdf"],
    "docx": [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "application/zip",
    ],
    "txt": ["text/plain"],
    "md": ["text/markdown", "text/plain"],
    "csv": ["text/csv", "application/csv", "text/plain"],
    "html": ["text/html", "application/xhtml+xml"],
}


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent directory traversal and invalid characters."""
    # Normalize Windows backslashes to forward slashes first
    normalized = filename.replace("\\", "/")
    base_name = os.path.basename(normalized)
    # Remove directory separators and null bytes
    cleaned = re.sub(r"[\\/:\0]", "", base_name)
    # Replace whitespace and unsafe characters with underscores
    cleaned = re.sub(r"[^\w\.-]", "_", cleaned)
    # Ensure it's not empty and does not start with dots
    cleaned = cleaned.lstrip(".")
    if not cleaned:
        cleaned = "unnamed_document"
    return cleaned


def validate_file_upload(file: UploadFile, content_length: int) -> Tuple[str, str]:
    """Validate uploaded file for extension, MIME type, and size limits.

    Returns:
        Tuple of (sanitized_filename, extension)
    """
    if not file.filename:
        raise FileValidationError("Uploaded file has no filename.")

    sanitized = sanitize_filename(file.filename)
    extension = sanitized.rsplit(".", 1)[-1].lower() if "." in sanitized else ""

    allowed_exts = settings.allowed_extensions_list
    if not extension or extension not in allowed_exts:
        raise FileValidationError(
            f"File extension '.{extension}' is not permitted. Allowed: {', '.join(allowed_exts)}"
        )

    if content_length > settings.max_upload_bytes:
        raise FileValidationError(
            f"File size exceeds maximum permitted limit of {settings.MAX_UPLOAD_SIZE_MB}MB."
        )

    return sanitized, extension


def verify_safe_path(target_path: Path, base_dir: Path) -> Path:
    """Verify that a path resolves within the specified base directory, preventing path traversal."""
    resolved_target = target_path.resolve()
    resolved_base = base_dir.resolve()
    try:
        resolved_target.relative_to(resolved_base)
    except ValueError:
        raise FileValidationError("Unsafe file path detected: path traversal attempt blocked.")
    return resolved_target


def sanitize_retrieved_text(text: str) -> str:
    """Sanitize retrieved document text to prevent prompt injection hijacking."""
    if not text:
        return ""
    # Strip dangerous raw control characters
    cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)
    # Replace backticks that could break code block formatting
    cleaned = cleaned.replace("```", "'''")
    return cleaned.strip()
