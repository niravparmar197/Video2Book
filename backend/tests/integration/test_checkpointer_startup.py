import asyncio
from unittest.mock import MagicMock

from sqlalchemy import text

import api.main  # noqa: F401  -- import alone triggers ensure_checkpoint_tables()
import api.worker as worker_module
from api.db import engine


def test_importing_api_main_creates_checkpoint_tables():
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "select table_name from information_schema.tables "
                "where table_schema = 'public' and table_name = 'checkpoints'"
            )
        ).fetchall()
    assert rows, "expected langgraph's 'checkpoints' table to exist after api.main import"


def test_worker_main_ensures_checkpoint_tables_before_serving(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(
        worker_module, "ensure_checkpoint_tables", lambda: calls.append("ensure_checkpoint_tables")
    )
    monkeypatch.setattr(worker_module, "init_error_tracking", lambda: calls.append("init_error_tracking"))
    monkeypatch.setattr(worker_module.heartbeat, "write_heartbeat", lambda: None)
    monkeypatch.setattr(worker_module.heartbeat, "clear_heartbeat", lambda: calls.append("clear_heartbeat"))

    fake_worker = MagicMock()
    fake_worker.close = MagicMock(return_value=asyncio.sleep(0))
    monkeypatch.setattr(worker_module, "Worker", lambda *a, **k: fake_worker)

    async def _immediate_wait(self):
        calls.append("serving")

    monkeypatch.setattr(asyncio.Event, "wait", _immediate_wait)

    asyncio.run(worker_module._main())

    assert calls.index("ensure_checkpoint_tables") < calls.index("serving")
    assert "clear_heartbeat" in calls
