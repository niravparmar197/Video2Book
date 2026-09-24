from types import SimpleNamespace

import api.routers.books as books_module
from api.config import settings as real_settings


def _settings_with_limit(limit: int) -> SimpleNamespace:
    return SimpleNamespace(
        database_url=real_settings.database_url,
        redis_url=real_settings.redis_url,
        output_root=real_settings.output_root,
        max_concurrent_books_per_user=limit,
    )


def _signup(client, email: str) -> dict:
    resp = client.post("/users", json={"email": email})
    assert resp.status_code == 201
    return {"X-API-Key": resp.json()["api_key"]}


def test_two_users_cannot_see_each_others_books(client):
    alice_headers = _signup(client, "alice@example.com")
    bob_headers = _signup(client, "bob@example.com")

    create_resp = client.post(
        "/books/youtube",
        json={"url": "https://www.youtube.com/watch?v=alice-video"},
        headers=alice_headers,
    )
    assert create_resp.status_code == 201
    book_id = create_resp.json()["id"]

    # Alice can see her own book.
    assert client.get(f"/books/{book_id}", headers=alice_headers).status_code == 200

    # Bob gets a 404, not a 403 -- no existence leak -- for Alice's book.
    assert client.get(f"/books/{book_id}", headers=bob_headers).status_code == 404
    assert client.get(f"/books/{book_id}/outline", headers=bob_headers).status_code == 404
    assert client.get(f"/books/{book_id}/pdf", headers=bob_headers).status_code == 404
    assert client.post(f"/books/{book_id}/retry", headers=bob_headers).status_code == 404
    assert client.put(f"/books/{book_id}/outline", json=[], headers=bob_headers).status_code == 404


def test_rate_limit_blocks_the_nth_plus_one_book_then_recovers(client, monkeypatch, db_session):
    monkeypatch.setattr(books_module, "settings", _settings_with_limit(2))
    headers = _signup(client, "carol@example.com")

    ids = []
    for i in range(2):
        resp = client.post(
            "/books/youtube", json={"url": f"https://youtu.be/{i}"}, headers=headers
        )
        assert resp.status_code == 201
        ids.append(resp.json()["id"])

    blocked = client.post(
        "/books/youtube", json={"url": "https://youtu.be/one-too-many"}, headers=headers
    )
    assert blocked.status_code == 429

    # Mark one of the in-flight books "done" directly -- it should free up
    # a slot for the next create, same as a worker completing it would.
    # A Core UPDATE (not an ORM get()+mutate()+commit()) avoids touching
    # this session's identity map for a row it never loaded.
    from sqlalchemy import update

    from api.models import Book

    db_session.execute(update(Book).where(Book.id == ids[0]).values(status="done"))
    db_session.commit()

    recovered = client.post(
        "/books/youtube", json={"url": "https://youtu.be/after-one-finishes"}, headers=headers
    )
    assert recovered.status_code == 201
