# Sprint v2 — Tasks

## Status: Done

- [x] Task 1: Structured JSON logging setup (P0)
  - Acceptance: `api/logging.py` configures stdlib `logging` with a JSON formatter (fields at minimum: `ts`, `level`, `message`) and exposes `get_logger(**context)` returning a `LoggerAdapter` that merges `context` (e.g. `book_id`, `step`) into every record; wired into `api/main.py` (FastAPI startup) and `api/worker.py` (entrypoint); a unit test captures a log call via `caplog`/a custom handler and asserts the emitted record is valid JSON containing the passed `book_id`
  - Files: api/logging.py, api/main.py, api/worker.py, tests/unit/test_logging.py
  - Completed: 2026-09-24 — `JsonFormatter` plus a `ContextLoggerAdapter`
    subclass (the stdlib `LoggerAdapter.process` *overwrites* any per-call
    `extra=`, it doesn't merge — needed a custom `process()` that merges
    bound context with call-site `extra` so e.g. `step` and `status` can
    coexist). `configure_logging()` is idempotent (no-ops if the root
    logger already has handlers) and called once from both `api/main.py`
    and `api/worker.py`. 2 unit tests.

- [x] Task 2: Log `POST /books/youtube` and `GET /books/{id}` with book_id/step context (P0)
  - Acceptance: creating a book logs a JSON line with `step="create"` and the new `book_id`; fetching a book logs a JSON line with `step="get"` and that `book_id`; verified by asserting on captured log output in an integration test, not by inspecting response bodies
  - Files: api/routers/books.py, tests/integration/test_books_logging.py
  - Completed: 2026-09-24 — added a shared `log_stream` pytest fixture in
    `tests/conftest.py` (attaches a `JsonFormatter`-handler to the
    `video2book` logger for the test's duration) plus a `parse_log_lines`
    helper, reused by Tasks 2 and 3's tests. 2 integration tests.

- [x] Task 3: Log the worker's status transitions (P0)
  - Acceptance: `process_run_book` logs one JSON line per transition (`queued→running`, `running→done`, `running→failed`) each carrying `book_id` and `step="run_book"`; the failure log includes the exception message but never the raw `DATABASE_URL`/`REDIS_URL`/any LLM API key; unit test monkeypatches `ai_llm_run_book` to fail and asserts the failure log line's fields, including that no configured secret substring appears in it
  - Files: api/jobs/run_book.py, tests/unit/test_run_book_job.py
  - Completed: 2026-09-24 — logs `status: running` before the call,
    `status: done` on success, `status: failed` + the exception text only
    on the final attempt (a non-final attempt logs a `warning` with
    `attempt`/`attempts` instead, no status-changed line, matching v1's
    "stays running" behavior). 2 new tests, one asserting
    `settings.database_url`/`settings.redis_url` never appear in the
    captured log text.

- [x] Task 4: `GET /health` checks DB + Redis connectivity (P0)
  - Acceptance: with both reachable, returns 200 `{"status": "ok", "db": "ok", "redis": "ok"}`; with Postgres unreachable (test points `DATABASE_URL` at a closed port) returns 503 with `"db": "error"`; same for Redis; neither check ever raises past the handler (both wrapped in their own try/except)
  - Files: api/routers/health.py, api/main.py, tests/integration/test_health.py
  - Completed: 2026-09-24 — **found and fixed a real hang**: the first test
    run against `postgresql+psycopg://x:x@localhost:1/x` (an intentionally
    closed port, to test the down-path) hung indefinitely instead of
    failing fast — psycopg has no default connect timeout, and Windows
    doesn't RST a connection to an unlisted low port quickly. Fixed by
    passing `connect_args={"connect_timeout": 2}` to `create_engine` in
    `_check_db`; Redis's check already had `socket_connect_timeout=2`.
    Also added `pytest-timeout` (`timeout = 30` in `pyproject.toml`) as a
    permanent safety net so a future hang fails the run instead of
    blocking indefinitely. 3 integration tests (healthy, db-down,
    redis-down), each swapping `api.routers.health.settings` for a fake
    `SimpleNamespace` rather than mocking the check functions themselves.

- [x] Task 5: `GET /books/{id}/pdf` serves the rendered file (P0)
  - Acceptance: for a `done` book with an existing `pdf_path`, returns 200 with `Content-Type: application/pdf` and the file's bytes; returns 404 for an unknown `book_id`; returns 404 (not 200 with an empty body) for a book that exists but is `queued`/`running`/`failed`
  - Files: api/routers/books.py, tests/integration/test_books_pdf.py
  - Completed: 2026-09-24 — `FileResponse`, 404 on unknown id, wrong
    status, or a `pdf_path` that no longer exists on disk (checked
    explicitly rather than letting `FileResponse` surface its own error).
    4 integration tests, including a real temp PDF file written to disk
    and read back byte-for-byte.

- [x] Task 6: README updates for /health and /books/{id}/pdf (P1)
  - Acceptance: `backend/README.md` documents `curl`ing `/health` and downloading a finished PDF via `GET /books/{id}/pdf`, and notes the JSON log format contributors should expect on stdout
  - Files: README.md
  - Completed: 2026-09-24 — new "Operability (v2)" section with worked
    `curl` examples and a sample log line; "What's in v1 / v2 / what's
    not" section replaces v1's now-stale scope note.

## Verification summary

- 31/31 tests passing (18 from v1 + 13 new), all against real
  Postgres/Redis containers — no DB or queue mocking.
- `bandit -r api -ll`: clean, 0 issues.
- Live smoke test: real `uvicorn` process, `curl /health` → 200 all-ok,
  `curl /books/unknown/pdf` → 404.

## Deferred to v3+ (see PRD "Out of Scope")

Outline review, retry, `/books/{id}/events`, the Postgres checkpointer
swap for LangGraph, S3 storage, auth, and the rest of
backend/AGENTS.md's production-readiness checklist.
