"""Real-Time Event Broadcasting Service for Document Ingestion and Chunking.

Supports Server-Sent Events (SSE) streaming to client frontends, eliminating
repetitive polling intervals. Broadcasts status changes across Docker containers
via RabbitMQ Fanout exchange, with seamless in-process fallback.
"""

import asyncio
from datetime import datetime, timezone
import json
from typing import Any, Dict, Optional, Set
import uuid

try:
    import aio_pika
    from aio_pika.abc import AbstractChannel, AbstractConnection, AbstractExchange, AbstractQueue
    HAS_AIO_PIKA = True
except ImportError:
    aio_pika = None
    AbstractChannel = AbstractConnection = AbstractExchange = AbstractQueue = Any  # type: ignore
    HAS_AIO_PIKA = False

from app.config import get_settings
from app.core.logging import logger

settings = get_settings()


class EventBroadcaster:
    """Manages real-time event distribution to SSE subscribers via local queues and RabbitMQ."""

    def __init__(self):
        self._subscribers: Set[asyncio.Queue] = set()
        self._lock: Optional[asyncio.Lock] = None
        self._lock_loop: Optional[asyncio.AbstractEventLoop] = None
        self._process_id = str(uuid.uuid4())
        self._listener_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._exchange_name = getattr(settings, "RABBITMQ_EVENTS_EXCHANGE", "document_events_fanout")

    def _get_lock(self) -> asyncio.Lock:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if self._lock is None or getattr(self, "_lock_loop", None) is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    async def subscribe(self) -> asyncio.Queue:
        """Register a new in-memory subscriber queue for an SSE client."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        async with self._get_lock():
            self._subscribers.add(q)
            logger.debug(f"SSE client subscribed. Total active listeners: {len(self._subscribers)}")
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        """Unregister an SSE client queue."""
        async with self._get_lock():
            self._subscribers.discard(q)
            logger.debug(f"SSE client unsubscribed. Remaining active listeners: {len(self._subscribers)}")

    def _deliver_to_local_subscribers(self, event_data: Dict[str, Any]) -> None:
        """Deliver an event payload to all currently connected local SSE queues."""
        for q in list(self._subscribers):
            try:
                q.put_nowait(event_data)
            except asyncio.QueueFull:
                logger.warning("SSE client queue full. Dropping oldest event.")
                try:
                    q.get_nowait()
                    q.put_nowait(event_data)
                except Exception:
                    pass
            except Exception as e:
                logger.debug(f"Error putting event to client queue: {e}")

    async def broadcast_document_status(
        self,
        document_id: str,
        status: str,
        filename: str = "",
        chunk_count: int = 0,
        file_size: Optional[int] = None,
        error_message: Optional[str] = None,
        user_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Broadcast a document status change (queued, processing, completed, failed).

        Delivers immediately to local SSE connections, and publishes to RabbitMQ fanout
        exchange so all other containers (e.g. web servers) receive the update.
        """
        payload: Dict[str, Any] = {
            "event": "document_status",
            "document_id": document_id,
            "status": status,
            "filename": filename,
            "chunk_count": chunk_count,
            "file_size": file_size,
            "error_message": error_message,
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "origin_id": self._process_id,
        }
        if extra:
            payload.update(extra)

        # 1. Immediately deliver to any local SSE clients attached to this process
        self._deliver_to_local_subscribers(payload)

        # 2. Publish to RabbitMQ fanout exchange if available
        if HAS_AIO_PIKA and getattr(settings, "RABBITMQ_ENABLED", True):
            try:
                from app.services.queue_service import queue_service

                channel = await queue_service.get_channel()
                if channel and not channel.is_closed:
                    exchange = await channel.declare_exchange(
                        self._exchange_name,
                        aio_pika.ExchangeType.FANOUT,
                        durable=True,
                    )
                    body = json.dumps(payload).encode("utf-8")
                    message = aio_pika.Message(
                        body=body,
                        content_type="application/json",
                        delivery_mode=aio_pika.DeliveryMode.NOT_PERSISTENT,
                    )
                    await exchange.publish(message, routing_key="")
                    logger.debug(
                        f"Published status '{status}' for document {document_id} to RabbitMQ exchange '{self._exchange_name}'"
                    )
            except Exception as e:
                logger.debug(f"Note during RabbitMQ status event publish: {e}")

        return payload

    async def _rabbitmq_listener_loop(self) -> None:
        """Background listener that consumes status events from RabbitMQ and forwards to local SSE clients."""
        logger.info(f"Starting RabbitMQ SSE events listener on exchange '{self._exchange_name}'...")
        from app.services.queue_service import queue_service

        while not self._stop_event.is_set():
            try:
                conn = await queue_service.get_connection()
                if not conn or conn.is_closed:
                    await asyncio.sleep(2.0)
                    continue

                channel = await conn.channel()
                exchange = await channel.declare_exchange(
                    self._exchange_name,
                    aio_pika.ExchangeType.FANOUT,
                    durable=True,
                )
                # Auto-delete exclusive queue for this process instance
                queue = await channel.declare_queue(exclusive=True, auto_delete=True)
                await queue.bind(exchange)

                async with queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        if self._stop_event.is_set():
                            break
                        async with message.process(ignore_processed=True):
                            try:
                                data = json.loads(message.body.decode("utf-8"))
                                # Ignore events originated from this process to avoid duplicate delivery
                                if data.get("origin_id") == self._process_id:
                                    continue
                                self._deliver_to_local_subscribers(data)
                            except Exception as parse_err:
                                logger.warning(f"Error parsing RabbitMQ event payload: {parse_err}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._stop_event.is_set():
                    logger.warning(f"RabbitMQ event listener reconnecting after error: {e}")
                    await asyncio.sleep(3.0)

    def start_listener(self) -> None:
        """Start the background RabbitMQ event listener task if enabled."""
        if not HAS_AIO_PIKA or not getattr(settings, "RABBITMQ_ENABLED", True):
            return
        if self._listener_task and not self._listener_task.done():
            return
        self._stop_event.clear()
        self._listener_task = asyncio.create_task(self._rabbitmq_listener_loop())

    async def stop_listener(self) -> None:
        """Stop background RabbitMQ event listener."""
        self._stop_event.set()
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None


event_broadcaster = EventBroadcaster()
