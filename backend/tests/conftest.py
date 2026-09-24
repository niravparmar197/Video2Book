import os

# Must be set before any `api.*` module is imported anywhere in the process,
# since api.config.Settings reads os.environ at import time.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://video2book:video2book@localhost:5433/video2book_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("OUTPUT_ROOT", "./test_output")

import io
import json
import logging
import uuid

import pytest
from fastapi.testclient import TestClient

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
