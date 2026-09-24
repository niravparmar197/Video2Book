# Sprint v5 — Tasks

## Status: Done

- [x] Task 1: Local dev infra — MinIO in docker-compose, `boto3` dependency, S3 settings (P0)
  - Acceptance: `docker-compose up -d` brings up a healthy `minio` service alongside Postgres/Redis; `api/config.py` gains `s3_bucket`, `s3_endpoint_url`, `s3_access_key`, `s3_secret_key`, `pdf_retention_days` (all env-overridable, sane MinIO defaults for local dev); `boto3` added to `pyproject.toml` and installed
  - Files: docker-compose.yml, api/config.py, pyproject.toml, .env.example
  - Completed: 2026-09-24 — **not MinIO**. `minio/minio` and
    `bitnami/minio` both now require a Docker Hub login to pull (a real
    licensing change since this project's earlier sprints), and
    `localstack/localstack:latest` pulls fine but refuses to start
    without a paid `LOCALSTACK_AUTH_TOKEN`. Verified all three by
    actually trying to pull/run them, not by assumption. Landed on
    `adobe/s3mock` (Apache-2.0, genuinely free, no auth) instead — pulled
    and ran cleanly, and a manual `boto3` round-trip (put/get/presigned
    URL fetch) against it worked on the first real try. PRD/TASKS
    describe MinIO because that's what was scoped before this was
    discovered; the running system uses S3Mock. Settings/env vars ended
    up named `S3_*` regardless of backing service, so nothing downstream
    needed renaming.

- [x] Task 2: `api/storage.py` — bucket-ensure, upload, presigned URL (P0)
  - Acceptance: `upload_pdf(book_id, local_path) -> str` uploads to `S3_BUCKET` at key `f"{book_id}/book.pdf"` (creating the bucket first if it doesn't exist) and returns the key; `presigned_url(key, expires_in=900) -> str` returns a working time-limited URL; `delete_pdf(key)` removes the object; a test uploads a small fake PDF to the real MinIO container, generates a presigned URL, fetches it with a plain HTTP client, and asserts the bytes round-trip
  - Files: api/storage.py, tests/unit/test_storage.py
  - Completed: 2026-09-24 — **found and fixed a real hang** (same class of
    bug as sprints/v2 Task 4's psycopg fix): `boto3`'s default retry
    policy re-attempts a failed connect several times with backoff, so
    even `connect_timeout=2` let `check_s3()` against an unreachable host
    hang past pytest-timeout's 30s cap. Fixed with
    `retries={"max_attempts": 2}` in the client `Config`, alongside
    `connect_timeout=2`/`read_timeout=5`. Also discovered port `1`
    (used for the equivalent psycopg/redis tests) doesn't fail the same
    way for boto3 on this machine -- switched the negative test to an
    unused high port (`59999`), which does fail with a real
    `TimeoutError` rather than hanging indefinitely. 4 tests, all against
    the real S3Mock container.

- [x] Task 3: Worker uploads the PDF to S3 on render/retry success (P0)
  - Acceptance: after a successful `render` or `retry` phase, `process_run_book` calls `storage.upload_pdf` with the local `pdf_path` ai_llm returned, sets `Book.pdf_path` to the returned S3 key (not the local path), and deletes the local `book.pdf` file — the rest of `output/<book_id>/` is left alone; a unit test with a real local temp PDF file and the real MinIO container asserts the DB row's `pdf_path` is an S3 key, the object exists in the bucket, and the local file no longer exists
  - Files: api/jobs/run_book.py, tests/unit/test_run_book_job.py
  - Completed: 2026-09-24 — `_finalize_pdf(book_id, local_pdf_path)` is
    the one place both the `render` and `retry` branches call; it uploads
    then `unlink(missing_ok=True)`s the local file. Every pre-existing
    test that mocked `ai_llm_run_book`/`ai_llm_resume_book` to return a
    fabricated (never-written) `Path` had to start writing a real file
    there instead, since `_finalize_pdf` now genuinely reads it —
    touched `test_run_book_job.py` and `test_outline_lifecycle.py`.

- [x] Task 4: `GET /books/{id}/pdf` redirects to a presigned URL (P0)
  - Acceptance: for a `done` book, returns `307` with a `Location` header pointing at a working presigned URL that serves the actual PDF bytes when fetched; 404 behavior for unknown/not-done/other-user's book is unchanged from v1-v4
  - Files: api/routers/books.py, tests/integration/test_books_pdf.py
  - Completed: 2026-09-24 — swapped `FileResponse` for
    `RedirectResponse(url, status_code=307)`; the local-disk existence
    check from v2 is gone (S3 is now the source of truth). Rewrote
    `test_books_pdf.py` to request with `follow_redirects=False`, assert
    the key appears in the `Location` header, then separately fetch that
    URL with `urllib.request` to confirm real bytes.

- [x] Task 5: End-to-end render → S3 → download lifecycle test (P0)
  - Acceptance: one test drives a (mocked ai_llm, real MinIO) render phase to `done`, follows the `GET /books/{id}/pdf` redirect, and confirms the fetched bytes match what ai_llm "rendered"
  - Files: tests/integration/test_pdf_storage_lifecycle.py
  - Completed: 2026-09-24 — full chain: create → plan phase (mocked
    `ai_llm_run_plan`) → `outline_ready` → render phase (mocked
    `ai_llm_run_book`, writes a real temp PDF) → `done` → `GET .../pdf`
    → follow the real redirect → bytes match exactly what "ai_llm"
    wrote.

- [x] Task 6: `GET /health` also checks S3 (P1)
  - Acceptance: `/health` response gains `"s3": "ok"`/`"error"`; a real bucket-list call against the configured endpoint, wrapped in its own try/except like the existing DB/Redis checks; unreachable S3 → overall `503`, same pattern as v2's DB/Redis checks
  - Files: api/routers/health.py, tests/integration/test_health.py
  - Completed: 2026-09-24 — `storage.check_s3()` calls `list_buckets()`;
    4 tests (all-ok, db-down, redis-down, s3-down), each confirming the
    *other* two checks still read `"ok"` when only one dependency is
    broken.

- [x] Task 7: `PDF_RETENTION_DAYS` + `python -m api.retention` delete script (P1)
  - Acceptance: running `python -m api.retention` finds every `Book` with a non-null `pdf_path` and `updated_at` older than `PDF_RETENTION_DAYS`, deletes the S3 object via `storage.delete_pdf`, and sets `pdf_path` to `NULL`; books inside the window are left untouched; a test seeds one expired and one fresh book against the real DB/MinIO and asserts only the expired one is cleaned up
  - Files: api/retention.py, tests/unit/test_retention.py
  - Completed: 2026-09-24 — **found a real test-writing footgun**:
    `Book.updated_at` has `onupdate=_now` (set in v1), so the natural way
    to seed an "aged" test row — insert, then a second `commit()` to set
    `pdf_path` — silently resets `updated_at` back to "now" on that
    second UPDATE, defeating the aged timestamp entirely. Both tests
    initially failed for this reason. Fixed by generating the book's
    UUID up front and setting `pdf_path` and the backdated `updated_at`
    in the *same* initial `INSERT`, never updating the row again before
    the assertion. Worth remembering for any future test that needs to
    fake an old `updated_at`/similar `onupdate` column.

- [x] Task 8: README — MinIO setup, S3 env vars, new `/pdf` redirect, retention script (P1)
  - Acceptance: `backend/README.md` documents the MinIO service, the new S3 env vars, that `/pdf` now redirects instead of streaming bytes, and how to run `python -m api.retention`
  - Files: README.md
  - Completed: 2026-09-24 — new "File storage (v5)" section explains the
    MinIO→S3Mock substitution and why; existing `/health` and PDF-download
    examples updated for the new response shape and redirect behavior;
    "What's in v1-v5" section extended.

## Verification summary

- 78/78 backend tests passing, 3 consecutive clean full-suite runs
  (31 v1/v2 + 20 v3 + 19 v4 + 8 new v5 tests). ~40s total, up from ~14s
  in v4 — almost entirely the 4 deliberately-slow unreachable-S3/DB/Redis
  negative tests (each bounded at ~9-10s by design, not hanging).
- `bandit -r api -ll`: clean, 0 issues.
- Live smoke test: real `uvicorn` process — `/health` reports all three
  dependencies `ok` including `s3`; signup → create book, full JSON logs
  visible.

## Real issues found and fixed (not in the original plan)

1. **Infra substitution**: MinIO (both official and Bitnami images) and
   LocalStack are no longer freely pullable/runnable without a login or
   paid token. Discovered by actually trying each, not by reading docs.
   Switched to `adobe/s3mock`.
2. **A real hang**: `boto3`'s default retry policy meant a 2s
   `connect_timeout` alone wasn't enough to keep `check_s3()` fast
   against an unreachable host — same class of bug as sprints/v2 Task 4's
   psycopg fix. Fixed with `retries={"max_attempts": 2}`.
3. **A test-writing footgun**: `onupdate=_now` columns get silently
   reset by any later `UPDATE` in the same test, including ones that
   only touch an unrelated field — the aged-timestamp seed has to happen
   in the row's original `INSERT`.

## Deferred to v6+ (see PRD "Out of Scope")

Scheduling `python -m api.retention`, honoring a reordered outline,
per-chapter status, `/events` + Postgres checkpointer, password/JWT/OAuth
login, key rotation, a global spend ceiling, and the rest of
backend/AGENTS.md's production-readiness checklist.
