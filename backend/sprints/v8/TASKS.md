# Sprint v8 — Tasks

## Status: Done

- [x] Task 1: `api/ai_llm_bridge.py` re-exports `estimate_playlist` + `load_settings` (P0)
  - Acceptance: the bridge imports `app.estimate` and `app.config` via the same sys.path mechanism already used for `app.graph`; re-exports `estimate_playlist = _estimate.estimate_playlist` and `load_settings = _config.load_settings` — function references, not values baked in at import time, matching the existing `run_book`/`run_plan`/`resume_book`/`get_progress` re-export pattern (so a monkeypatched env var takes effect on the next call without reimporting anything); unit test asserts both names are importable/callable, and that `load_settings().max_book_hours`/`.max_book_cost_usd` equal calling `ai_llm`'s own `app.config.load_settings()` directly (proves it's a pass-through, not a second copy)
  - Files: api/ai_llm_bridge.py, tests/unit/test_ai_llm_bridge.py
  - Completed: 2026-09-25 — generalized the bridge's existing
    `_import_graph()` into a reusable `_import(name)` and used it for
    `app.estimate`/`app.config` too (dropped the now-redundant
    `_import_graph`, `_graph = _import("app.graph")` instead). Both new
    names are plain re-exported function references. 2 new tests:
    importability/signature for `estimate_playlist`, and
    `load_settings().max_book_hours`/`.max_book_cost_usd` equality against
    a direct `import app.config` call (the `app` package is already cached
    in `sys.modules` from the bridge's own import, so this works without
    re-adding `ai_llm/` to `sys.path`).

- [x] Task 2: `Book.estimated_cost_usd` column + Alembic migration (P0)
  - Acceptance: `Book` gains `estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)`; a new Alembic revision adds the column with `server_default="0"` (so it backfills any existing rows without a manual data migration) and a downgrade that drops it; `alembic upgrade head` runs clean against the real Postgres test database; a test creates a `Book` without specifying the field and asserts it reads back as `0.0`, and one specifying a value round-trips it
  - Files: api/models.py, alembic/versions/9b3f2c7a1d4e_book_estimated_cost.py, tests/integration/test_books_create.py
  - Completed: 2026-09-25 — added the column and revision
    `9b3f2c7a1d4e` (`down_revision = 27e9a46bfeda`). Verified `alembic
    upgrade head` against both the real dev DB and the real
    `video2book_test` DB; found and fixed a pre-existing, unrelated piece
    of drift while doing so -- `video2book_test` had an orphaned
    `alembic_version` row stamped at an old revision with none of the
    actual tables present (tests create/drop schema via
    `Base.metadata.create_all`/`drop_all` directly, bypassing Alembic
    entirely, so nothing had ever caught this). Dropped the stray table
    and reran the full migration chain from scratch against that database
    to confirm it applies cleanly end to end. 2 new tests: a book created
    with an explicit cost round-trips it; one created with none defaults
    to `0.0`.

- [x] Task 3: `POST /books/youtube` — upfront budget check before creating a Book/job (P0)
  - Acceptance: `create_book` calls `asyncio.to_thread(ai_llm_bridge.estimate_playlist, str(payload.url))` before touching the database; sums `duration_seconds / 3600` and `estimated_cost_usd` across every returned video; if total hours exceeds `ai_llm_bridge.load_settings().max_book_hours` or total cost exceeds `.max_book_cost_usd`, raises `HTTPException(422, ...)` naming the exceeded limit and the measured value, with no `Book` row created and no job enqueued (no `--force` equivalent — see PRD); otherwise creates the `Book` with `estimated_cost_usd` set to the summed total and enqueues the plan job exactly as today. Integration test: monkeypatching `ai_llm_bridge.estimate_playlist` to return an over-hours (and separately an over-cost) result asserts `422` and that no `Book` row exists afterward for that user; a normal (in-budget) result still returns `201` with `estimated_cost_usd` populated on the response
  - Files: api/routers/books.py, api/schemas.py, tests/integration/test_books_create.py
  - Completed: 2026-09-25 — `_check_over_budget()` raises 422 (naming
    `MAX_BOOK_HOURS`/`MAX_BOOK_COST_USD` and the measured value) before
    any DB write; `BookResponse` gained `estimated_cost_usd`. Real
    knock-on effect: every existing test that posts to `/books/youtube`
    (7 test files) would now make a real network call to YouTube via
    `estimate_playlist` -- fixed with a new autouse `_default_playlist_estimate`
    fixture in `tests/conftest.py` that stubs `books_module.ai_llm_estimate_playlist`
    to a small in-budget fake for every test by default (never a real
    call, per `AGENTS.md`'s testing rule), which individual tests override
    with their own `monkeypatch.setattr` when they care about the estimate
    itself. Also had to fix two existing tests' settings stubs
    (`test_auth_lifecycle.py`, `test_books_create.py`'s
    `_settings_with_limit` helper) that reconstructed a hand-rolled
    `SimpleNamespace` missing the fields the new code path reads --
    switched both to `dataclasses.replace(real_settings, ...)` so a future
    settings field can't silently break them the same way again; and
    updated `test_books_status.py`'s one exact-dict response assertion to
    include the new `estimated_cost_usd` field. 4 new tests: over-hours
    422, over-cost 422 (both assert zero `Book` rows created), estimated
    cost persisted on success, and the existing default-to-zero case from
    Task 2.

- [x] Task 4: `api/error_tracking.py` — `capture_message_with_context()` helper (P0)
  - Acceptance: a new `capture_message_with_context(message: str, level: str = "warning", **context: str) -> None` mirrors `capture_exception_with_context`'s tag-then-capture shape but calls `sentry_sdk.capture_message(message, level=level)`; safe no-op when `SENTRY_DSN` is unset, same as the existing exception helper (no new guard needed — `sentry_sdk`'s own behavior with no client configured already covers it); unit test (following `tests/unit/test_error_tracking.py`'s existing pattern) covers the disabled no-op path and asserts `capture_message`/`set_tag` are invoked with the given message/level/context when enabled
  - Files: api/error_tracking.py, tests/unit/test_error_tracking.py
  - Completed: 2026-09-25 — added exactly as specified. 2 new tests
    mirroring the existing exception-helper tests: tags-then-capture with
    a monkeypatched `sentry_sdk.capture_message`, and a no-init safety
    test.

- [x] Task 5: Global daily spend alert (P0)
  - Acceptance: `api/config.py` gains `global_daily_spend_alert_usd: float` (default `20.0`, env-overridable via `GLOBAL_DAILY_SPEND_ALERT_USD`); after a `Book` is committed in `create_book`, sum `estimated_cost_usd` for every `Book` with `created_at` on or after today's UTC midnight (including the just-created one); if that sum is `>=` the threshold, call `capture_message_with_context` with a message naming today's total and the threshold at `level="warning"` — this never blocks or fails the request, purely observational, and cannot fire in production yet since every real `estimated_cost_usd` is `0.0` until a paid provider exists (documented in the message/PRD, not hidden). Integration test: creates several books the same day with `estimate_playlist` monkeypatched to a non-zero fake cost that crosses the threshold on the Nth book and asserts `capture_message_with_context` (or the underlying `sentry_sdk.capture_message`) is called exactly once with the correct running total; staying under the threshold across several creates triggers zero calls
  - Files: api/config.py, api/routers/books.py, tests/integration/test_books_create.py
  - Completed: 2026-09-25 — `global_daily_spend_alert_usd` defaults to
    `20` (`GLOBAL_DAILY_SPEND_ALERT_USD`); `_check_daily_spend_alert()`
    runs after commit, sums `estimated_cost_usd` for books created since
    UTC midnight via `func.coalesce(func.sum(...), 0.0)` (so an all-zero
    day never errors on a `None` sum), and calls
    `capture_message_with_context` at `level="warning"` once the total is
    `>=` the threshold. Purely observational -- no exception path, nothing
    it does can fail the request. 2 new tests: 2 books at $6 each cross a
    $10 threshold on the 2nd and trigger exactly 1 capture with both the
    running total ($12.00) and the threshold ($10.00) in the message;
    3 books at $1 each staying under the same threshold trigger 0.

- [x] Task 6: README — document the budget gate + daily spend alert (P1)
  - Acceptance: `backend/README.md` documents that `POST /books/youtube` now estimates a playlist before creating anything and rejects (`422`) over `MAX_BOOK_HOURS`/`MAX_BOOK_COST_USD` with no `--force` bypass (reusing `ai_llm`'s own settings, not a duplicate backend copy), that `Book.estimated_cost_usd` is persisted at creation, and what `GLOBAL_DAILY_SPEND_ALERT_USD` does today (and why it can't fire in production yet)
  - Files: README.md
  - Completed: 2026-09-25 — added a "Cost ceiling + daily spend alert
    (v8)" section covering both, added a v8 line to the "what's in" list,
    and trimmed the resolved items off the "still deferred" bullet.
    117/117 tests passing full suite (~51s), bandit clean, pip-audit
    unchanged (only the pre-existing unrelated `pip` self-CVEs).
