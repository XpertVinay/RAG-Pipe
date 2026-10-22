#!/usr/bin/env python3
"""CLI Entrypoint for running standalone RabbitMQ Document Processing Worker."""

import asyncio
import logging
import signal
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.core.logging import logger
from app.database import init_db
from app.services.document_worker import (
    recover_orphaned_processing_jobs,
    run_document_consumer,
    stop_embedded_worker,
)

settings = get_settings()


async def main():
    logger.info("Initializing Database for Standalone Document Worker...")
    settings.ensure_directories()
    await init_db()
    await recover_orphaned_processing_jobs()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    consumer_task = asyncio.create_task(run_document_consumer())
    logger.info(
        f"Standalone RabbitMQ Document Worker active on queue '{settings.RABBITMQ_QUEUE_NAME}'. Waiting for jobs..."
    )

    await stop_event.wait()
    logger.info("Shutdown signal received. Gracefully stopping worker...")
    await stop_embedded_worker()
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    logger.info("Worker process exited successfully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
