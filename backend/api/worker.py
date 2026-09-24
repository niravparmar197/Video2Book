"""Worker process entrypoint: `python -m api.worker`.

Runs a BullMQ Worker that pulls `run_book` jobs and hands them to
`process_run_book`, which calls ai_llm's pipeline in a thread. Also
writes a heartbeat to Redis on a fixed interval so `GET /health` can
detect a stuck/crashed worker (sprints/v6).
"""

import asyncio

from bullmq import Worker

from api import heartbeat
from api.checkpointer import ensure_checkpoint_tables
from api.config import settings
from api.error_tracking import init_error_tracking
from api.jobs.run_book import LOCK_DURATION_MS, process_run_book
from api.logging import configure_logging
from api.queue import QUEUE_NAME


async def _heartbeat_loop() -> None:
    while True:
        await asyncio.to_thread(heartbeat.write_heartbeat)
        await asyncio.sleep(settings.worker_heartbeat_interval_seconds)


async def _main() -> None:
    configure_logging()
    init_error_tracking()
    ensure_checkpoint_tables()

    worker = Worker(
        QUEUE_NAME,
        process_run_book,
        {
            "connection": settings.redis_url,
            "lockDuration": LOCK_DURATION_MS,
            "concurrency": 1,
        },
    )
    heartbeat_task = asyncio.create_task(_heartbeat_loop())

    try:
        await asyncio.Event().wait()
    finally:
        heartbeat_task.cancel()
        await asyncio.to_thread(heartbeat.clear_heartbeat)
        await worker.close()


if __name__ == "__main__":
    asyncio.run(_main())
