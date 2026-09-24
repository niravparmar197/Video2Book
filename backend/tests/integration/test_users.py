from api.auth import hash_api_key
from api.models import User


def test_create_user_returns_api_key_once(client, db_session):
    resp = client.post("/users", json={"email": "alice@example.com"})

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
    resp = client.post("/users", json={"email": "not-an-email"})
    assert resp.status_code == 422


def test_create_user_rejects_duplicate_email(client):
    client.post("/users", json={"email": "bob@example.com"})
    resp = client.post("/users", json={"email": "bob@example.com"})
    assert resp.status_code == 409
