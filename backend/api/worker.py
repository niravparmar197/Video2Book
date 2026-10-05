"""Worker process entrypoint: `python -m api.worker`.

Runs a BullMQ Worker that pulls `run_book` jobs and hands them to
`process_run_book`, which calls ai_llm's pipeline in a thread. Also
writes a heartbeat to Redis on a fixed interval so `GET /health` can
detect a stuck/crashed worker (sprints/v6), and once a day runs the
housekeeping: retention and the Postgres backup.
"""

import asyncio

from bullmq import Worker

from api import heartbeat
from api.backup import run_backup
from api.checkpointer import ensure_checkpoint_tables
from api.config import settings
from api.error_tracking import init_error_tracking
from api.jobs.run_book import LOCK_DURATION_MS, process_run_book
from api.logging import configure_logging, get_logger
from api.queue import QUEUE_NAME
from api.retention import run_retention


async def _heartbeat_loop() -> None:
    while True:
        await asyncio.to_thread(heartbeat.write_heartbeat)
        await asyncio.sleep(settings.worker_heartbeat_interval_seconds)


_HOUSEKEEPING_KEY = "worker:housekeeping"
# How often a worker checks whether housekeeping is due.
_HOUSEKEEPING_CHECK_SECONDS = 600


def _claim_housekeeping() -> bool:
    """True for one worker once per HOUSEKEEPING_INTERVAL_HOURS (a Redis key
    with that TTL), so restarts and several workers don't repeat it."""
    ttl = max(60, int(settings.housekeeping_interval_hours * 3600))
    try:
        return bool(heartbeat._client().set(_HOUSEKEEPING_KEY, "1", nx=True, ex=ttl))
    except Exception:  # noqa: BLE001 - Redis down: skip this round
        return False


def run_housekeeping() -> None:
    """Retention (old books' files, empty folders) and the Postgres backup.
    Each failure is logged; neither may stop the worker."""
    logger = get_logger(step="housekeeping")
    for name, task in (("retention", run_retention), ("backup", run_backup)):
        try:
            task()
        except Exception as error:  # noqa: BLE001
            logger.error(f"{name} failed", extra={"error": str(error)})


async def _housekeeping_loop() -> None:
    while True:
        if await asyncio.to_thread(_claim_housekeeping):
            await asyncio.to_thread(run_housekeeping)
        await asyncio.sleep(_HOUSEKEEPING_CHECK_SECONDS)


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
            "concurrency": settings.worker_concurrency,
        },
    )
    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    housekeeping_task = asyncio.create_task(_housekeeping_loop())

    try:
        await asyncio.Event().wait()
    finally:
        heartbeat_task.cancel()
        housekeeping_task.cancel()
        await asyncio.to_thread(heartbeat.clear_heartbeat)
        await worker.close()


if __name__ == "__main__":
    asyncio.run(_main())
