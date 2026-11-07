"""Custom exception classes and FastAPI exception handlers."""

from typing import Any, Dict, Optional
from fastapi import Request, status
from fastapi.responses import JSONResponse


class RAGException(Exception):
    """Base exception for application errors."""

    def __init__(self, message: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class FileValidationError(RAGException):
    """Raised when an uploaded file fails validation."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=status.HTTP_400_BAD_REQUEST, details=details)


class DocumentParsingError(RAGException):
    """Raised when document extraction or parsing fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        code = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)
        super().__init__(message, status_code=code, details=details)


class VectorStoreError(RAGException):
    """Raised when vector store operations fail."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, details=details)


class ProviderUnavailableError(RAGException):
    """Raised when an LLM or embedding provider is unavailable or misconfigured."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=status.HTTP_503_SERVICE_UNAVAILABLE, details=details)


class EntityNotFoundError(RAGException):
    """Raised when a requested resource is not found."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=status.HTTP_404_NOT_FOUND, details=details)


async def rag_exception_handler(request: Request, exc: RAGException) -> JSONResponse:
    """FastAPI error handler for RAGException hierarchy."""
    import asyncio
    try:
        from app.services.audit_service import audit_service
        domain = "third_party_failure" if isinstance(exc, ProviderUnavailableError) else (
            "core_logic" if isinstance(exc, (VectorStoreError, DocumentParsingError)) else "exception_handling"
        )
        asyncio.create_task(
            audit_service.log_event(
                domain_category=domain,
                event_name=f"handled_exception_{exc.__class__.__name__.lower()}",
                execution_status="failed",
                error_type=exc.__class__.__name__,
                error_message=exc.message,
                metadata_payload={"path": request.url.path, "method": request.method, "details": exc.details},
            )
        )
    except Exception:
        pass

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.__class__.__name__,
            "message": exc.message,
            "detail": exc.message,
            "details": exc.details,
        },
    )


async def validation_exception_handler(request: Request, exc: Any) -> JSONResponse:
    """Error handler for FastAPI/Pydantic validation errors ensuring readable and JSON-safe messages."""
    error_messages = []
    sanitized_errors = []
    errors = getattr(exc, "errors", lambda: [])()
    for err in errors:
        loc = [str(l) for l in err.get("loc", []) if l != "body"]
        field = ".".join(loc)
        msg = str(err.get("msg", "Invalid value"))
        # Strip internal Pydantic prefix "Value error, " if present
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, "):]
        if field:
            error_messages.append(f"{field}: {msg}")
        else:
            error_messages.append(msg)
        sanitized_errors.append({
            "loc": loc,
            "msg": msg,
            "type": str(err.get("type", "value_error")),
        })
    joined_msg = "; ".join(error_messages) or "Input validation failed."
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "RequestValidationError",
            "message": joined_msg,
            "detail": joined_msg,
            "details": sanitized_errors,
        },
    )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Fallback handler to prevent stack traces leaking to clients and record critical audit trail event."""
    import asyncio
    try:
        from app.services.audit_service import audit_service
        asyncio.create_task(
            audit_service.log_event(
                domain_category="exception_handling",
                event_name="unhandled_server_exception",
                execution_status="critical",
                error_type=exc.__class__.__name__,
                error_message=str(exc),
                metadata_payload={"path": request.url.path, "method": request.method},
                compliance_status="REVIEW_REQUIRED",
                compliance_remark="Auto-flagged unhandled server exception requiring root-cause inspection",
            )
        )
    except Exception:
        pass

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred while processing the request.",
            "detail": "An unexpected error occurred while processing the request.",
        },
    )
