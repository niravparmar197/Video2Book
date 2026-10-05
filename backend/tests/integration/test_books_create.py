import dataclasses
from types import SimpleNamespace

from sqlalchemy import select

import api.routers.books as books_module
from api.config import Settings
from api.config import settings as real_settings
from api.models import Book


def _settings_with_limit(limit: int) -> Settings:
    return dataclasses.replace(real_settings, max_concurrent_books_per_user=limit)


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


def test_create_book_persists_the_estimated_cost(client, db_session, auth_headers, monkeypatch):
    monkeypatch.setattr(
        books_module,
        "ai_llm_estimate_playlist",
        lambda url, chunk_minutes=None: [
            SimpleNamespace(duration_seconds=1200, estimated_cost_usd=1.23)
        ],
    )

    resp = client.post(
        "/books/youtube", json={"url": "https://www.youtube.com/watch?v=abc123"}, headers=auth_headers
    )

    assert resp.status_code == 201
    assert resp.json()["estimated_cost_usd"] == 1.23

    book = db_session.get(Book, resp.json()["id"])
    assert book.estimated_cost_usd == 1.23


def test_create_book_defaults_estimated_cost_to_zero_when_unset(client, db_session, user):
    book = Book(url="https://youtu.be/a", status="queued", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    assert book.estimated_cost_usd == 0.0


def test_create_book_422_over_max_book_hours(client, db_session, auth_headers, monkeypatch):
    budget = dataclasses.replace(books_module.ai_llm_load_settings(), max_book_hours=1)
    monkeypatch.setattr(books_module, "ai_llm_load_settings", lambda: budget)
    monkeypatch.setattr(
        books_module,
        "ai_llm_estimate_playlist",
        lambda url, chunk_minutes=None: [
            SimpleNamespace(duration_seconds=2 * 3600, estimated_cost_usd=0.0)
        ],
    )

    resp = client.post(
        "/books/youtube", json={"url": "https://www.youtube.com/watch?v=abc123"}, headers=auth_headers
    )

    assert resp.status_code == 422
    assert "MAX_BOOK_HOURS" in resp.json()["detail"]
    assert db_session.execute(select(Book)).scalars().first() is None


def test_create_book_422_over_max_book_cost_usd(client, db_session, auth_headers, monkeypatch):
    budget = dataclasses.replace(books_module.ai_llm_load_settings(), max_book_cost_usd=1.0)
    monkeypatch.setattr(books_module, "ai_llm_load_settings", lambda: budget)
    monkeypatch.setattr(
        books_module,
        "ai_llm_estimate_playlist",
        lambda url, chunk_minutes=None: [
            SimpleNamespace(duration_seconds=600, estimated_cost_usd=5.0)
        ],
    )

    resp = client.post(
        "/books/youtube", json={"url": "https://www.youtube.com/watch?v=abc123"}, headers=auth_headers
    )

    assert resp.status_code == 422
    assert "MAX_BOOK_COST_USD" in resp.json()["detail"]
    assert db_session.execute(select(Book)).scalars().first() is None


def test_create_book_triggers_daily_spend_alert_once_threshold_crossed(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr(
        books_module, "settings", dataclasses.replace(real_settings, global_daily_spend_alert_usd=10.0)
    )
    monkeypatch.setattr(
        books_module,
        "ai_llm_estimate_playlist",
        lambda url, chunk_minutes=None: [
            SimpleNamespace(duration_seconds=600, estimated_cost_usd=6.0)
        ],
    )
    calls = []
    monkeypatch.setattr(
        books_module, "capture_message_with_context", lambda message, **kw: calls.append(message)
    )

    for i in range(2):
        resp = client.post(
            "/books/youtube", json={"url": f"https://youtu.be/{i}"}, headers=auth_headers
        )
        assert resp.status_code == 201

    assert len(calls) == 1
    assert "12.00" in calls[0]
    assert "10.00" in calls[0]


def test_create_book_no_alert_while_under_daily_spend_threshold(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr(
        books_module, "settings", dataclasses.replace(real_settings, global_daily_spend_alert_usd=10.0)
    )
    monkeypatch.setattr(
        books_module,
        "ai_llm_estimate_playlist",
        lambda url, chunk_minutes=None: [
            SimpleNamespace(duration_seconds=600, estimated_cost_usd=1.0)
        ],
    )
    calls = []
    monkeypatch.setattr(
        books_module, "capture_message_with_context", lambda message, **kw: calls.append(message)
    )

    for i in range(3):
        resp = client.post(
            "/books/youtube", json={"url": f"https://youtu.be/{i}"}, headers=auth_headers
        )
        assert resp.status_code == 201

    assert calls == []


def test_create_book_returns_422_with_youtubes_reason_for_a_members_only_video(
    client, db_session, auth_headers, monkeypatch
):
    def blocked(url, chunk_minutes=None):
        raise books_module.VideoUnavailableError("This video is available to this channel's members")

    monkeypatch.setattr(books_module, "ai_llm_estimate_playlist", blocked)

    resp = client.post(
        "/books/youtube", json={"url": "https://www.youtube.com/watch?v=WZjSFNPS9Lo"}, headers=auth_headers
    )

    assert resp.status_code == 422
    assert "channel's members" in resp.json()["detail"]
    assert db_session.query(Book).count() == 0  # nothing queued or persisted


def test_create_book_saves_a_chosen_book_type_before_planning(
    client, db_session, auth_headers, monkeypatch, tmp_path
):
    import dataclasses

    from api.ai_llm_bridge import load_genre

    monkeypatch.setattr(books_module, "settings", dataclasses.replace(books_module.settings, output_root=str(tmp_path)))
    monkeypatch.setattr(
        books_module,
        "ai_llm_estimate_playlist",
        lambda url, chunk_minutes=None: [SimpleNamespace(duration_seconds=600, estimated_cost_usd=0.0)],
    )

    resp = client.post(
        "/books/youtube",
        json={"url": "https://www.youtube.com/watch?v=pod1", "genre": "podcast"},
        headers=auth_headers,
    )

    assert resp.status_code == 201
    assert load_genre(tmp_path / resp.json()["id"]) == "podcast"


def test_create_book_rejects_an_unknown_book_type(client, auth_headers):
    resp = client.post(
        "/books/youtube",
        json={"url": "https://www.youtube.com/watch?v=x", "genre": "documentary"},
        headers=auth_headers,
    )

    assert resp.status_code == 422


def test_the_per_user_limit_holds_when_requests_arrive_together(client, make_user, monkeypatch):
    """A load test sent 4 requests at once and all 4 books were created past
    a limit of 3: each counted the in-flight books before any was saved."""
    import time
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    import api.routers.books as books_module

    def slow_estimate(url, chunk_minutes=None):
        time.sleep(0.3)  # the real estimate is a YouTube round trip
        return [SimpleNamespace(duration_seconds=600, estimated_cost_usd=0.0)]

    monkeypatch.setattr(books_module, "ai_llm_estimate_playlist", slow_estimate)
    _, _, headers = make_user()

    def create(_):
        return client.post(
            "/books/youtube", json={"url": "https://www.youtube.com/watch?v=abc"}, headers=headers
        ).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = sorted(pool.map(create, range(4)))

    assert codes == [201, 201, 201, 429]
