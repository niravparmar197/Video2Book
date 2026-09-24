# Sprint v1 — Tasks

## Status: Done

- [x] Task 1: Project setup — FastAPI skeleton, docker-compose (Postgres + Redis), ai_llm as an editable dependency (P0)
  - Acceptance: `uvicorn app.main:app --reload` boots and serves a placeholder route; `docker-compose up -d` brings up Postgres and Redis containers; `python -c "from ai_llm.app.graph import run_book"` succeeds from within `backend/`
  - Files: app/main.py, docker-compose.yml, pyproject.toml, .env.example
  - Completed: 2026-09-24 — package is `api/` not `app/`, on purpose: ai_llm's
    own internal package is also named `app` (`ai_llm/app/graph.py`) and is
    intentionally not pip-installable (root AGENTS.md — it must keep working
    standalone from the CLI). Naming this project `api` instead avoids a
    Python import collision; `api/ai_llm_bridge.py` adds `ai_llm/` to
    `sys.path` just long enough to import its `app.graph` module, then
    removes it again. `uvicorn api.main:app --reload` boots and serves `/`.
    `docker-compose.yml` maps Postgres to host port **5433** (not 5432) —
    this machine already has a native PostgreSQL 18 service on 5432, so
    5432 would have collided; Redis stays on the default 6379. Both
    containers report `healthy`. `pyproject.toml` needed an explicit
    `[tool.setuptools] packages = [...]` list — flat-layout autodiscovery
    otherwise fails with "Multiple top-level packages discovered"
    (api/alembic/sprints all present as top-level dirs). `pip install -e
    ".[dev]"` verified working end to end.

- [x] Task 2: SQLAlchemy models + initial Alembic migration (User, Book, Video, Chapter) (P0)
  - Acceptance: `alembic upgrade head` against the docker-compose Postgres creates all four tables with the columns needed by later tasks (`Book.id`, `Book.url`, `Book.status`, `Book.pdf_path`, `Book.error_message`, timestamps)
  - Files: app/models.py, app/db.py, alembic/env.py, alembic/versions/0001_initial.py
  - Completed: 2026-09-24 — files are under `api/`, not `app/` (see Task 1).
    `alembic revision --autogenerate` generated `alembic/versions/0001_initial.py`
    against the live compose Postgres; `alembic upgrade head` verified via
    `\dt` inside the container — `users`, `books`, `videos`, `chapters`, and
    `alembic_version` all present. `Video`/`Chapter` tables exist and
    migrate cleanly but are intentionally unpopulated in v1 (see PRD —
    the video set isn't known until ai_llm's fetch node runs).

- [x] Task 3: Pydantic schemas + `POST /books/youtube` creates a `Book` row (P0)
  - Acceptance: posting `{"url": "<link>"}` returns 201 with `{id, status: "queued"}`; a `Book` row exists in the DB with that id and status; posting an empty/malformed `url` returns 422
  - Files: app/schemas.py, app/routers/books.py, tests/integration/test_books_create.py
  - Completed: 2026-09-24 — `BookCreateRequest.url: HttpUrl` gives 422 on a
    malformed or missing url for free via pydantic validation. 4 integration
    tests against the real (non-mocked) `video2book_test` Postgres database,
    per backend/AGENTS.md's "never mock the DB layer" rule. Also verified
    live with a real `uvicorn` process + `curl`.

- [x] Task 4: Redis/BullMQ queue wiring — enqueue `run_book` job on book creation (P0)
  - Acceptance: after `POST /books/youtube`, a `run_book` job exists on the BullMQ queue with `jobId == book_id` and the book's `url` in its payload; verified against a test Redis instance (or fakeredis), not mocked at the queue-client level
  - Files: app/queue.py, app/routers/books.py, tests/integration/test_books_create.py
  - Completed: 2026-09-24 — `api/queue.py`'s `enqueue_run_book` adds a job
    with `jobId=book_id` and `defaultJobOptions={attempts: 3, backoff:
    exponential 5s, removeOnFail: False}` (the retry contract Task 6 relies
    on). Verified against the real docker-compose Redis via
    `tests/integration/test_queue_enqueue.py`, which fetches the job back
    with `bullmq.Job.fromId` and asserts `job.data`/`job.opts` — no queue
    mocking.

- [x] Task 5: Worker entrypoint — `run_book` job handler calls `ai_llm.app.graph.run_book` via `asyncio.to_thread` (P0)
  - Acceptance: handler sets `Book.status = "running"` before invoking `run_book`, and on success sets `Book.status = "done"` with `Book.pdf_path` set to the path `run_book` returned; unit test mocks `ai_llm.app.graph.run_book` and asserts both status transitions and that the event loop isn't blocked (call happens in a thread)
  - Files: app/jobs/run_book.py, tests/unit/test_run_book_job.py
  - Completed: 2026-09-24 — `api/jobs/run_book.py::process_run_book` sets
    `running` before the call, `done` + `pdf_path` after, via
    `asyncio.to_thread(ai_llm_run_book, ...)`. `api/worker.py` is the queue
    entrypoint (`python -m api.worker`), imported and instantiated in a
    smoke check to confirm the ai_llm bridge resolves cleanly outside of
    tests too.

- [x] Task 6: Failure + retry handling in the worker (P0)
  - Acceptance: queue is configured for 3 retries and a 5-minute lock per job; if `run_book` raises, the handler re-raises so BullMQ retries; a unit test simulates retries exhausted (final attempt) and asserts `Book.status = "failed"` with `Book.error_message` set to the exception text; an earlier (non-final) attempt leaves `Book.status` as `"running"`, not `"failed"`
  - Files: app/jobs/run_book.py, app/queue.py, tests/unit/test_run_book_job.py
  - Completed: 2026-09-24 — `attempts=3` on the job (Task 4),
    `lockDuration=300000` (5 min) on the `Worker` in `api/worker.py`.
    `_is_final_attempt(job)` mirrors bullmq's own
    `(attemptsMade + 1) >= attempts` check from `Job.moveToFailed`
    (read from the installed `bullmq` package source to get this right)
    so the handler can tell, before that framework call runs, whether this
    is the last try. Only marks `Book.status = "failed"` on the final
    attempt; always re-raises so BullMQ's own retry/backoff still runs.
    4 parametrized + 3 dedicated unit tests cover both branches.

- [x] Task 7: `GET /books/{id}` reports status (P0)
  - Acceptance: returns 404 for an unknown id; for a known id returns 200 with `{id, status, pdf_path, error_message}` matching the current DB row exactly (covers `queued`/`running`/`done`/`failed`)
  - Files: app/routers/books.py, tests/integration/test_books_status.py
  - Completed: 2026-09-24 — 4 integration tests cover 404 plus all three
    non-`queued` statuses (`running`/`done`/`failed`) against the real test
    DB.

- [x] Task 8: End-to-end integration test for the full create → queue → worker → status loop (P1)
  - Acceptance: a single test drives `POST /books/youtube` through the FastAPI `TestClient`, runs the queued job handler directly (with `ai_llm.app.graph.run_book` mocked, per the no-real-LLM/YouTube testing rule), and asserts `GET /books/{id}` reflects `done` with the mocked `pdf_path`; a second variant asserts the `failed` path end to end
  - Files: tests/integration/test_book_lifecycle.py
  - Completed: 2026-09-24 — both the success and final-failure variants
    drive the real HTTP create endpoint, invoke `process_run_book` directly
    with `ai_llm_run_book` monkeypatched, then re-`GET` to confirm the DB
    round-trip end to end.

- [x] Task 9: README quickstart for local dev (P1)
  - Acceptance: `backend/README.md` documents `docker-compose up -d`, `alembic upgrade head`, running the API, and running the worker, sufficient for a new contributor to get `POST /books/youtube` returning a real `queued` book locally
  - Files: README.md
  - Completed: 2026-09-24 — covers env setup (noting the 5433 port choice),
    compose up, `pip install -e ".[dev]"`, migration, running the API and
    worker, and how tests get a real, isolated `video2book_test` database.

## Verification summary

- 18/18 tests passing (`pytest`), all against real Postgres/Redis
  containers — no DB or queue mocking, per backend/AGENTS.md.
- `bandit -r api -ll`: clean, 0 issues.
- `pip-audit`: 12 pre-existing CVEs on the `pip` launcher itself (pinned
  pip 24.0, same class of finding ai_llm's own v7 sprint hit) — unrelated
  to any dependency this sprint added, not blocking.
- Live smoke test: real `uvicorn` process + `curl POST /books/youtube` +
  `curl GET /`, both 2xx.
- `api.worker` module (and its `ai_llm_bridge` import of ai_llm's
  `app.graph`) imports cleanly outside of pytest.

## Deferred to v2 (see PRD "Out of Scope")

Outline review endpoints, `/books/{id}/events`, `/books/{id}/pdf` + S3,
`/books/{id}/retry`, `/health` + structured logging, Postgres checkpointer
for LangGraph, auth, and everything in backend/AGENTS.md's production
readiness checklist.
