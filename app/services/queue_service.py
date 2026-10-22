"""RabbitMQ Asynchronous Queue Service for High-Traffic Scalable Document Ingestion."""

import asyncio
import json
import socket
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, Optional
try:
    import aio_pika
    from aio_pika.abc import AbstractChannel, AbstractConnection, AbstractQueue, DeliveryMode
    HAS_AIO_PIKA = True
except ImportError:
    aio_pika = None
    AbstractChannel = AbstractConnection = AbstractQueue = DeliveryMode = Any  # type: ignore
    HAS_AIO_PIKA = False

from app.config import get_settings
from app.core.logging import logger

settings = get_settings()


class QueueService:
    """Manages RabbitMQ async connections, job publishing, and worker consumption with fallback."""

    def __init__(self):
        self._connection: Optional[AbstractConnection] = None
        self._channel: Optional[AbstractChannel] = None
        self._queue: Optional[AbstractQueue] = None
        self._lock: Optional[asyncio.Lock] = None
        self._lock_loop: Optional[asyncio.AbstractEventLoop] = None
        self._is_connecting = False
        self._failed_connection_attempts = 0
        self._last_connect_attempt = 0.0

    def _get_lock(self) -> asyncio.Lock:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if self._lock is None or getattr(self, "_lock_loop", None) is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    async def get_connection(self) -> Optional[AbstractConnection]:
        """Obtain or establish a persistent async RabbitMQ connection."""
        if not HAS_AIO_PIKA or not getattr(settings, "RABBITMQ_ENABLED", True):
            return None

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if self._connection and not self._connection.is_closed:
            if getattr(self, "_connection_loop", None) is current_loop:
                return self._connection
            else:
                self._connection = None
                self._channel = None
                self._queue = None

        async with self._get_lock():
            # Double-check inside lock
            if self._connection and not self._connection.is_closed:
                if getattr(self, "_connection_loop", None) is current_loop:
                    return self._connection
                else:
                    self._connection = None
                    self._channel = None
                    self._queue = None

            try:
                rabbitmq_url = getattr(settings, "RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
                logger.info(f"Connecting to RabbitMQ broker at {rabbitmq_url.split('@')[-1] if '@' in rabbitmq_url else rabbitmq_url}...")
                heartbeat = getattr(settings, "RABBITMQ_HEARTBEAT", 120)
                self._connection = await aio_pika.connect_robust(
                    rabbitmq_url,
                    timeout=getattr(settings, "RABBITMQ_CONNECT_TIMEOUT", 10.0),
                    heartbeat=heartbeat,
                )
                self._connection_loop = current_loop
                self._channel = await self._connection.channel()
                prefetch = getattr(settings, "RABBITMQ_PREFETCH_COUNT", 2)
                await self._channel.set_qos(prefetch_count=prefetch)

                queue_name = getattr(settings, "RABBITMQ_QUEUE_NAME", "document_processing_queue")
                self._queue = await self._channel.declare_queue(
                    queue_name,
                    durable=True,
                    auto_delete=False,
                )
                self._failed_connection_attempts = 0
                logger.info(f"Connected to RabbitMQ. Declared durable queue '{queue_name}' (prefetch={prefetch})")
                return self._connection
            except Exception as e:
                self._failed_connection_attempts += 1
                logger.warning(
                    f"RabbitMQ connection not established ({e}). Will gracefully fallback to in-process execution."
                )
                self._connection = None
                self._channel = None
                self._queue = None
                return None

    async def get_channel(self) -> Optional[AbstractChannel]:
        """Get or create active channel."""
        conn = await self.get_connection()
        if not conn or conn.is_closed:
            return None
        if not self._channel or self._channel.is_closed:
            self._channel = await conn.channel()
            prefetch = getattr(settings, "RABBITMQ_PREFETCH_COUNT", 2)
            await self._channel.set_qos(prefetch_count=prefetch)
        return self._channel

    async def enqueue_document_job(
        self,
        document_id: str,
        background_tasks: Optional[Any] = None,
        retry_count: int = 0,
    ) -> Dict[str, Any]:
        """Publish a document processing job to RabbitMQ with resilient fallback."""
        enqueued_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "document_id": document_id,
            "action": "process_document",
            "retry_count": retry_count,
            "enqueued_at": enqueued_at,
        }

        channel = await self.get_channel()
        queue_name = getattr(settings, "RABBITMQ_QUEUE_NAME", "document_processing_queue")

        if channel and not channel.is_closed:
            try:
                body = json.dumps(payload).encode("utf-8")
                message = aio_pika.Message(
                    body=body,
                    delivery_mode=DeliveryMode.PERSISTENT,
                    content_type="application/json",
                    headers={"retry_count": retry_count},
                )
                await channel.default_exchange.publish(
                    message,
                    routing_key=queue_name,
                )
                logger.info(f"Published document {document_id} to RabbitMQ queue '{queue_name}'")
                return {
                    "status": "queued",
                    "mechanism": "rabbitmq",
                    "queue": queue_name,
                    "document_id": document_id,
                    "enqueued_at": enqueued_at,
                }
            except Exception as e:
                logger.warning(f"Error publishing to RabbitMQ queue: {e}. Falling back to in-process execution.")

        # Fallback to local async background execution
        logger.info(f"Queue fallback: Scheduling document {document_id} via local async background task")
        from app.ingestion.pipeline import ingestion_pipeline

        if background_tasks is not None:
            background_tasks.add_task(ingestion_pipeline.process_document, document_id)
        else:
            asyncio.create_task(ingestion_pipeline.process_document(document_id))

        return {
            "status": "queued",
            "mechanism": "background_task",
            "queue": "in_process_fallback",
            "document_id": document_id,
            "enqueued_at": enqueued_at,
        }

    async def check_health(self) -> Dict[str, Any]:
        """Check status of RabbitMQ broker and queue statistics."""
        if not getattr(settings, "RABBITMQ_ENABLED", True):
            return {
                "status": "disabled",
                "message": "RabbitMQ queue is disabled via configuration.",
                "connected": False,
            }

        try:
            conn = await self.get_connection()
            if conn and not conn.is_closed and self._channel and not self._channel.is_closed:
                queue_name = getattr(settings, "RABBITMQ_QUEUE_NAME", "document_processing_queue")
                # Passive declare inspects existing queue without modifying
                q = await self._channel.declare_queue(queue_name, passive=True)
                msg_count = q.declaration_result.message_count
                consumer_count = q.declaration_result.consumer_count
                return {
                    "status": "healthy",
                    "message": "RabbitMQ broker connected and queue active.",
                    "connected": True,
                    "queue_name": queue_name,
                    "message_count": msg_count,
                    "consumer_count": consumer_count,
                }
            else:
                return {
                    "status": "degraded",
                    "message": "RabbitMQ broker connection not active. In-process fallback is active.",
                    "connected": False,
                    "queue_name": getattr(settings, "RABBITMQ_QUEUE_NAME", "document_processing_queue"),
                    "fallback_active": True,
                }
        except Exception as e:
            return {
                "status": "degraded",
                "message": f"RabbitMQ health check error: {str(e)}. In-process fallback active.",
                "connected": False,
                "error": str(e),
                "fallback_active": True,
            }

    async def close(self) -> None:
        """Gracefully close channels and connection."""
        async with self._get_lock():
            try:
                if self._channel and not self._channel.is_closed:
                    await self._channel.close()
                if self._connection and not self._connection.is_closed:
                    await self._connection.close()
                logger.info("RabbitMQ queue connection closed.")
            except Exception as e:
                logger.warning(f"Note during RabbitMQ connection shutdown: {e}")
            finally:
                self._channel = None
                self._connection = None
                self._queue = None
                self._connection_loop = None
                self._queue = None


queue_service = QueueService()
