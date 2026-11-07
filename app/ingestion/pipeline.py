"""Document ingestion pipeline coordinating parsing, chunking, and vector persistence."""

import asyncio
import math
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.documents import Document as LCDocument

from app.core.exceptions import DocumentParsingError, VectorStoreError
from app.core.logging import logger
from app import database
from app.ingestion.chunker import DocumentChunker
from app.ingestion.parsers import DocumentParser
from app.ingestion.vector_store import vector_store
from app.models.document import Document, DocumentChunk, DocumentPartition, utc_now
from app.models.room import RoomDocument
from app.models.memory import MemoryItem
from app.services.event_broadcaster import event_broadcaster


class IngestionPipeline:
    """Coordinates parsing, splitting, vectorizing, and database persistence."""

    def __init__(self, chunk_size: Optional[int] = None, chunk_overlap: Optional[int] = None):
        self.chunker = DocumentChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    async def process_document(self, document_id: str) -> None:
        """Process an uploaded document in the background with duplicate vector awareness."""
        logger.info(f"Starting ingestion for document_id={document_id}")

        async with database.AsyncSessionLocal() as db:
            doc = None
            for attempt in range(6):
                result = await db.execute(select(Document).where(Document.id == document_id))
                doc = result.scalar_one_or_none()
                if doc:
                    break
                logger.info(
                    f"Document {document_id} not yet visible in DB (attempt {attempt + 1}/6). Retrying in 0.5s..."
                )
                await asyncio.sleep(0.5)

            if not doc:
                logger.error(f"Document {document_id} not found in database for ingestion after retries.")
                return False

            # Check if document is already completed (idempotency guard)
            if doc.status == "completed" and doc.chunk_count > 0:
                logger.info(f"Document {document_id} ({doc.filename}) is already completed with {doc.chunk_count} chunks. Skipping duplicate embedding.")
                return True

            # Mark document as processing and update heartbeat timestamp
            doc.status = "processing"
            doc.error_message = None
            doc.updated_at = utc_now()
            await db.commit()
            await event_broadcaster.broadcast_document_status(
                document_id=doc.id,
                status="processing",
                filename=doc.filename,
                chunk_count=0,
                file_size=doc.file_size,
                user_id=doc.user_id,
            )

            file_path = Path(doc.storage_path)
            if not file_path.exists():
                doc.status = "failed"
                doc.error_message = f"File not found on storage: {file_path}"
                await db.commit()
                await event_broadcaster.broadcast_document_status(
                    document_id=doc.id,
                    status="failed",
                    filename=doc.filename,
                    chunk_count=0,
                    file_size=doc.file_size,
                    error_message=doc.error_message,
                    user_id=doc.user_id,
                )
                return False

            from app.config import get_settings
            current_settings = get_settings()

            # Deduplication Optimization: Check if an identical file was already indexed
            if doc.file_hash:
                try:
                    source_res = await db.execute(
                        select(Document)
                        .where(
                            Document.file_hash == doc.file_hash,
                            Document.file_size == doc.file_size,
                            Document.file_type == doc.file_type,
                            Document.status == "completed",
                            Document.chunk_count > 0,
                            Document.id != doc.id,
                        )
                        .order_by(Document.created_at.desc())
                    )
                    source_doc = source_res.scalars().first()

                    if source_doc:
                        source_chunks_res = await db.execute(
                            select(DocumentChunk)
                            .where(DocumentChunk.document_id == source_doc.id)
                            .order_by(DocumentChunk.chunk_index)
                        )
                        source_chunks = source_chunks_res.scalars().all()

                        if source_chunks:
                            logger.info(
                                f"Identical content hash detected (from source doc {source_doc.id}). "
                                f"Reusing {len(source_chunks)} cached chunks & embeddings for {doc.filename} to avoid CPU/RAM overhead."
                            )
                            # Purge any existing chunks for this doc
                            await asyncio.to_thread(vector_store.delete_document, document_id=doc.id)
                            await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))

                            for sc in source_chunks:
                                meta = dict(sc.chunk_metadata or {})
                                meta["document_id"] = doc.id
                                meta["filename"] = doc.filename
                                meta["user_id"] = doc.user_id
                                meta["uploader_username"] = doc.uploader_username
                                new_chunk_id = f"{doc.id}_chunk_{sc.chunk_index}"
                                meta["chunk_id"] = new_chunk_id

                                db_chunk = DocumentChunk(
                                    id=new_chunk_id,
                                    document_id=doc.id,
                                    chunk_index=sc.chunk_index,
                                    content=sc.content,
                                    chunk_metadata=meta,
                                )
                                db.add(db_chunk)

                            # Copy vector embeddings in vector database without re-invoking LLM embedding provider
                            await asyncio.to_thread(
                                vector_store.copy_document_vectors,
                                source_doc_id=source_doc.id,
                                target_doc_id=doc.id,
                                new_filename=doc.filename,
                            )

                            doc.status = "completed"
                            doc.chunk_count = len(source_chunks)
                            doc.error_message = None
                            doc.updated_at = utc_now()
                            await db.commit()
                            await event_broadcaster.broadcast_document_status(
                                document_id=doc.id,
                                status="completed",
                                filename=doc.filename,
                                chunk_count=doc.chunk_count,
                                file_size=doc.file_size,
                                user_id=doc.user_id,
                            )
                            logger.info(
                                f"Successfully completed ingestion for {doc.filename} via cached vector reuse ({len(source_chunks)} chunks)"
                            )

                            try:
                                from app.memory.revaluation import revaluation_engine
                                await revaluation_engine.revaluate_for_document(doc.id, db)
                            except Exception as reval_err:
                                logger.warning(f"Post-ingestion memory revaluation note: {reval_err}")
                            return
                except Exception as dedupe_err:
                    logger.warning(
                        f"Cached vector reuse skipped due to error: {dedupe_err}. Proceeding with standard embedding pipeline."
                    )

            try:
                # 1. Parse document into pages off the event loop
                pages = await asyncio.to_thread(DocumentParser.parse, file_path=file_path, extension=doc.file_type)

                # 2. Chunk pages into LangChain documents with provenance off the event loop
                lc_chunks = await asyncio.to_thread(
                    self.chunker.chunk_document,
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

                # Multi-Worker Concurrent Chunk Processing Check (flag & threshold managed)
                enable_concurrent = getattr(current_settings, "ENABLE_CONCURRENT_CHUNK_PROCESSING", False)
                num_workers = max(
                    1,
                    getattr(current_settings, "WORKER_CONCURRENCY", 1),
                    getattr(current_settings, "NUM_CHUNKING_WORKERS", 1),
                )
                part_size_mb = max(0.1, getattr(current_settings, "CHUNK_PARTITION_SIZE_MB", 3.0))
                part_thresh_mb = max(0.1, getattr(current_settings, "CHUNK_PARTITION_THRESHOLD_MB", 1.0))
                file_size_mb = (doc.file_size or 0) / (1024 * 1024)

                should_partition = (
                    enable_concurrent
                    and num_workers > 1
                    and (file_size_mb >= part_thresh_mb or len(lc_chunks) >= num_workers * 2)
                    and len(lc_chunks) >= num_workers
                )

                if should_partition:
                    from app.services.queue_service import queue_service

                    # Calculate partition count based on workers and partition size target (e.g. 9MB / 3MB = 3)
                    calc_partitions = max(2, math.ceil(file_size_mb / part_size_mb)) if file_size_mb > 0 else 2
                    num_partitions = min(num_workers, calc_partitions, len(lc_chunks))

                    logger.info(
                        f"Multi-Worker Concurrency Enabled: Dividing {doc.filename} ({file_size_mb:.2f} MB, {len(lc_chunks)} chunks) "
                        f"into {num_partitions} independent chunk partitions across {num_workers} workers."
                    )

                    # 3. Clean up any existing vectors and DB chunks for idempotency
                    try:
                        await asyncio.to_thread(vector_store.delete_document, document_id=doc.id)
                    except Exception as ve:
                        logger.warning(f"Note during vector cleanup for {doc.id}: {ve}")

                    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
                    await db.execute(delete(DocumentPartition).where(DocumentPartition.document_id == doc.id))

                    chunk_dicts = [
                        {"content": c.page_content, "metadata": c.metadata}
                        for c in lc_chunks
                    ]
                    total_c = len(chunk_dicts)
                    part_slice_size = math.ceil(total_c / num_partitions)

                    partitions_created: List[DocumentPartition] = []
                    partition_chunks_map: Dict[int, list] = {}

                    for p_idx in range(num_partitions):
                        start_idx = p_idx * part_slice_size
                        end_idx = min((p_idx + 1) * part_slice_size, total_c)
                        sub_chunks = chunk_dicts[start_idx:end_idx]
                        if not sub_chunks:
                            continue

                        part = DocumentPartition(
                            id=str(uuid.uuid4()),
                            document_id=doc.id,
                            partition_index=p_idx,
                            total_partitions=num_partitions,
                            status="queued",
                            chunk_count=len(sub_chunks),
                        )
                        db.add(part)
                        partitions_created.append(part)
                        partition_chunks_map[p_idx] = sub_chunks

                    doc.status = "processing"
                    doc.updated_at = utc_now()
                    await db.commit()

                    await event_broadcaster.broadcast_document_status(
                        document_id=doc.id,
                        status="processing",
                        filename=doc.filename,
                        chunk_count=0,
                        file_size=doc.file_size,
                        user_id=doc.user_id,
                        extra={"partitions": len(partitions_created), "total_chunks": total_c},
                    )

                    # Dispatch partitions asynchronously across worker containers
                    for p_idx, part in enumerate(partitions_created):
                        await queue_service.enqueue_chunk_partition_job(
                            document_id=doc.id,
                            partition_id=part.id,
                            partition_index=p_idx,
                            total_partitions=len(partitions_created),
                            chunks=partition_chunks_map[p_idx],
                        )

                    logger.info(
                        f"Enqueued {len(partitions_created)} chunk partitions for {doc.filename}. "
                        "Workers will process concurrently and release early."
                    )
                    return True

                # Standard Single-Worker / Sequential Execution Pipeline
                # 3. Clean up any existing vectors and DB chunks for idempotency
                try:
                    await asyncio.to_thread(vector_store.delete_document, document_id=doc.id)
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

                # Update heartbeat before launching embedding batches
                doc.updated_at = utc_now()
                await db.commit()

                # Periodic DB heartbeat during heavy batch embedding jobs to prevent stale job recovery
                async def on_batch_progress(cur_batch: int, tot_batches: int):
                    if cur_batch % 5 == 0 or cur_batch == tot_batches:
                        try:
                            async with database.AsyncSessionLocal() as hb_db:
                                await hb_db.execute(
                                    update(Document)
                                    .where(Document.id == doc.id)
                                    .values(updated_at=utc_now())
                                )
                                await hb_db.commit()
                        except Exception as hb_err:
                            logger.debug(f"Heartbeat DB update notice: {hb_err}")

                # 5. Persist to vector store asynchronously without blocking the event loop
                await vector_store.add_chunks_async(
                    lc_chunks,
                    batch_size=current_settings.EMBEDDING_BATCH_SIZE,
                    on_batch_complete=on_batch_progress,
                )

                # 6. Update document status to completed
                doc.status = "completed"
                doc.chunk_count = len(lc_chunks)
                doc.error_message = None
                doc.updated_at = utc_now()
                await db.commit()
                await event_broadcaster.broadcast_document_status(
                    document_id=doc.id,
                    status="completed",
                    filename=doc.filename,
                    chunk_count=doc.chunk_count,
                    file_size=doc.file_size,
                    user_id=doc.user_id,
                )
                logger.info(f"Successfully completed ingestion for {doc.filename} ({len(lc_chunks)} chunks)")

                # 7. Revaluate any existing memories linked to this document
                try:
                    from app.memory.revaluation import revaluation_engine
                    await revaluation_engine.revaluate_for_document(doc.id, db)
                except Exception as reval_err:
                    logger.warning(f"Post-ingestion memory revaluation note: {reval_err}")

                return True

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
                        await event_broadcaster.broadcast_document_status(
                            document_id=err_doc.id,
                            status="failed",
                            filename=err_doc.filename,
                            chunk_count=0,
                            file_size=err_doc.file_size,
                            error_message=str(e),
                            user_id=err_doc.user_id,
                        )
                return False

    async def process_chunk_partition(
        self,
        partition_id: str,
        document_id: str,
        partition_index: int,
        total_partitions: int,
        chunk_items: list,
    ) -> bool:
        """Process an assigned chunk partition independently on this worker container."""
        logger.info(
            f"[Concurrent Chunk Worker] Processing partition {partition_index + 1}/{total_partitions} "
            f"for doc_id={document_id} ({len(chunk_items)} chunks)"
        )
        from app.config import get_settings
        current_settings = get_settings()

        async with database.AsyncSessionLocal() as db:
            part = None
            try:
                # 1. Update partition status to processing
                part_res = await db.execute(
                    select(DocumentPartition).where(DocumentPartition.id == partition_id)
                )
                part = part_res.scalar_one_or_none()
                if not part:
                    part_res = await db.execute(
                        select(DocumentPartition).where(
                            DocumentPartition.document_id == document_id,
                            DocumentPartition.partition_index == partition_index,
                        )
                    )
                    part = part_res.scalar_one_or_none()

                worker_name = os.environ.get("HOSTNAME", f"worker-{partition_index}")
                if part:
                    part.status = "processing"
                    part.worker_id = worker_name
                    part.updated_at = utc_now()
                    await db.commit()

                # 2. Build LangChain Documents
                lc_docs = [
                    LCDocument(page_content=item["content"], metadata=item.get("metadata", {}))
                    for item in chunk_items
                ]

                # 3. Insert DocumentChunk records into DB
                for c in lc_docs:
                    db_chunk = DocumentChunk(
                        id=c.metadata.get("chunk_id") or f"{document_id}_p{partition_index}_{c.metadata.get('chunk_index', 0)}",
                        document_id=document_id,
                        chunk_index=c.metadata.get("chunk_index", 0),
                        content=c.page_content,
                        chunk_metadata=c.metadata,
                    )
                    db.add(db_chunk)
                await db.commit()

                # 4. Generate embeddings and persist to vector store
                await vector_store.add_chunks_async(
                    lc_docs,
                    batch_size=current_settings.EMBEDDING_BATCH_SIZE,
                )

                # 5. Mark partition completed
                if part:
                    part.status = "completed"
                    part.chunk_count = len(lc_docs)
                    part.updated_at = utc_now()
                    await db.commit()

                logger.info(
                    f"[Concurrent Chunk Worker] Completed partition {partition_index + 1}/{total_partitions} "
                    f"for doc {document_id}. Worker released for next traffic."
                )

                # 6. Check if all partitions for document_id are completed
                tot_res = await db.execute(
                    select(func.count(DocumentPartition.id)).where(DocumentPartition.document_id == document_id)
                )
                total_parts = tot_res.scalar_one()

                comp_res = await db.execute(
                    select(func.count(DocumentPartition.id)).where(
                        DocumentPartition.document_id == document_id,
                        DocumentPartition.status == "completed",
                    )
                )
                completed_parts = comp_res.scalar_one()

                if completed_parts >= total_parts and total_parts > 0:
                    chunks_count_res = await db.execute(
                        select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document_id)
                    )
                    total_chunks = chunks_count_res.scalar_one()

                    doc_res = await db.execute(select(Document).where(Document.id == document_id))
                    doc = doc_res.scalar_one_or_none()
                    if doc and doc.status != "completed":
                        doc.status = "completed"
                        doc.chunk_count = total_chunks
                        doc.error_message = None
                        doc.updated_at = utc_now()
                        await db.commit()

                        await event_broadcaster.broadcast_document_status(
                            document_id=doc.id,
                            status="completed",
                            filename=doc.filename,
                            chunk_count=doc.chunk_count,
                            file_size=doc.file_size,
                            user_id=doc.user_id,
                        )
                        logger.info(
                            f"[Concurrent Chunk Worker] All {total_parts} partitions completed for {doc.filename}. "
                            f"Document marked completed with {total_chunks} chunks."
                        )
                        try:
                            from app.memory.revaluation import revaluation_engine
                            await revaluation_engine.revaluate_for_document(doc.id, db)
                        except Exception as reval_err:
                            logger.warning(f"Post-ingestion memory revaluation note: {reval_err}")

                return True

            except Exception as e:
                logger.error(
                    f"[Concurrent Chunk Worker] Error in partition {partition_index} for doc {document_id}: {e}",
                    exc_info=True,
                )
                await db.rollback()
                try:
                    if part:
                        part.status = "failed"
                        part.error_message = str(e)
                        part.updated_at = utc_now()
                    doc_res = await db.execute(select(Document).where(Document.id == document_id))
                    doc = doc_res.scalar_one_or_none()
                    if doc:
                        doc.status = "failed"
                        doc.error_message = f"Partition {partition_index + 1} error: {e}"
                        doc.updated_at = utc_now()
                    await db.commit()
                    if doc:
                        await event_broadcaster.broadcast_document_status(
                            document_id=doc.id,
                            status="failed",
                            filename=doc.filename,
                            chunk_count=0,
                            error_message=doc.error_message,
                            user_id=doc.user_id,
                        )
                except Exception:
                    pass
                return False

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
