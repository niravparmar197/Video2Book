import os

# Must be set before any `api.*` module is imported anywhere in the process,
# since api.config.Settings reads os.environ at import time.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://video2book:video2book@localhost:5433/video2book_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("OUTPUT_ROOT", "./test_output")
# sprints/v11: isolates test-enqueued BullMQ jobs from a real dev/prod
# worker's queue -- same REDIS_URL (Redis is cheap to share), different
# queue name, so tests never sit in front of real work and are never
# processed by a real worker either. See api/queue.py's QUEUE_NAME comment.
os.environ.setdefault("QUEUE_NAME", "run_book_test")

import io
import json
import logging
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api.routers.books as books_module
from api.auth import generate_api_key, hash_api_key
from api.db import SessionLocal, engine
from api.logging import JsonFormatter
from api.main import app
from api.models import Base, User


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture(autouse=True)
def _default_playlist_estimate(monkeypatch):
    """POST /books/youtube now estimates a playlist before creating a Book
    (sprints/v8) -- a real network call to YouTube ai_llm's own
    estimate_playlist makes. Stubbed to a small in-budget result by default
    (never a real call, per AGENTS.md's testing rule) so every existing
    test that creates a book doesn't need its own stub; a test that cares
    about the estimate (over-budget rejection, the daily spend alert)
    overrides this with its own monkeypatch.setattr call."""

    def _fake_estimate_playlist(url, chunk_minutes=None):
        return [SimpleNamespace(duration_seconds=600, estimated_cost_usd=0.0)]

    monkeypatch.setattr(books_module, "ai_llm_estimate_playlist", _fake_estimate_playlist)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def log_stream():
    """Captures JSON log lines emitted through api.logging's `video2book`
    logger during the test, independent of pytest's own log capture."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("video2book")
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def parse_log_lines(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


@pytest.fixture
def make_user(db_session):
    """Factory: make_user() -> (User, raw_api_key, {"X-API-Key": raw_api_key})."""

    def _make() -> tuple[User, str, dict]:
        raw_key = generate_api_key()
        user = User(email=f"{uuid.uuid4()}@example.com", api_key_hash=hash_api_key(raw_key))
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user, raw_key, {"X-API-Key": raw_key}

    return _make


@pytest.fixture
def _user_and_key(make_user) -> tuple:
    return make_user()


@pytest.fixture
def user(_user_and_key) -> User:
    return _user_and_key[0]


@pytest.fixture
def auth_headers(_user_and_key) -> dict:
    return _user_and_key[2]
