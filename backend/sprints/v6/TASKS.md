# Sprint v6 — Tasks

## Status: Done

- [x] Task 1: Settings + `sentry-sdk` dependency (P0)
  - Acceptance: `api/config.py` gains `sentry_dsn` (default `""`, env-overridable), `sentry_environment` (default `"development"`), `worker_heartbeat_interval_seconds` (default 15), `worker_heartbeat_ttl_seconds` (default 45); `sentry-sdk` added to `pyproject.toml` and installed
  - Files: api/config.py, pyproject.toml, .env.example
  - Completed: 2026-09-25 — verified already implemented: `Settings`
    (api/config.py) has `sentry_dsn` (`""` default, env-overridable via
    `SENTRY_DSN`), `sentry_environment` (`"development"` default),
    `worker_heartbeat_interval_seconds` (15) and
    `worker_heartbeat_ttl_seconds` (45). `sentry-sdk>=2.0.0` present in
    `pyproject.toml` and importable. `.env.example` documents all four.

- [x] Task 2: `api/error_tracking.py` — init + capture helper (P0)
  - Acceptance: `init_error_tracking()` calls `sentry_sdk.init(dsn=..., environment=...)` only when `settings.sentry_dsn` is truthy, and is a complete no-op otherwise (no network I/O attempted, verified by asserting `sentry_sdk.init` is never called when `sentry_dsn=""`); `capture_exception_with_context(exc, **context)` calls `sentry_sdk.set_tag`/`set_context` for each kwarg then `sentry_sdk.capture_exception(exc)`, and is safe to call even when the SDK was never initialized; unit tests monkeypatch `sentry_sdk.capture_exception`/`set_tag` and assert the call sequence/args, never hitting a real Sentry endpoint
  - Files: api/error_tracking.py, tests/unit/test_error_tracking.py
  - Completed: 2026-09-25 — verified already implemented and covered by
    4 unit tests (`tests/unit/test_error_tracking.py`), all passing:
    `sentry_sdk.init` skipped when `sentry_dsn=""`, called with
    `dsn`/`environment` when set, `capture_exception_with_context`
    tags-then-captures, and is safe to call pre-init. No real Sentry
    endpoint touched.

- [x] Task 3: FastAPI global exception handler (P0)
  - Acceptance: `api/main.py` registers `@app.exception_handler(Exception)`; an unhandled exception in any route logs an error-level structured log line (existing `api/logging.py`), calls `capture_exception_with_context(exc, path=request.url.path)`, and still returns a `500` JSON response — verified with a route that deliberately raises, asserting the 500 response, the log line, and the mocked Sentry call all happen
  - Files: api/main.py, tests/integration/test_error_tracking.py
  - Completed: 2026-09-25 — verified already implemented:
    `unhandled_exception_handler` in `api/main.py` logs error-level,
    calls `capture_exception_with_context(exc, path=request.url.path)`,
    returns 500 JSON. Covered by
    `tests/integration/test_error_tracking.py::test_unhandled_exception_returns_500_logs_and_captures_to_sentry`
    (passing) against a deliberately-raising route.

- [x] Task 4: Worker captures final-attempt failures to Sentry (P0)
  - Acceptance: in `process_run_book`'s existing final-attempt failure branch (sprints/v1 Task 6), alongside the existing error-level log, `capture_exception_with_context(exc, book_id=book_id, phase=phase)` is called; a non-final attempt (which only warns, never marks `failed`) does *not* call it; unit test monkeypatches `sentry_sdk.capture_exception` and asserts it's called exactly once, only on the final attempt, with `book_id`/`phase` tags set
  - Files: api/jobs/run_book.py, tests/unit/test_run_book_job.py
  - Completed: 2026-09-25 — verified already implemented at
    `api/jobs/run_book.py:175`, called only from the final-attempt
    branch. Covered by
    `test_process_run_book_final_attempt_captures_to_sentry` and
    `test_process_run_book_non_final_attempt_does_not_capture_to_sentry`
    (both passing).

- [x] Task 5: Worker heartbeat — write + clear on shutdown (P0)
  - Acceptance: `api/worker.py` runs a background `asyncio` task that writes `SETEX worker:heartbeat WORKER_HEARTBEAT_TTL_SECONDS <iso timestamp>` to Redis every `WORKER_HEARTBEAT_INTERVAL_SECONDS`, and deletes that key on a clean shutdown (the existing `finally: await worker.close()`); a test runs the heartbeat loop for one tick against the real Redis container and asserts the key exists with a TTL close to the configured value, then asserts it's gone after the equivalent of a clean shutdown
  - Files: api/worker.py, tests/unit/test_worker_heartbeat.py
  - Completed: 2026-09-25 — verified already implemented: `api/heartbeat.py`
    (`write_heartbeat`/`clear_heartbeat`/`is_alive`) plus `api/worker.py`'s
    `_heartbeat_loop` background task, cancelled and cleared in the
    existing `finally` block alongside `worker.close()`. 4 unit tests
    against the real Redis container, all passing.

- [x] Task 6: `GET /health` reports heartbeat freshness (P0)
  - Acceptance: `/health` response gains `"worker": "ok"`/`"stale"`; `"ok"` when the `worker:heartbeat` Redis key exists (i.e. hasn't expired), `"stale"` when it's missing; missing/stale worker flips the overall response to `503`, same pattern as the existing db/redis/s3 checks; tests cover both states against the real Redis container (set the key manually for "ok", ensure it's absent for "stale")
  - Files: api/routers/health.py, tests/integration/test_health.py
  - Completed: 2026-09-25 — verified already implemented: `/health` in
    `api/routers/health.py` includes `"worker": "ok"/"stale"` via
    `heartbeat.is_alive()`, folded into the existing 503-on-any-failure
    logic. `test_health_ok_when_db_redis_s3_and_worker_reachable` and
    `test_health_503_when_worker_heartbeat_stale` both pass against the
    real Redis container.

- [x] Task 7: README — Sentry setup, heartbeat, and the new `/health` field (P1)
  - Acceptance: `backend/README.md` documents `SENTRY_DSN` (optional, disabled by default), what context gets attached to captured exceptions, the heartbeat mechanism, and that starting the API without also running `python -m api.worker` means `/health` will correctly report `"worker": "stale"`
  - Files: README.md
  - Completed: 2026-09-25 — verified already implemented: README's
    "Error tracking + worker heartbeat (v6)" section documents
    `SENTRY_DSN`/`SENTRY_ENVIRONMENT` (off by default, no network I/O),
    the `book_id`/`phase`/`path` tags attached to captured exceptions,
    and the heartbeat interval/TTL mechanism including the
    worker-not-running → `"stale"` case.

**Sprint verification (2026-09-25)**: all 7 tasks' code, tests, and docs
were already present in the working tree but `TASKS.md` had never been
updated to reflect it (still read "Not Started" with every box
unchecked). Re-verified for real rather than trusting the stale
checklist: full suite `python -m pytest tests/ -v` — 90/90 passing,
including every v6-specific test (error tracking unit + integration,
worker heartbeat unit, health integration, run_book Sentry-capture
unit). `python -m bandit -r api/ -ll` — clean, 0 issues.
`python -m pip_audit` — 0 findings against any project dependency
(including `sentry-sdk`); the only findings are 12 advisories against
`pip` 24.0 itself (the global Python install's packaging tool, not a
project dependency) — attempted `pip install --upgrade pip` but the
system Python at `c:\python312` denied the uninstall
(`WinError 5: Access is denied`), which needs admin rights and is an
environment issue outside this sprint's scope, not a regression
introduced here.
