"""Document ingestion pipeline coordinating parsing, chunking, and vector persistence."""

import os
from pathlib import Path
from typing import Optional
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DocumentParsingError, VectorStoreError
from app.core.logging import logger
from app import database
from app.ingestion.chunker import DocumentChunker
from app.ingestion.parsers import DocumentParser
from app.ingestion.vector_store import vector_store
from app.models.document import Document, DocumentChunk
from app.models.room import RoomDocument
from app.models.memory import MemoryItem


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
                    user_id=doc.user_id,
                    uploader_username=doc.uploader_username,
                    is_persistent=doc.is_persistent_vector if doc.is_persistent_vector is not None else True,
                    is_shared=doc.is_shared if doc.is_shared is not None else False,
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

                # 7. Revaluate any existing memories linked to this document
                try:
                    from app.memory.revaluation import revaluation_engine
                    await revaluation_engine.revaluate_for_document(doc.id, db)
                except Exception as reval_err:
                    logger.warning(f"Post-ingestion memory revaluation note: {reval_err}")

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
    async def delete_document(db: AsyncSession, document_id: str, purge_vectors: bool = False) -> bool:
        """Remove a document record from DB and local storage.
        
        If purge_vectors is False and the document's vector embeddings are marked persistent,
        the embeddings in Chroma remain persistent so other users continue to benefit from them.
        """
        result = await db.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return False

        # Invalidate in-memory L1 cache for this document
        try:
            from app.memory.manager import memory_manager
            memory_manager.l1_cache.invalidate_document(document_id)
        except Exception:
            pass

        # 1. Remove vector embeddings ONLY if purge_vectors is requested OR doc is not persistent
        if purge_vectors or not getattr(doc, "is_persistent_vector", True):
            try:
                vector_store.delete_document(document_id=document_id)
            except Exception as e:
                logger.warning(f"Error removing vectors for {document_id}: {e}")
        else:
            logger.info(
                f"Document {document_id} deleted by user, but vector embeddings remain persistent for shared platform RAG."
            )

        # 2. Remove physical file from disk
        if doc.storage_path and os.path.exists(doc.storage_path):
            try:
                os.remove(doc.storage_path)
            except OSError as e:
                logger.warning(f"Error removing file {doc.storage_path}: {e}")

        # 3. Clean up room associations and memories referencing this document
        try:
            await db.execute(delete(RoomDocument).where(RoomDocument.document_id == document_id))
            await db.execute(
                update(MemoryItem).where(MemoryItem.document_id == document_id).values(document_id=None)
            )
        except Exception as e:
            logger.warning(f"Error unlinking room/memory references for {document_id}: {e}")

        # 4. Delete document row from DB (chunks cascade deleted)
        await db.delete(doc)
        await db.commit()
        return True



ingestion_pipeline = IngestionPipeline()
