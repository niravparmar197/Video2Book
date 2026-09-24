from bullmq import Queue

from api.config import settings

QUEUE_NAME = "run_book"

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
    across phases is safe because `removeOnComplete=True` frees it once
    the previous phase's job finishes.
    """
    queue = _make_queue()
    try:
        await queue.add(
            QUEUE_NAME, {"book_id": book_id, "url": url, "phase": phase}, {"jobId": book_id}
        )
    finally:
        await queue.close()
