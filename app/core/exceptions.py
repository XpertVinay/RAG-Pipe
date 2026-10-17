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
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.__class__.__name__,
            "message": exc.message,
            "details": exc.details,
        },
    )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Fallback handler to prevent stack traces leaking to clients."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred while processing the request.",
        },
    )
