from bullmq import Job, Queue

from api.config import settings
from api.models import Book
from api.queue import QUEUE_NAME


def test_cancel_404_for_unknown_book(client, auth_headers):
    resp = client.post("/books/does-not-exist/cancel", headers=auth_headers)
    assert resp.status_code == 404


def test_cancel_requires_auth(client, db_session, user):
    book = Book(url="https://youtu.be/x", status="queued", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    resp = client.post(f"/books/{book.id}/cancel")
    assert resp.status_code == 401


def test_cancel_from_another_user_returns_404(client, db_session, user, make_user):
    book = Book(url="https://youtu.be/x", status="queued", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    _other_user, _key, other_headers = make_user()
    resp = client.post(f"/books/{book.id}/cancel", headers=other_headers)
    assert resp.status_code == 404


def test_cancel_409_when_done(client, db_session, user, auth_headers):
    book = Book(url="https://youtu.be/x", status="done", pdf_path="x.pdf", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    resp = client.post(f"/books/{book.id}/cancel", headers=auth_headers)
    assert resp.status_code == 409


def test_cancel_409_when_already_failed(client, db_session, user, auth_headers):
    book = Book(url="https://youtu.be/x", status="failed", error_message="boom", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    resp = client.post(f"/books/{book.id}/cancel", headers=auth_headers)
    assert resp.status_code == 409


def test_cancel_202_when_in_flight(client, db_session, user, auth_headers):
    book = Book(url="https://youtu.be/x", status="rendering", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    resp = client.post(f"/books/{book.id}/cancel", headers=auth_headers)

    assert resp.status_code == 202
    body = resp.json()
    assert body["id"] == book.id
    assert body["status"] == "failed"
    assert body["error_message"] == "Cancelled by user"


async def test_cancel_removes_the_queued_job(client, db_session, user, auth_headers):
    resp = client.post(
        "/books/youtube",
        json={"url": "https://www.youtube.com/watch?v=abc123"},
        headers=auth_headers,
    )
    book_id = resp.json()["id"]

    resp = client.post(f"/books/{book_id}/cancel", headers=auth_headers)
    assert resp.status_code == 202

    queue = Queue(QUEUE_NAME, {"connection": settings.redis_url})
    try:
        job = await Job.fromId(queue, book_id)
        assert job is None
    finally:
        await queue.close()
