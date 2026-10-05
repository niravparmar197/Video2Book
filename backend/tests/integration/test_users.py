from api.auth import hash_api_key
from api.models import User


def test_create_user_returns_api_key_once(client, db_session):
    resp = client.post("/users", json={"email": "alice@example.com", "accept_terms": True})

    assert resp.status_code == 201
    body = resp.json()
    assert "user_id" in body
    assert "api_key" in body
    assert len(body["api_key"]) > 20

    user = db_session.get(User, body["user_id"])
    assert user is not None
    assert user.email == "alice@example.com"
    assert user.api_key_hash == hash_api_key(body["api_key"])
    # the raw key is never stored -- only its hash
    assert user.api_key_hash != body["api_key"]


def test_create_user_rejects_malformed_email(client):
    resp = client.post("/users", json={"email": "not-an-email", "accept_terms": True})
    assert resp.status_code == 422


def test_create_user_rejects_duplicate_email(client):
    client.post("/users", json={"email": "bob@example.com", "accept_terms": True})
    resp = client.post("/users", json={"email": "bob@example.com", "accept_terms": True})
    assert resp.status_code == 409


def _with_settings(monkeypatch, module, **overrides):
    from dataclasses import replace

    monkeypatch.setattr(module, "settings", replace(module.settings, **overrides))


def test_create_user_requires_accepting_the_terms(client, db_session):
    resp = client.post("/users", json={"email": "carol@example.com"})

    assert resp.status_code == 422
    assert db_session.query(User).filter(User.email == "carol@example.com").first() is None


def test_create_user_records_when_the_terms_were_accepted(client, db_session):
    body = client.post("/users", json={"email": "dan@example.com", "accept_terms": True}).json()

    user = db_session.get(User, body["user_id"])
    assert user.terms_accepted_at is not None
    assert user.api_key_created_at is not None


def test_create_user_needs_the_invite_code_when_one_is_set(client, monkeypatch):
    import api.routers.users as users_module

    _with_settings(monkeypatch, users_module, signup_invite_code="letmein")

    missing = client.post("/users", json={"email": "eve@example.com", "accept_terms": True})
    wrong = client.post("/users", json={"email": "eve@example.com", "accept_terms": True, "invite_code": "nope"})
    right = client.post("/users", json={"email": "eve@example.com", "accept_terms": True, "invite_code": "letmein"})

    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert right.status_code == 201


def test_create_user_is_refused_past_the_per_ip_limit(client, monkeypatch):
    import api.routers.users as users_module

    monkeypatch.setattr(users_module, "allow_signup", lambda ip: False)

    resp = client.post("/users", json={"email": "frank@example.com", "accept_terms": True})

    assert resp.status_code == 429


def test_rotating_the_key_invalidates_the_old_one(client, make_user):
    _, _, old_headers = make_user()

    resp = client.post("/users/me/api-key", headers=old_headers)

    assert resp.status_code == 200
    new_headers = {"X-API-Key": resp.json()["api_key"]}
    assert client.get("/books", headers=old_headers).status_code == 401
    assert client.get("/books", headers=new_headers).status_code == 200


def test_an_expired_key_is_refused_but_can_still_be_rotated(client, make_user, db_session, monkeypatch):
    from datetime import datetime, timedelta, timezone

    import api.auth as auth_module

    _with_settings(monkeypatch, auth_module, api_key_max_age_days=30)
    user, _, headers = make_user()
    user.api_key_created_at = datetime.now(timezone.utc) - timedelta(days=31)
    db_session.commit()

    refused = client.get("/books", headers=headers)
    rotated = client.post("/users/me/api-key", headers=headers)

    assert refused.status_code == 401
    assert "expired" in refused.json()["detail"]
    assert rotated.status_code == 200
    assert client.get("/books", headers={"X-API-Key": rotated.json()["api_key"]}).status_code == 200


def test_deleting_the_account_removes_the_user_and_their_books(client, make_user, db_session, monkeypatch):
    import api.book_deletion as deletion_module
    from api.models import Book

    removed = []
    monkeypatch.setattr(deletion_module, "remove_book_files", lambda book: removed.append(book.id))
    user, _, headers = make_user()
    book = Book(url="https://youtu.be/x", status="done", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    book_id, user_id = book.id, user.id

    resp = client.delete("/users/me", headers=headers)

    assert resp.status_code == 204
    db_session.expire_all()
    assert db_session.get(User, user_id) is None
    assert db_session.get(Book, book_id) is None
    assert removed == [book_id]


def test_deleting_the_account_is_refused_while_a_book_is_being_made(client, make_user, db_session):
    from api.models import Book

    user, _, headers = make_user()
    db_session.add(Book(url="https://youtu.be/x", status="rendering", user_id=user.id))
    db_session.commit()

    assert client.delete("/users/me", headers=headers).status_code == 409
