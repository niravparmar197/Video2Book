"""Postgres-backed LangGraph checkpointer, shared by the API and worker
processes (sprints/v7). Replaces ai_llm's per-book SQLite checkpoint file
for books created through this API -- ai_llm itself is unaffected: its own
CLI still defaults to a SqliteSaver per output_dir when no checkpointer is
passed in.

A single connection pool is kept for the process's lifetime so the API's
`/events` polling and the worker's job runs can share it safely (psycopg3
connection pools, unlike a bare connection, are safe for concurrent use
across threads).
"""

from functools import lru_cache

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from api.config import settings


def _conninfo() -> str:
    # settings.database_url is a SQLAlchemy URL ("postgresql+psycopg://...");
    # psycopg's own connection string doesn't understand the "+psycopg"
    # driver suffix SQLAlchemy adds.
    return settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache(maxsize=1)
def _pool() -> ConnectionPool:
    return ConnectionPool(
        _conninfo(),
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        min_size=1,
        open=True,
    )


def get_checkpointer() -> PostgresSaver:
    return PostgresSaver(_pool())


def ensure_checkpoint_tables() -> None:
    """Idempotent -- safe to call on every process startup. Creates
    langgraph's checkpoint tables on first run, no-ops after."""
    get_checkpointer().setup()
