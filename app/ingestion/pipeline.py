"""Document ingestion pipeline coordinating parsing, chunking, and vector persistence."""

import os
from pathlib import Path
from typing import Optional
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DocumentParsingError, VectorStoreError
from app.core.logging import logger
from app import database
from app.ingestion.chunker import DocumentChunker
from app.ingestion.parsers import DocumentParser
from app.ingestion.vector_store import vector_store
from app.models.document import Document, DocumentChunk


class IngestionPipeline:
    """Coordinates parsing, splitting, vectorizing, and database persistence."""

    def __init__(self, chunk_size: Optional[int] = None, chunk_overlap: Optional[int] = None):
        self.chunker = DocumentChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    async def process_document(self, document_id: str) -> None:
        """Process an uploaded document in the background."""
        logger.info(f"Starting ingestion for document_id={document_id}")

        async with database.AsyncSessionLocal() as db:
            result = await db.execute(select(Document).where(Document.id == document_id))
            doc = result.scalar_one_or_none()
            if not doc:
                logger.error(f"Document {document_id} not found in database for ingestion.")
                return

            # Mark document as processing
            doc.status = "processing"
            doc.error_message = None
            await db.commit()

            file_path = Path(doc.storage_path)
            if not file_path.exists():
                doc.status = "failed"
                doc.error_message = f"File not found on storage: {file_path}"
                await db.commit()
                return

            try:
                # 1. Parse document into pages
                pages = DocumentParser.parse(file_path=file_path, extension=doc.file_type)

                # 2. Chunk pages into LangChain documents with provenance
                lc_chunks = self.chunker.chunk_document(
                    document_id=doc.id,
                    filename=doc.filename,
                    file_type=doc.file_type,
                    pages=pages,
                )

                if not lc_chunks:
                    raise DocumentParsingError("Document produced no valid text chunks after splitting.")

                # 3. Clean up any existing vectors and DB chunks for idempotency
                try:
                    vector_store.delete_document(document_id=doc.id)
                except Exception as ve:
                    logger.warning(f"Note during vector cleanup for {doc.id}: {ve}")

                await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))

                # 4. Save chunk records to database
                for chunk in lc_chunks:
                    db_chunk = DocumentChunk(
                        id=chunk.metadata.get("chunk_id"),
                        document_id=doc.id,
                        chunk_index=chunk.metadata.get("chunk_index", 0),
                        content=chunk.page_content,
                        chunk_metadata=chunk.metadata,
                    )
                    db.add(db_chunk)

                # 5. Persist to Chroma vector store
                vector_store.add_chunks(lc_chunks)

                # 6. Update document status to completed
                doc.status = "completed"
                doc.chunk_count = len(lc_chunks)
                doc.error_message = None
                await db.commit()
                logger.info(f"Successfully completed ingestion for {doc.filename} ({len(lc_chunks)} chunks)")

            except Exception as e:
                logger.error(f"Ingestion failed for {doc.filename}: {e}", exc_info=True)
                await db.rollback()

                # Clean up vector store if partially inserted
                try:
                    vector_store.delete_document(document_id=doc.id)
                except Exception:
                    pass

                # Mark document as failed
                async with database.AsyncSessionLocal() as err_db:
                    err_res = await err_db.execute(select(Document).where(Document.id == document_id))
                    err_doc = err_res.scalar_one_or_none()
                    if err_doc:
                        err_doc.status = "failed"
                        err_doc.error_message = str(e)
                        await err_db.commit()

    @staticmethod
    async def delete_document(db: AsyncSession, document_id: str) -> bool:
        """Completely remove a document, its local file, DB chunks, and vector store embeddings."""
        result = await db.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return False

        # 1. Remove vector embeddings
        try:
            vector_store.delete_document(document_id=document_id)
        except Exception as e:
            logger.warning(f"Error removing vectors for {document_id}: {e}")

        # 2. Remove physical file from disk
        if doc.storage_path and os.path.exists(doc.storage_path):
            try:
                os.remove(doc.storage_path)
            except OSError as e:
                logger.warning(f"Error removing file {doc.storage_path}: {e}")

        # 3. Delete document row from DB (chunks cascade deleted)
        await db.delete(doc)
        await db.commit()
        return True


ingestion_pipeline = IngestionPipeline()
