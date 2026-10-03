from bullmq import Job, Queue

from api.config import settings
from api.models import Book
from api.queue import QUEUE_NAME


def test_retry_404_for_unknown_book(client, auth_headers):
    resp = client.post("/books/does-not-exist/retry", headers=auth_headers)
    assert resp.status_code == 404


def test_retry_requires_auth(client, db_session, user):
    book = Book(url="https://youtu.be/x", status="failed", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    resp = client.post(f"/books/{book.id}/retry")
    assert resp.status_code == 401


def test_retry_from_another_user_returns_404(client, db_session, user, make_user):
    book = Book(url="https://youtu.be/x", status="failed", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    _other_user, _key, other_headers = make_user()
    resp = client.post(f"/books/{book.id}/retry", headers=other_headers)
    assert resp.status_code == 404


def test_retry_409_unless_failed(client, db_session, user, auth_headers):
    book = Book(url="https://youtu.be/x", status="rendering", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    resp = client.post(f"/books/{book.id}/retry", headers=auth_headers)
    assert resp.status_code == 409


def test_retry_202_when_failed(client, db_session, user, auth_headers):
    book = Book(url="https://youtu.be/x", status="failed", error_message="boom", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    resp = client.post(f"/books/{book.id}/retry", headers=auth_headers)

    assert resp.status_code == 202
    body = resp.json()
    assert body["id"] == book.id
    assert body["status"] == "failed"  # unchanged until the worker picks up the job


async def test_retry_enqueues_retry_phase(client, db_session, user, auth_headers):
    book = Book(url="https://youtu.be/x", status="failed", error_message="boom", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    client.post(f"/books/{book.id}/retry", headers=auth_headers)

    queue = Queue(QUEUE_NAME, {"connection": settings.redis_url})
    try:
        job = await Job.fromId(queue, book.id)
        assert job is not None
        assert job.data["phase"] == "retry"
    finally:
        await queue.close()


async def test_retry_after_a_prior_job_for_this_id_still_processes(
    client, db_session, user, auth_headers
):
    """sprints/v11: a real bug found live. `POST /books/{id}/retry` is only
    ever called after a book already failed once -- meaning a BullMQ job
    for this exact id (jobId=book_id) can already exist on Redis in a
    terminal state (removeOnFail=False keeps failed jobs around forever).
    BullMQ's add() with a pre-existing jobId does NOT start a fresh attempt
    cycle -- it silently keeps the old job's data, so retry returned 202
    but the worker never actually re-ran anything. Reproduces the core
    mechanism directly: a job already exists for this id (any prior data),
    then retry_book's enqueue must make a job with THIS retry's phase
    retrievable afterward, not the stale prior one.
    """
    book = Book(url="https://youtu.be/x", status="failed", error_message="boom", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    queue = Queue(QUEUE_NAME, {"connection": settings.redis_url})
    try:
        # Simulates the stale terminal job a real prior "render" phase run
        # would leave behind for this exact book_id.
        await queue.add(
            QUEUE_NAME, {"book_id": book.id, "url": book.url, "phase": "render"}, {"jobId": book.id}
        )

        resp = client.post(f"/books/{book.id}/retry", headers=auth_headers)
        assert resp.status_code == 202

        job = await Job.fromId(queue, book.id)
        assert job is not None
        assert job.data["phase"] == "retry", (
            "retry's fresh job must win -- a stale prior job for the same "
            "id must not silently block it"
        )
    finally:
        await queue.close()
