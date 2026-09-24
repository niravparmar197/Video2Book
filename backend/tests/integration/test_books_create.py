from types import SimpleNamespace

from sqlalchemy import select

import api.routers.books as books_module
from api.config import settings as real_settings
from api.models import Book


def _settings_with_limit(limit: int) -> SimpleNamespace:
    return SimpleNamespace(
        database_url=real_settings.database_url,
        redis_url=real_settings.redis_url,
        output_root=real_settings.output_root,
        max_concurrent_books_per_user=limit,
    )


def test_create_book_returns_201_and_queued_status(client, db_session, user, auth_headers):
    resp = client.post(
        "/books/youtube",
        json={"url": "https://www.youtube.com/watch?v=abc123"},
        headers=auth_headers,
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "queued"
    assert body["pdf_path"] is None
    assert body["error_message"] is None

    book = db_session.get(Book, body["id"])
    assert book is not None
    assert book.status == "queued"
    assert book.url == "https://www.youtube.com/watch?v=abc123"
    assert book.user_id == user.id


def test_create_book_persists_a_row_per_request(client, db_session, auth_headers):
    client.post(
        "/books/youtube", json={"url": "https://www.youtube.com/watch?v=one"}, headers=auth_headers
    )
    client.post(
        "/books/youtube", json={"url": "https://www.youtube.com/watch?v=two"}, headers=auth_headers
    )

    books = db_session.execute(select(Book)).scalars().all()
    assert len(books) == 2


def test_create_book_rejects_malformed_url(client, auth_headers):
    resp = client.post("/books/youtube", json={"url": "not-a-url"}, headers=auth_headers)
    assert resp.status_code == 422


def test_create_book_rejects_missing_url(client, auth_headers):
    resp = client.post("/books/youtube", json={}, headers=auth_headers)
    assert resp.status_code == 422


def test_create_book_rejects_missing_api_key(client):
    resp = client.post("/books/youtube", json={"url": "https://www.youtube.com/watch?v=abc123"})
    assert resp.status_code == 401


def test_create_book_rejects_invalid_api_key(client):
    resp = client.post(
        "/books/youtube",
        json={"url": "https://www.youtube.com/watch?v=abc123"},
        headers={"X-API-Key": "not-a-real-key"},
    )
    assert resp.status_code == 401


def test_create_book_429_at_concurrent_limit(client, db_session, user, auth_headers, monkeypatch):
    monkeypatch.setattr(books_module, "settings", _settings_with_limit(2))

    for i in range(2):
        resp = client.post(
            "/books/youtube",
            json={"url": f"https://www.youtube.com/watch?v={i}"},
            headers=auth_headers,
        )
        assert resp.status_code == 201

    resp = client.post(
        "/books/youtube",
        json={"url": "https://www.youtube.com/watch?v=one-too-many"},
        headers=auth_headers,
    )
    assert resp.status_code == 429

    books = db_session.execute(select(Book).where(Book.user_id == user.id)).scalars().all()
    assert len(books) == 2  # the 429'd request never created a row


def test_create_book_done_and_failed_books_dont_count_toward_limit(
    client, db_session, user, auth_headers, monkeypatch
):
    monkeypatch.setattr(books_module, "settings", _settings_with_limit(1))

    db_session.add_all(
        [
            Book(url="https://youtu.be/a", status="done", user_id=user.id),
            Book(url="https://youtu.be/b", status="failed", user_id=user.id),
        ]
    )
    db_session.commit()

    resp = client.post(
        "/books/youtube", json={"url": "https://youtu.be/c"}, headers=auth_headers
    )
    assert resp.status_code == 201
