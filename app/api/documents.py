"""API endpoints for document upload, listing, details, deletion, and reprocessing."""

import hashlib
import shutil
import uuid
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.auth import get_optional_user
from app.core.exceptions import EntityNotFoundError, FileValidationError
from app.core.logging import logger
from app.core.rate_limit import RateLimiter
from app.core.security import validate_file_upload, verify_safe_path
from app.database import get_db
from app.ingestion.pipeline import ingestion_pipeline
from app.models.document import Document
from app.models.user import User
from app.schemas.document import (
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResult,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])
settings = get_settings()

document_upload_rate_limiter = RateLimiter(max_requests=15, window_seconds=60)


@router.post(
    "/upload",
    response_model=DocumentUploadResult,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(document_upload_rate_limiter)],
)
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload one or more documents, validate them, and trigger background ingestion."""
    uploaded_docs: List[DocumentResponse] = []
    failed_files: List[dict] = []

    for file in files:
        try:
            # Read first chunk or entire file into memory to compute size and hash
            content = await file.read()
            content_length = len(content)

            sanitized_name, extension = validate_file_upload(file, content_length, content_bytes=content)

            if content_length == 0:
                raise FileValidationError(f"File '{file.filename}' is empty.")

            file_hash = hashlib.sha256(content).hexdigest()

            # Save file to storage directory safely
            doc_id = str(uuid.uuid4())
            target_filename = f"{doc_id}_{sanitized_name}"
            target_path = settings.UPLOAD_DIR / target_filename
            safe_path = verify_safe_path(target_path, settings.UPLOAD_DIR)

            with open(safe_path, "wb") as f:
                f.write(content)

            # Insert document row into database
            doc = Document(
                id=doc_id,
                user_id=current_user.id if current_user else None,
                filename=sanitized_name,
                file_type=extension,
                file_size=content_length,
                storage_path=str(safe_path),
                file_hash=file_hash,
                status="queued",
            )
            db.add(doc)
            await db.flush()

            # Schedule background ingestion
            background_tasks.add_task(ingestion_pipeline.process_document, doc_id)

            uploaded_docs.append(DocumentResponse.model_validate(doc))

        except Exception as e:
            logger.warning(f"Upload failed for file '{file.filename}': {e}")
            failed_files.append({"filename": file.filename or "unknown", "error": str(e)})

    await db.commit()

    message = f"Uploaded {len(uploaded_docs)} file(s) for indexing."
    if failed_files:
        message += f" ({len(failed_files)} file(s) failed validation)"

    return DocumentUploadResult(
        message=message,
        uploaded=uploaded_docs,
        failed=failed_files,
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    status_filter: Optional[str] = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List all documents with optional status filtering and pagination."""
    query = select(Document)
    count_query = select(func.count(Document.id))

    if status_filter:
        query = query.where(Document.status == status_filter)
        count_query = count_query.where(Document.status == status_filter)

    query = query.order_by(Document.created_at.desc()).offset(skip).limit(limit)

    total_res = await db.execute(count_query)
    total = total_res.scalar_one()

    results = await db.execute(query)
    docs = results.scalars().all()

    return DocumentListResponse(
        total=total,
        items=[DocumentResponse.model_validate(d) for d in docs],
    )


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document_details(document_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve details and indexed chunks of a specific document."""
    res = await db.execute(select(Document).where(Document.id == document_id))
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    return DocumentDetailResponse.model_validate(doc)


@router.delete("/{document_id}", status_code=status.HTTP_200_OK)
async def delete_document(
    document_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document, its file on disk, DB chunks, and vector store embeddings."""
    res = await db.execute(select(Document).where(Document.id == document_id))
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    if doc.user_id is not None:
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to delete this document.",
            )
        if doc.user_id != current_user.id and getattr(current_user, "role", "user") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied to delete this document.",
            )

    success = await ingestion_pipeline.delete_document(db, document_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found.")

    return {"message": "Document and associated vectors successfully deleted.", "document_id": document_id}


@router.post("/{document_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def reprocess_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger re-ingestion of an existing document."""
    res = await db.execute(select(Document).where(Document.id == document_id))
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    if doc.user_id is not None:
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to reprocess this document.",
            )
        if doc.user_id != current_user.id and getattr(current_user, "role", "user") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied to reprocess this document.",
            )

    doc.status = "queued"
    doc.error_message = None
    await db.commit()

    background_tasks.add_task(ingestion_pipeline.process_document, document_id)

    return {"message": "Document re-ingestion queued.", "document_id": document_id}
