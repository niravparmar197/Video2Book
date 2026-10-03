import os

from bullmq import Queue

from api.config import settings

# env-overridable (sprints/v11) so tests/conftest.py can point at a
# separate queue name -- every integration test that hits POST
# /books/youtube, /retry, or PUT /outline enqueues a REAL job via the real
# Redis connection (never mocked, and never cleaned up afterward), so
# without this isolation every test run permanently pollutes whatever
# queue a real dev/prod worker is consuming from. Found in production:
# 1276 stray test-fixture jobs (fake URLs like "https://youtu.be/1",
# "abc123") backed up a real book behind them, since the worker's
# concurrency is 1.
QUEUE_NAME = os.environ.get("QUEUE_NAME", "run_book")

DEFAULT_JOB_OPTIONS = {
    "attempts": 3,
    "backoff": {"type": "exponential", "delay": 5000},
    "removeOnComplete": True,
    "removeOnFail": False,
}


def _make_queue() -> Queue:
    return Queue(
        QUEUE_NAME,
        {"connection": settings.redis_url, "defaultJobOptions": DEFAULT_JOB_OPTIONS},
    )


async def enqueue_run_book(book_id: str, url: str, phase: str) -> None:
    """Enqueue one run_book job for `book_id`, using the book id as the jobId.

    `phase` is `"plan"`, `"render"`, or `"retry"` -- the worker's
    `process_run_book` dispatches on it. Reusing `book_id` as the jobId
    across phases is safe when the previous phase's job *completed*
    (`removeOnComplete=True` frees the id), but NOT when it *failed*
    (`removeOnFail=False` keeps it around forever) -- BullMQ's `add()` with
    a jobId that already has a terminal job on record does not start a
    fresh attempt cycle; it silently no-ops against the stale job. This is
    exactly the situation `retry_book()` hits every time (it only ever
    calls this after `book.status == "failed"`), so without removing the
    stale job first, `POST /books/{id}/retry` returned 202 but never
    actually re-ran anything -- a real bug found live (sprints/v11).
    Removing any existing job for this id first (best-effort, same pattern
    as cancel_run_book; harmless no-op if none exists) guarantees `add()`
    always starts a genuinely fresh attempt.
    """
    queue = _make_queue()
    try:
        try:
            await queue.remove(book_id)
        except Exception:
            pass
        await queue.add(
            QUEUE_NAME, {"book_id": book_id, "url": url, "phase": phase}, {"jobId": book_id}
        )
    finally:
        await queue.close()


async def cancel_run_book(book_id: str) -> None:
    """Removes the BullMQ job for `book_id` if it's still queued. Best
    effort only, by design: a job the worker has already picked up keeps
    running to its next checkpoint -- this does not interrupt it mid-step
    (sprints/frontend-v2)."""
    queue = _make_queue()
    try:
        await queue.remove(book_id)
    finally:
        await queue.close()
