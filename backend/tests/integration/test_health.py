from types import SimpleNamespace

import pytest

import api.routers.health as health_module
import api.storage as storage_module
from api import heartbeat


@pytest.fixture(autouse=True)
def _worker_heartbeat_alive():
    """Most of this file is about the db/redis/s3 checks -- a live
    heartbeat is the assumed baseline so those tests aren't also
    incidentally asserting on worker staleness. The one test that cares
    about the worker axis specifically clears it itself."""
    heartbeat.write_heartbeat()
    yield
    heartbeat.clear_heartbeat()


def test_health_ok_when_db_redis_s3_and_worker_reachable(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok", "redis": "ok", "s3": "ok", "worker": "ok"}


def test_health_503_when_db_unreachable(monkeypatch, client):
    bad = SimpleNamespace(
        database_url="postgresql+psycopg://x:x@localhost:1/x",
        redis_url=health_module.settings.redis_url,
        output_root=health_module.settings.output_root,
    )
    monkeypatch.setattr(health_module, "settings", bad)

    resp = client.get("/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "error"
    assert body["db"] == "error"
    assert body["redis"] == "ok"
    assert body["s3"] == "ok"
    assert body["worker"] == "ok"


def test_health_503_when_redis_unreachable(monkeypatch, client):
    bad = SimpleNamespace(
        database_url=health_module.settings.database_url,
        redis_url="redis://localhost:1/0",
        output_root=health_module.settings.output_root,
    )
    monkeypatch.setattr(health_module, "settings", bad)

    resp = client.get("/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "error"
    assert body["db"] == "ok"
    assert body["redis"] == "error"
    assert body["s3"] == "ok"
    assert body["worker"] == "ok"


def test_health_503_when_s3_unreachable(monkeypatch, client):
    bad = SimpleNamespace(
        s3_endpoint_url="http://localhost:59999",
        s3_access_key="test",
        s3_secret_key="test",
        s3_region="us-east-1",
        s3_bucket="video2book-books",
    )
    monkeypatch.setattr(storage_module, "settings", bad)

    resp = client.get("/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "error"
    assert body["db"] == "ok"
    assert body["redis"] == "ok"
    assert body["s3"] == "error"
    assert body["worker"] == "ok"


def test_health_503_when_worker_heartbeat_stale(client):
    heartbeat.clear_heartbeat()

    resp = client.get("/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "error"
    assert body["db"] == "ok"
    assert body["redis"] == "ok"
    assert body["s3"] == "ok"
    assert body["worker"] == "stale"
