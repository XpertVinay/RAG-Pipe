"""Security utilities for file validation, magic signature checks, sanitization, and prompt defense."""

import os
import re
from pathlib import Path
from typing import Optional, Tuple
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

# Blocklist of hazardous executable extensions
BLOCKED_EXECUTABLE_EXTENSIONS = {
    "exe", "bat", "cmd", "sh", "bash", "bin", "elf", "dll", "so", "dylib",
    "py", "pyc", "pyd", "js", "vbs", "vbe", "wsf", "wsh", "ps1", "psm1",
    "jar", "war", "ear", "app", "msi", "scr", "pif", "hta", "cpl",
}

# Magic signatures for binary document formats
MAGIC_SIGNATURES = {
    "pdf": [b"%PDF-"],
    "docx": [b"PK\x03\x04"],  # Standard ZIP container used by Office Open XML
}


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent directory traversal and invalid characters."""
    normalized = filename.replace("\\", "/")
    base_name = os.path.basename(normalized)
    cleaned = re.sub(r"[\\/:\0]", "", base_name)
    cleaned = re.sub(r"[^\w\.-]", "_", cleaned)
    cleaned = cleaned.lstrip(".")
    if not cleaned:
        cleaned = "unnamed_document"
    return cleaned


def validate_file_upload(file: UploadFile, content_length: int, content_bytes: Optional[bytes] = None) -> Tuple[str, str]:
    """Validate uploaded file for extension, MIME signature, size limits, and binary headers.

    Returns:
        Tuple of (sanitized_filename, extension)
    """
    if not file.filename:
        raise FileValidationError("Uploaded file has no filename.")

    sanitized = sanitize_filename(file.filename)
    parts = sanitized.lower().split(".")

    if len(parts) > 1 and any(part in BLOCKED_EXECUTABLE_EXTENSIONS for part in parts[1:]):
        raise FileValidationError(f"File '{file.filename}' contains forbidden executable extension.")

    extension = parts[-1] if len(parts) > 1 else ""

    allowed_exts = settings.allowed_extensions_list
    if not extension or extension not in allowed_exts:
        raise FileValidationError(
            f"File extension '.{extension}' is not permitted. Allowed: {', '.join(allowed_exts)}"
        )

    if content_length > settings.max_upload_bytes:
        raise FileValidationError(
            f"File size exceeds maximum permitted limit of {settings.MAX_UPLOAD_SIZE_MB}MB."
        )

    # Magic byte signature verification if content is provided
    if content_bytes and len(content_bytes) > 0:
        if extension in MAGIC_SIGNATURES:
            expected_signatures = MAGIC_SIGNATURES[extension]
            if not any(content_bytes.startswith(sig) for sig in expected_signatures):
                raise FileValidationError(
                    f"File '{file.filename}' content header does not match expected {extension.upper()} signature."
                )
        elif extension in ["txt", "md", "csv", "html"]:
            # Check for binary null bytes indicative of compiled executables disguised as text
            if b"\x00" in content_bytes[:4096]:
                raise FileValidationError(f"File '{file.filename}' contains unexpected binary data.")

    return sanitized, extension


def verify_safe_path(target_path: Path, base_dir: Path) -> Path:
    """Verify that a path resolves strictly within the specified base directory, preventing path traversal."""
    resolved_target = target_path.resolve()
    resolved_base = base_dir.resolve()
    try:
        resolved_target.relative_to(resolved_base)
    except ValueError:
        raise FileValidationError("Unsafe file path detected: path traversal attempt blocked.")
    return resolved_target


# Prompt injection control markers to redact or neutralize from retrieved text
PROMPT_INJECTION_PATTERNS = [
    r"(?i)<\s*system\s*>",
    r"(?i)<\s*/\s*system\s*>",
    r"(?i)<\|im_start\|>",
    r"(?i)<\|im_end\|>",
    r"(?i)\[INST\]",
    r"(?i)\[/INST\]",
    r"(?i)<<SYS>>",
    r"(?i)<</SYS>>",
    r"(?i)human:\s*",
    r"(?i)assistant:\s*",
]


def sanitize_retrieved_text(text: str) -> str:
    """Sanitize retrieved document text to prevent prompt injection hijacking."""
    if not text:
        return ""
    # Strip dangerous raw control characters
    cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)
    # Neutralize prompt injection delimiter tokens
    for pat in PROMPT_INJECTION_PATTERNS:
        cleaned = re.sub(pat, " ", cleaned)
    # Replace backticks that could break code block formatting
    cleaned = cleaned.replace("```", "'''")
    return cleaned.strip()
