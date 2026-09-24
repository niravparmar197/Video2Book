import redis
from fastapi import APIRouter, Response
from sqlalchemy import create_engine, text

from api import heartbeat, storage
from api.config import settings

router = APIRouter()


def _check_db() -> bool:
    try:
        engine = create_engine(settings.database_url, connect_args={"connect_timeout": 2})
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        finally:
            engine.dispose()
    except Exception:
        return False


def _check_redis() -> bool:
    try:
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        return bool(client.ping())
    except Exception:
        return False


@router.get("/health")
def health(response: Response) -> dict:
    db_ok = _check_db()
    redis_ok = _check_redis()
    s3_ok = storage.check_s3()
    worker_ok = heartbeat.is_alive()
    if not (db_ok and redis_ok and s3_ok and worker_ok):
        response.status_code = 503
    return {
        "status": "ok" if db_ok and redis_ok and s3_ok and worker_ok else "error",
        "db": "ok" if db_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "s3": "ok" if s3_ok else "error",
        "worker": "ok" if worker_ok else "stale",
    }
