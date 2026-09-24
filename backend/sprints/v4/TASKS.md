# Sprint v4 — Tasks

## Status: Done

- [x] Task 1: Schema — `User.api_key_hash` + `Book.user_id`, migration (P0)
  - Acceptance: `User` gets a `api_key_hash` column (unique, not null); `Book` gets a `user_id` FK to `users` (not null); `alembic upgrade head` applies cleanly against the compose Postgres (tables are currently empty, so a straight `ALTER TABLE ... NOT NULL` is fine, no drop/recreate needed)
  - Files: api/models.py, alembic/versions/0003_user_auth.py (generated as `27e9a46bfeda_user_auth.py`)
  - Completed: 2026-09-24 — straight `ADD COLUMN ... NOT NULL` since both
    tables were empty; named the two new constraints explicitly
    (`books_user_id_fkey`, `users_api_key_hash_key`) since alembic's
    autogenerate left them unnamed and warned the `downgrade()` would
    fail as rendered. Confirmed the test DB does *not* need this (or any)
    alembic migration applied — `tests/conftest.py`'s
    `Base.metadata.create_all/drop_all` builds it fresh from `models.py`
    every session; running alembic against it was a v3-era mistake that
    this sprint didn't repeat.

- [x] Task 2: `POST /users` issues an API key (P0)
  - Acceptance: posting `{"email": "..."}` returns 201 with `{"user_id": "...", "api_key": "<raw token>"}`; the raw token is never persisted (only `sha256(token)` is stored in `User.api_key_hash`) and never appears in logs; a duplicate email returns 409
  - Files: api/routers/users.py, api/schemas.py, api/main.py, tests/integration/test_users.py
  - Completed: 2026-09-24 — `api/auth.py` centralizes
    `generate_api_key`/`hash_api_key`. Needed `pydantic[email]` (the
    `email-validator` package) for `EmailStr`, added to `pyproject.toml`
    and installed. 3 tests, including one that asserts the stored
    `api_key_hash` is the SHA-256 of the returned key and is never equal
    to the raw key itself.

- [x] Task 3: `get_current_user` auth dependency; require it on `POST /books/youtube` (P0)
  - Acceptance: `api/auth.py` exposes a FastAPI dependency that reads `X-API-Key`, hashes it, and loads the matching `User` (401 if missing or no match); `POST /books/youtube` uses it and sets `Book.user_id` to the caller; `GET /health` is unaffected (no auth dependency added to it) — verified by a test that still gets 200 from `/health` with no `X-API-Key` header at all
  - Files: api/auth.py, api/routers/books.py, tests/integration/test_books_create.py
  - Completed: 2026-09-24 — `tests/integration/test_health.py` was left
    completely untouched by this sprint, which is itself the proof that
    `/health` stayed unauthenticated (it still passes with zero auth
    setup). 2 new tests (missing key, invalid key) in
    `test_books_create.py`.

- [x] Task 4: Require auth + ownership on the remaining book-scoped endpoints (P0)
  - Acceptance: `GET /books/{id}`, `GET /books/{id}/pdf`, `GET`/`PUT /books/{id}/outline`, `POST /books/{id}/retry` all 401 with no/invalid `X-API-Key`; a valid key for a *different* user requesting an existing book id gets 404 (same as an unknown id — no existence leak); the owning user still gets normal 200/202/409 behavior unchanged from v1-v3
  - Files: api/routers/books.py, api/routers/outline.py, tests/integration/test_books_status.py, tests/integration/test_books_pdf.py, tests/integration/test_outline.py, tests/integration/test_books_retry.py
  - Completed: 2026-09-24 — `get_owned_book(db, book_id, user)` (in
    `api/routers/books.py`, imported by `outline.py`) is the single
    ownership check every endpoint uses, so "unknown" and "someone
    else's" collapse to the exact same 404 code path rather than two
    separately-maintained checks that could drift. `tests/conftest.py`
    grew `make_user`/`user`/`auth_headers` fixtures (`user` and
    `auth_headers` share one underlying `make_user()` call via a cached
    `_user_and_key` fixture, so they refer to the same identity rather
    than two different users). Every pre-existing v1-v3 test file that
    built a `Book(...)` directly needed a `user_id` added (NOT NULL
    column now) — mechanical but wide-reaching across
    `test_books_status.py`, `test_books_pdf.py`, `test_books_logging.py`,
    `test_books_retry.py`, `test_outline.py`, `test_outline_lifecycle.py`,
    `test_book_lifecycle.py`, `test_run_book_job.py`. Added a
    same-user-vs-other-user 404 test to each of the 4 affected route
    files.

- [x] Task 5: `MAX_CONCURRENT_BOOKS_PER_USER` rate limit on create (P0)
  - Acceptance: new `MAX_CONCURRENT_BOOKS_PER_USER` setting (default 3, env-overridable); `POST /books/youtube` counts the caller's books with `status NOT IN ('done', 'failed')`; at or over the limit, returns 429 with a clear message and does not create a `Book` row or enqueue a job; under the limit, behaves as before
  - Files: api/config.py, api/routers/books.py, tests/integration/test_books_create.py
  - Completed: 2026-09-24 — in-flight statuses are
    `queued`/`planning`/`outline_ready`/`rendering` (everything except
    `done`/`failed`); the count check runs *before* the `Book` row is
    created, so a 429 never leaves a half-created row behind. 2 tests
    (limit trips at N, `done`/`failed` books don't count against it).

- [x] Task 6: End-to-end auth + rate-limit lifecycle test (P1)
  - Acceptance: one test signs up two users, confirms user A cannot see/act on user B's book (404), confirms `MAX_CONCURRENT_BOOKS_PER_USER` in-flight books trigger 429 on the next create, and confirms a `done`/`failed` book doesn't count against the limit
  - Files: tests/integration/test_auth_lifecycle.py
  - Completed: 2026-09-24 — drives the *real* `POST /users` signup flow
    (not the `make_user` test fixture) end to end, then exercises all 5
    book-scoped endpoints for the cross-user 404 check in one pass.
    **Found and fixed a real flake while writing this**: the
    limit-then-recover test originally freed a slot with
    `db_session.get(Book, id); book.status = "done"; db_session.commit()`
    (ORM load-mutate-commit) and intermittently hit
    `sqlalchemy.orm.exc.StaleDataError` (and, on a later run, a cascading
    401 on an unrelated request) when run as part of the full 70-test
    suite — not reproducible in isolation, and a clean re-run of the full
    suite sometimes passed outright, pointing to a connection/session
    state issue rather than a logic bug. Switched to a Core
    `update(Book).where(...)` (bypassing the ORM identity map for a row
    this session never loaded) and the flake did not recur across 5
    consecutive full-suite runs afterward.

- [x] Task 7: README — document `POST /users`, `X-API-Key`, and the rate limit (P1)
  - Acceptance: `backend/README.md` shows signing up, using the key on every book-scoped call, the 401/404/429 behaviors, and notes the key is shown only once and there's no rotation yet
  - Files: README.md
  - Completed: 2026-09-24 — new "Auth + rate limiting (v4)" section;
    every existing `curl` example elsewhere in the README updated to
    include `-H "X-API-Key: ..."`; `.env.example` got
    `MAX_CONCURRENT_BOOKS_PER_USER`; "What's in v1/v2/v3/v4" updated.

## Verification summary

- 70/70 backend tests passing, 5 consecutive clean full-suite runs after
  the Task 6 flake fix (31 v1/v2 + 20 v3 + 19 new v4 tests -- v3's count
  also grew slightly from added cross-user/auth-required test variants).
- `bandit -r api -ll`: clean, 0 issues.
- Live smoke test: real `uvicorn` process — signup, 401 without a key,
  201 with one, `/health` still 200 with no key at all.

## Real gap found and fixed (not in the original plan)

A test flake, not a shipped bug: `test_rate_limit_blocks_the_nth_plus_one_book_then_recovers`
intermittently triggered `StaleDataError` (and once a seemingly-unrelated
cascading 401) only when run inside the full 70-test suite, never in
isolation. Root-caused to an ORM `get()`-then-mutate-then-`commit()` on a
row the test's session hadn't itself created; switched to a Core
`UPDATE` statement, which sidesteps the ORM's row-count check entirely.
Flagging this pattern (avoid ORM load-mutate-commit on rows your test
didn't create/load through the same session) for future test-writing in
this project.

## Deferred to v5+ (see PRD "Out of Scope")

Password/JWT/OAuth login, per-key scopes, key rotation/revocation,
rate-limiting `POST /users` itself, a global cross-user spend ceiling,
and everything already deferred as of v3 (reordering, per-chapter
status, `/events`, Postgres checkpointer, S3, and the rest of
backend/AGENTS.md's production-readiness checklist).
