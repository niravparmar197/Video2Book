"""Sign-ups per IP per hour, counted in Redis.

Each account may run MAX_CONCURRENT_BOOKS_PER_USER books at once, so
unlimited sign-ups let one person multiply that and drain the shared free
LLM quota. A fixed one-hour window per IP (INCR + EXPIRE) is enough to stop
scripted sign-ups without bothering a real person.
"""

from datetime import datetime, timezone

import redis

from api.config import settings
from api.logging import get_logger

_WINDOW_SECONDS = 3600


def _client() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)


def allow_signup(ip: str) -> bool:
    """Count this sign-up for `ip`; False once the hour's limit is passed.

    Fails open when Redis is unreachable: sign-up still needs the invite
    code (when one is set), and a Redis outage should not lock out new users.
    """
    limit = settings.signup_limit_per_ip_per_hour
    if limit <= 0:
        return True
    hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    key = f"signup:{ip}:{hour}"
    try:
        client = _client()
        count = client.incr(key)
        if count == 1:
            client.expire(key, _WINDOW_SECONDS)
    except Exception as error:  # noqa: BLE001 - see docstring
        get_logger(step="signup").warning("sign-up limit unavailable", extra={"error": str(error)})
        return True
    return count <= limit
