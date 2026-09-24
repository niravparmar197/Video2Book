from types import SimpleNamespace

import redis

from api import heartbeat
from api.config import settings


def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url)


def test_write_heartbeat_sets_key_with_ttl():
    heartbeat.clear_heartbeat()
    heartbeat.write_heartbeat()

    client = _redis_client()
    assert client.exists(heartbeat.HEARTBEAT_KEY) == 1
    ttl = client.ttl(heartbeat.HEARTBEAT_KEY)
    assert 0 < ttl <= settings.worker_heartbeat_ttl_seconds


def test_clear_heartbeat_removes_key():
    heartbeat.write_heartbeat()
    heartbeat.clear_heartbeat()

    client = _redis_client()
    assert client.exists(heartbeat.HEARTBEAT_KEY) == 0


def test_is_alive_reflects_key_presence():
    heartbeat.clear_heartbeat()
    assert heartbeat.is_alive() is False

    heartbeat.write_heartbeat()
    assert heartbeat.is_alive() is True


def test_is_alive_false_when_redis_unreachable(monkeypatch):
    monkeypatch.setattr(
        heartbeat,
        "settings",
        SimpleNamespace(redis_url="redis://localhost:59999/0", worker_heartbeat_ttl_seconds=45),
    )
    assert heartbeat.is_alive() is False
