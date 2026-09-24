import pytest
from bullmq import Job, Queue

from api.config import settings
from api.queue import QUEUE_NAME


@pytest.fixture
async def queue():
    q = Queue(QUEUE_NAME, {"connection": settings.redis_url})
    yield q
    await q.close()


async def test_create_book_enqueues_a_run_book_job(client, queue: Queue, auth_headers):
    resp = client.post(
        "/books/youtube",
        json={"url": "https://www.youtube.com/watch?v=abc123"},
        headers=auth_headers,
    )
    book_id = resp.json()["id"]

    job = await Job.fromId(queue, book_id)

    assert job is not None
    assert job.id == book_id
    assert job.data["book_id"] == book_id
    assert job.data["url"] == "https://www.youtube.com/watch?v=abc123"
    assert job.data["phase"] == "plan"
    assert job.opts.get("attempts") == 3
