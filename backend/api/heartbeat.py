"""Worker heartbeat -- a TTL'd Redis key. `GET /health` checks it so a
stuck or crashed worker is detectable within one heartbeat interval
instead of "eventually, when someone notices books have stopped moving."
"""

from datetime import datetime, timezone

import redis

from api.config import settings

HEARTBEAT_KEY = "worker:heartbeat"


def _client() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)


def write_heartbeat() -> None:
    _client().set(
        HEARTBEAT_KEY,
        datetime.now(timezone.utc).isoformat(),
        ex=settings.worker_heartbeat_ttl_seconds,
    )


def clear_heartbeat() -> None:
    _client().delete(HEARTBEAT_KEY)


def is_alive() -> bool:
    try:
        return bool(_client().exists(HEARTBEAT_KEY))
    except Exception:
        return False
