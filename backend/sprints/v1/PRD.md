# Sprint v1 — PRD: Book API + Job Queue Core Loop

## Overview

Wrap `ai_llm`'s LangGraph pipeline (`app/graph.py`) behind a minimal FastAPI
service so a book run can be submitted over HTTP and polled for status,
instead of run by hand from the CLI. This sprint is the "core loop" only:
create a book, queue it, run it, report status. Outline review, retry,
event streaming, PDF download, and S3 are deliberately deferred to v2 so
each task here stays atomic and testable.

## Goals

- `POST /books/youtube` persists a `Book` row and enqueues one `run_book`
  BullMQ job per book (`jobId = book_id`).
- A worker process pulls `run_book` jobs from the queue and calls
  `ai_llm.app.graph.run_book(...)` via `asyncio.to_thread()`, never blocking
  the event loop.
- `GET /books/{id}` returns the book's current status (`queued`, `running`,
  `done`, `failed`) and, once complete, the local path to the rendered PDF.
- Postgres (SQLAlchemy + Alembic) replaces ad-hoc JSON files for this layer
  only — `Book`, `Video`, `Chapter`, and a minimal `User` table exist and
  migrate cleanly with `alembic upgrade head`.
- A failed job retries automatically (BullMQ, 3 retries, 5-minute lock)
  before the book is marked `failed`, so a transient NVIDIA/Gemini outage
  doesn't kill a run outright.

## User Stories

- As a user, I want to submit a YouTube link or playlist and get a book id
  back immediately, so I don't have to wait on the request while the
  pipeline runs.
- As a user, I want to poll a book's status at any time, so I know whether
  it's still running, finished, or failed.
- As an operator, I want a stuck or transiently-failing job to retry
  automatically instead of silently dying, so a rate-limit blip doesn't
  require a manual re-run.
- As an operator, I want the worker to run the existing `ai_llm` pipeline
  unmodified, so no pipeline logic is duplicated or drifts between the CLI
  and the API.

## Technical Architecture

**Stack** (per `backend/AGENTS.md`): FastAPI, PostgreSQL + SQLAlchemy +
Alembic, BullMQ (Python) + Redis, Docker Compose for local Postgres/Redis.
S3 and AWS deploy (ECS/RDS/ElastiCache) are out of scope — see below.

```
                 ┌──────────────┐        ┌─────────────────┐
 client ───POST──▶  FastAPI API  │──enq──▶│  Redis (BullMQ)  │
                 │  /books/...  │        └────────┬─────────┘
                 └──────┬───────┘                 │
                        │ writes                  │ run_book job
                        ▼                          ▼
                 ┌──────────────┐        ┌─────────────────────┐
                 │  PostgreSQL  │◀──────▶│  Worker process      │
                 │ Book/Video/  │ updates│  asyncio.to_thread(  │
                 │ Chapter/User │        │    ai_llm.graph.     │
                 └──────────────┘        │    run_book(...) )   │
                        ▲                └──────────┬──────────┘
                        │ status reads              │ writes
 client ───GET────▶ /books/{id} ◀───────── output/<book>/*.pdf (local disk)
```

**Data flow**

1. `POST /books/youtube {url}` → API creates a `Book` row (`status=queued`;
   `url` is a single link, which may itself be a video or a playlist — that
   distinction is resolved inside `ai_llm`'s own fetch node
   (`run_fetch_playlist`), not by this layer), then enqueues a `run_book`
   job with `jobId = book_id`. `Video` rows are not created at this step,
   since the set of videos isn't known until the pipeline fetches them.
2. The worker picks up the job, sets `Book.status = running`, and calls
   `ai_llm.app.graph.run_book(url, output_dir, force=False)` in a thread
   (this function already exists and returns the final PDF `Path`).
3. On success, the worker sets `Book.status = done` and
   `Book.pdf_path = <returned Path>` (local disk — `output/<book_id>/`).
   Populating `Video`/`Chapter` rows from the run's output (for the v2
   outline/retry endpoints) is deferred — the tables exist and migrate
   cleanly in v1, but only `Book` is written to in this sprint.
4. On an unhandled exception, BullMQ retries the job (up to 3 times, 5-min
   lock); if all retries are exhausted, the worker sets
   `Book.status = failed` and stores the error message.
5. `GET /books/{id}` reads the `Book` row directly — no LangGraph
   checkpoint inspection in v1; status granularity is book-level
   (`queued`/`running`/`done`/`failed`), not per-node.

**Core engine boundary**: this sprint imports and calls
`ai_llm.app.graph.run_book` only. No pipeline logic (fetch/chunk/write/
render) is reimplemented here, per the root `AGENTS.md` rule. `ai_llm`'s own
`SqliteSaver`-based checkpointing is left untouched by this sprint — the
Postgres checkpointer swap for LangGraph (listed in `backend/AGENTS.md`'s
stack table) is deferred to a later sprint since it requires changes inside
`ai_llm/graph.py` itself and isn't needed for v1's book-level status
granularity.

## Out of Scope (v2+)

- `GET/PUT /books/{id}/outline` (outline review/edit)
- `GET /books/{id}/events` (live per-node progress streaming)
- `GET /books/{id}/pdf` (download endpoint) and S3 file storage — v1 only
  records the local `output/<book_id>/` path in the DB
- `POST /books/{id}/retry` (re-run only failed chapters)
- `/health` endpoint and structured JSON logging
- Postgres checkpointer for LangGraph (replacing `ai_llm`'s `SqliteSaver`)
- Auth/login, per-user rate limiting, Bull Board dashboard
- AWS deploy (Docker + ECS/RDS/ElastiCache), CI (GitHub Actions)
- Everything in `backend/AGENTS.md`'s production-readiness checklist

## Dependencies

- `ai_llm/` core pipeline works end to end via its CLI (`run_book`,
  `--resume`) — confirmed for milestones 1–6; the v7 scale-test milestone
  (real 2h/8h/30h runs) is still in progress in parallel and is not a hard
  blocker for this sprint, since v1 only calls the existing, already-tested
  `run_book(url, output_dir, force)` function.
- Docker available locally to run `docker-compose up` for Postgres + Redis.
- `ai_llm` importable as a Python package from `backend/` (same virtualenv
  or an editable install) so `from ai_llm.app.graph import run_book` works.
