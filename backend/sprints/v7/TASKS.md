# Sprint v7 — Tasks

## Status: Done

- [x] Task 1: `langgraph-checkpoint-postgres` dependency + `api/checkpointer.py` (P0)
  - Acceptance: `langgraph-checkpoint-postgres` added to `pyproject.toml` and installed; `api/checkpointer.py` gains `get_checkpointer() -> PostgresSaver` bound to `settings.database_url`, and `ensure_checkpoint_tables()` that calls the saver's `.setup()` (idempotent — safe to call every startup, creates its tables on first run, no-ops after); unit test calls `ensure_checkpoint_tables()` twice against the real Postgres container and asserts no error, then asserts the checkpointer can `.put`/`.get_tuple` a trivial checkpoint round-trip
  - Files: pyproject.toml, api/checkpointer.py, tests/unit/test_checkpointer.py
  - Completed: 2026-09-25 — verified already implemented on disk:
    `langgraph-checkpoint-postgres>=3.0.0` in `pyproject.toml`;
    `api/checkpointer.py` has `get_checkpointer()` returning a
    `PostgresSaver` bound to a process-lifetime `ConnectionPool` (via
    `@lru_cache`) built from `settings.database_url`, and
    `ensure_checkpoint_tables()` calling `.setup()`. `test_checkpointer.py`
    covers idempotent double-`ensure_checkpoint_tables()` and a real
    `put`/`get_tuple` round trip. Confirmed passing against the real
    Postgres container (`docker compose up -d`).

- [x] Task 2: Wire `ensure_checkpoint_tables()` into API + worker startup (P0)
  - Acceptance: `api/main.py`'s startup (alongside existing `init_error_tracking()`) and `api/worker.py`'s `_main()` both call `ensure_checkpoint_tables()` before serving/consuming; integration test boots the app against a Postgres container with no checkpoint tables yet and confirms they exist afterward
  - Files: api/main.py, api/worker.py, tests/integration/test_checkpointer_startup.py
  - Completed: 2026-09-25 — verified already wired: `api/main.py` calls
    `ensure_checkpoint_tables()` right after `init_error_tracking()` at
    import time; `api/worker.py`'s `_main()` calls it before entering the
    BullMQ consume loop. `tests/integration/test_checkpointer_startup.py`
    covers it. Passing.

- [x] Task 3: `ai_llm` — optional `checkpointer` param on `run_book`/`run_plan`/`resume_book` (P0)
  - Acceptance: all three gain `checkpointer=None`; when `None` (every existing caller — the CLI, every existing `ai_llm` test), behavior is byte-for-byte unchanged (`SqliteSaver.from_conn_string(output_dir/graph_state.sqlite)`, exactly as today); when given a checkpointer object, it's used as-is (caller owns its lifecycle, no `with` block wrapping it) and `thread_id` stays `str(output_dir)` as today; unit test passes a fake in-memory checkpointer and asserts `run_book` uses it instead of creating a SQLite file, while a call with no checkpointer still produces the SQLite file
  - Files: ai_llm/app/graph.py, ai_llm/tests/unit/test_graph.py
  - Completed: 2026-09-25 — verified already implemented: `run_book`,
    `run_plan`, and `resume_book` in `ai_llm/app/graph.py` all take
    `checkpointer=None`; `None` keeps the existing
    `SqliteSaver.from_conn_string(...)` `with`-block path unchanged, a
    supplied checkpointer is used as-is with no `with` wrapping (caller
    owns its lifecycle) and the same `thread_id=str(output_dir)`.

- [x] Task 4: `ai_llm` — `get_progress(output_dir, checkpointer, book_order=None) -> dict` (P0)
  - Acceptance: builds the right graph variant for `book_order` (same `BOOK_ORDER` dispatch `build_graph` already does) bound to the given checkpointer, calls `graph.get_state(config)` for `thread_id=str(output_dir)`, and returns `{"completed_nodes": [...], "current_node": str | None, "next_nodes": [...], "step": int}` derived from the returned `StateSnapshot` (`.next` for upcoming, snapshot metadata for step count, completed = nodes seen minus next); returns `{"completed_nodes": [], "current_node": None, "next_nodes": [], "step": 0}` for a `thread_id` with no checkpoint yet (not an error); unit test with a real checkpointer that's had 2 of N nodes run asserts the returned node lists match
  - Files: ai_llm/app/graph.py, ai_llm/tests/unit/test_graph.py
  - Completed: 2026-09-25 — verified already implemented:
    `get_progress(output_dir, checkpointer, book_order=None, phase="render")`
    in `ai_llm/app/graph.py` dispatches to the right plan/full graph
    variant, reads `graph.get_state(...)`, and returns the documented
    shape, including the empty-state case for a fresh `thread_id`.

- [x] Task 5: `api/ai_llm_bridge.py` re-exports `get_progress` (P0)
  - Acceptance: `ai_llm_bridge.get_progress = _graph.get_progress`, same pattern as the existing three re-exports; a bridge-level test (already-existing pattern in this file's test coverage, if any, or a new minimal one) asserts the name is importable and callable
  - Files: api/ai_llm_bridge.py
  - Completed: 2026-09-25 — verified already present:
    `api/ai_llm_bridge.py` re-exports `get_progress = _graph.get_progress`
    alongside `run_book`/`run_plan`/`resume_book`; covered by
    `tests/unit/test_ai_llm_bridge.py`.

- [x] Task 6: `process_run_book` uses the shared Postgres checkpointer (P0)
  - Acceptance: `api/jobs/run_book.py`'s three ai_llm calls (`run_plan`/`run_book`/`resume_book`) each pass `checkpointer=checkpointer.get_checkpointer()`; existing plan/render/retry unit tests (which monkeypatch the ai_llm bridge functions) updated to assert the checkpointer kwarg is passed; no behavioral change to any existing assertion about status transitions
  - Files: api/jobs/run_book.py, tests/unit/test_run_book_job.py
  - Completed: 2026-09-25 — verified already implemented: all three
    `plan`/`render`/`retry` branches in `process_run_book`
    (`api/jobs/run_book.py`) pass `get_checkpointer()` from
    `api.checkpointer`; `tests/unit/test_run_book_job.py` asserts the
    checkpointer kwarg without changing any existing status-transition
    assertion.

- [x] Task 7: `GET /books/{id}/events` — SSE endpoint, auth + progress loop (P0)
  - Acceptance: new route returns `StreamingResponse(media_type="text/event-stream")`; 404 for an unknown book id or a book belonging to another user (same pattern as `GET /books/{id}`), 401 without auth; while the book's `status` is not `done`/`failed`, polls `ai_llm_bridge.get_progress` (via `asyncio.to_thread`, `EVENTS_POLL_SECONDS` setting, default 2) and yields an SSE `event: progress` / `data: <json>` line only when `current_node`/`completed_nodes` changed since the last yield (no-op ticks aren't sent); once `status` is `done` or `failed`, yields one final `event: done`/`event: failed` message and closes the stream
  - Files: api/routers/books.py, api/config.py, tests/integration/test_books_events.py
  - Completed: 2026-09-25 — verified already implemented:
    `GET /books/{id}/events` in `api/routers/books.py` returns a
    `StreamingResponse`, 404/401 match `GET /books/{id}`'s existing rules,
    `_progress_events` polls via `asyncio.to_thread(ai_llm_get_progress, ...)`
    on `settings.events_poll_seconds` (`EVENTS_POLL_SECONDS`, default 2),
    de-dupes no-op ticks, and emits a final `done`/`failed` event.
    `tests/integration/test_books_events.py` covers auth/404 and the
    event-shape/terminal-event behavior.

- [x] Task 8: Integration test — real multi-node progress over a real SSE stream (P0)
  - Acceptance: a test drives a book through at least 2 real node transitions (stub the underlying LLM/video calls as existing tests already do, but let the real graph + real Postgres checkpointer run) while a concurrent client reads the `/events` stream, and asserts the received events reflect the nodes in the correct order, ending in a `done`/`failed` terminal event; runs against the real Postgres container, not a mocked checkpointer
  - Files: tests/integration/test_books_events.py
  - Completed: 2026-09-25 — verified already implemented as
    `tests/integration/test_books_events_real_pipeline.py`: boots a real
    uvicorn server + real ai_llm graph + real Postgres checkpointer (only
    the LLM/video/compile boundary stubbed, per `AGENTS.md`'s testing
    rule), streams `/events` over a real TCP socket with a real `httpx`
    client concurrently with the run, and asserts the observed node
    sequence is monotonic in real pipeline order and ends in a `done`
    event with `Book.status == "done"`.

- [x] Task 9: README — Postgres checkpointer + `/events` docs (P1)
  - Acceptance: `backend/README.md` documents that LangGraph now checkpoints to Postgres (not per-book SQLite files) for API-created books, that `ai_llm/` run standalone from its own CLI is unaffected, and gives an example `curl -N` (or equivalent) showing a `/events` SSE stream and its event shapes
  - Files: README.md
  - Completed: 2026-09-25 — this was the one real gap found this pass:
    the code/tests for Tasks 1-8 were already complete, but `README.md`'s
    "still deferred" list still named live event streaming and the
    Postgres checkpointer swap as *not* done. Added a "Postgres
    checkpointer + live progress events (v7)" section documenting the
    SQLite-vs-Postgres split, `ensure_checkpoint_tables()` on startup, and
    a `curl -N .../events` example with real event shapes; added a v7
    line to the "what's in" list and removed the two items from "still
    deferred" now that they're shipped.
