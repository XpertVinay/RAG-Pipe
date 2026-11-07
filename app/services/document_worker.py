"""Dedicated RabbitMQ Worker Consumer for Scalable Document Ingestion."""

import asyncio
import json
import signal
from datetime import datetime, timezone
from typing import Any, Optional
try:
    import aio_pika
    from aio_pika.abc import AbstractIncomingMessage
    HAS_AIO_PIKA = True
except ImportError:
    aio_pika = None
    AbstractIncomingMessage = Any  # type: ignore
    HAS_AIO_PIKA = False

from app.config import get_settings
from app.core.logging import logger
from app.ingestion.pipeline import ingestion_pipeline
from app.services.queue_service import queue_service

settings = get_settings()

_worker_running = False
_consumer_task: Optional[asyncio.Task] = None


async def process_incoming_job(message: AbstractIncomingMessage) -> None:
    """Callback handling document ingestion and chunk partition jobs from RabbitMQ with retry & error handling."""
    async with message.process(requeue=False, ignore_processed=True):
        try:
            payload = json.loads(message.body.decode("utf-8"))
            action = payload.get("action", "process_document")
            document_id = payload.get("document_id")
            retry_count = int(payload.get("retry_count", 0))

            if not document_id:
                logger.error("Received RabbitMQ message with missing document_id. Skipping.")
                return

            if action == "process_chunk_partition":
                partition_id = payload.get("partition_id")
                partition_index = payload.get("partition_index", 0)
                total_partitions = payload.get("total_partitions", 1)
                chunk_items = payload.get("chunks", [])

                logger.info(
                    f"[RabbitMQ Worker] Processing chunk partition {partition_index + 1}/{total_partitions} "
                    f"for doc_id={document_id} ({len(chunk_items)} chunks)"
                )
                success = await ingestion_pipeline.process_chunk_partition(
                    partition_id=partition_id,
                    document_id=document_id,
                    partition_index=partition_index,
                    total_partitions=total_partitions,
                    chunk_items=chunk_items,
                )
                if success:
                    logger.info(
                        f"[RabbitMQ Worker] Finished partition {partition_index + 1}/{total_partitions} for {document_id}"
                    )
                else:
                    logger.warning(
                        f"[RabbitMQ Worker] Partition {partition_index + 1}/{total_partitions} reported failure for {document_id}"
                    )
            else:
                logger.info(
                    f"[RabbitMQ Worker] Processing document_id={document_id} (attempt {retry_count + 1})"
                )
                # Execute core ingestion pipeline (parse, chunk, embed, DB update, or partition dispatch)
                success = await ingestion_pipeline.process_document(document_id)
                if success:
                    logger.info(f"[RabbitMQ Worker] Successfully completed document_id={document_id}")
                else:
                    logger.warning(f"[RabbitMQ Worker] Ingestion finished with failed status for document_id={document_id}")

        except Exception as exc:
            max_retries = getattr(settings, "RABBITMQ_MAX_RETRIES", 3)
            logger.error(f"[RabbitMQ Worker] Error processing job: {exc}", exc_info=True)

            try:
                payload = json.loads(message.body.decode("utf-8"))
                doc_id = payload.get("document_id")
                retries = int(payload.get("retry_count", 0)) + 1

                if retries <= max_retries and doc_id:
                    delay = getattr(settings, "RABBITMQ_RETRY_DELAY_SECONDS", 5)
                    action = payload.get("action", "process_document")
                    logger.warning(
                        f"[RabbitMQ Worker] Re-enqueuing {action} for doc {doc_id} in {delay}s (retry {retries}/{max_retries})"
                    )
                    await asyncio.sleep(delay)
                    if action == "process_chunk_partition":
                        await queue_service.enqueue_chunk_partition_job(
                            document_id=doc_id,
                            partition_id=payload.get("partition_id"),
                            partition_index=payload.get("partition_index", 0),
                            total_partitions=payload.get("total_partitions", 1),
                            chunks=payload.get("chunks", []),
                            retry_count=retries,
                        )
                    else:
                        await queue_service.enqueue_document_job(
                            document_id=doc_id,
                            retry_count=retries,
                        )
                else:
                    logger.error(
                        f"[RabbitMQ Worker] Document {doc_id} exceeded max retries ({max_retries}). Job marked permanently failed."
                    )
            except Exception as re_err:
                logger.error(f"[RabbitMQ Worker] Error handling job retry logic: {re_err}")


async def run_document_consumer() -> None:
    """Long-running async loop consuming document ingestion and chunk partition jobs from RabbitMQ."""
    global _worker_running
    _worker_running = True

    queue_name = getattr(settings, "RABBITMQ_QUEUE_NAME", "document_processing_queue")
    chunk_queue_name = getattr(settings, "RABBITMQ_CHUNK_QUEUE_NAME", "document_chunks_queue")
    logger.info(f"Starting RabbitMQ document worker consumer on queues: '{queue_name}', '{chunk_queue_name}'...")

    reconnect_delay = 5.0

    while _worker_running:
        try:
            conn = await queue_service.get_connection()
            if not conn or conn.is_closed:
                await asyncio.sleep(reconnect_delay)
                continue

            channel = await queue_service.get_channel()
            if not channel or channel.is_closed:
                await asyncio.sleep(reconnect_delay)
                continue

            # Declare and consume from primary document queue
            queue = await channel.declare_queue(
                queue_name,
                durable=True,
                auto_delete=False,
            )
            await queue.consume(process_incoming_job)

            # Declare and consume from concurrent chunk partition queue
            chunk_queue = await channel.declare_queue(
                chunk_queue_name,
                durable=True,
                auto_delete=False,
            )
            await chunk_queue.consume(process_incoming_job)

            logger.info(
                f"[RabbitMQ Worker] Ready and waiting for incoming document & chunk partition jobs "
                f"on '{queue_name}' and '{chunk_queue_name}'..."
            )

            # Keep task alive while connection is healthy and worker is running
            while _worker_running and not conn.is_closed:
                await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            logger.info("[RabbitMQ Worker] Consumer loop cancelled.")
            break
        except Exception as e:
            if _worker_running:
                logger.warning(
                    f"[RabbitMQ Worker] Connection lost or error: {e}. Retrying in {reconnect_delay}s..."
                )
                await asyncio.sleep(reconnect_delay)

    logger.info("[RabbitMQ Worker] Document consumer loop stopped.")


async def recover_orphaned_processing_jobs(timeout_seconds: Optional[int] = None) -> int:
    """Reset any documents left stuck in 'processing' status beyond the configured timeout.
    
    Active jobs currently being handled by dedicated worker containers within the valid timeout
    window are preserved.
    """
    from app import database
    from app.models.document import Document
    from sqlalchemy import select

    timeout_sec = timeout_seconds or getattr(settings, "DOCUMENT_PROCESSING_TIMEOUT_SECONDS", 600)
    now = datetime.now(timezone.utc)
    recovered = 0
    try:
        async with database.AsyncSessionLocal() as db:
            result = await db.execute(select(Document).where(Document.status == "processing"))
            stuck_docs = result.scalars().all()
            for doc in stuck_docs:
                last_activity = doc.updated_at or doc.created_at
                if last_activity:
                    if last_activity.tzinfo is None:
                        last_activity = last_activity.replace(tzinfo=timezone.utc)
                    elapsed = (now - last_activity).total_seconds()
                    if elapsed > timeout_sec:
                        doc.status = "failed"
                        doc.error_message = (
                            f"Ingestion timed out after {int(elapsed // 60)}m (exceeded {timeout_sec // 60}m limit) "
                            "or worker was interrupted. Please click reprocess to retry."
                        )
                        recovered += 1
            if recovered > 0:
                await db.commit()
                logger.warning(
                    f"Recovered {recovered} orphaned document(s) stuck in 'processing' beyond {timeout_sec}s. Marked as failed for safe retry."
                )
    except Exception as e:
        logger.warning(f"Error during orphaned job recovery: {e}")
    return recovered


def start_embedded_worker() -> Optional[asyncio.Task]:
    """Start worker consumer as a background task within the FastAPI event loop if enabled."""
    global _consumer_task
    if not HAS_AIO_PIKA or not getattr(settings, "RABBITMQ_ENABLED", True):
        logger.info("RabbitMQ/aio_pika is disabled or not installed. Embedded worker will not start.")
        return None

    if not getattr(settings, "RABBITMQ_EMBEDDED_WORKER", True):
        logger.info("RabbitMQ embedded worker is disabled (standalone worker mode configured).")
        return None

    if _consumer_task is None or _consumer_task.done():
        _consumer_task = asyncio.create_task(run_document_consumer())
        logger.info("Started embedded RabbitMQ document worker background task.")
    return _consumer_task


async def stop_embedded_worker() -> None:
    """Gracefully terminate background consumer."""
    global _worker_running, _consumer_task
    _worker_running = False
    if _consumer_task and not _consumer_task.done():
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
        _consumer_task = None
    await queue_service.close()
    logger.info("Embedded RabbitMQ document worker stopped.")


# Standalone runner for multi-process worker container execution
if __name__ == "__main__":
    import sys
    from app.database import init_db

    async def main():
        logger.info("Starting standalone RabbitMQ Document Processing Worker...")
        await init_db()

        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass  # Windows or non-main thread

        worker_task = asyncio.create_task(run_document_consumer())

        await stop_event.wait()
        logger.info("Shutdown signal received. Stopping worker...")
        await stop_embedded_worker()
        worker_task.cancel()

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker process terminated.")
