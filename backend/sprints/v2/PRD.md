# Sprint v2 — PRD: Operability (Health, Logging, PDF Download)

## Overview

v1 shipped the create → queue → worker → status core loop against real
Postgres/Redis, but a finished book's PDF can't be retrieved through the
API, there's no way to tell if the DB or Redis is down before a request
fails, and nothing logs in a way that's greppable by `book_id` when a run
goes wrong. This sprint makes v1 actually usable end-to-end and observable,
without touching the outline/retry surface (still deferred).

## Goals

- `GET /books/{id}/pdf` serves the rendered PDF for a `done` book straight
  from local disk (`book.pdf_path`), and 404s cleanly for anything else.
- `GET /health` reports 200 only when both Postgres and Redis are
  reachable, 503 with which dependency failed otherwise — per
  `backend/AGENTS.md`'s health-check requirement.
- Every log line the API and worker emit is structured JSON and carries
  `book_id`/`step` (and `chapter_id` where relevant) — per
  `backend/AGENTS.md`'s logging requirement — with no secrets in the
  output.
- The worker's status transitions (`queued`→`running`→`done`/`failed`)
  are all logged with that same structured context, so a stuck or failed
  book is traceable from logs alone, not just by polling the DB.

## User Stories

- As a user, I want to download my finished book's PDF once it's `done`,
  so I don't have to go find the file on the server's disk myself.
- As an operator, I want `/health` to tell me the DB or Redis is down
  before users start hitting broken `POST /books/youtube` calls, so I
  find out from a monitor instead of from a support ticket.
- As an operator, I want every log line for a given book to carry its
  `book_id`, so `grep`/log-search by book id gives me the whole story of
  a run without correlating timestamps by hand.

## Technical Architecture

Builds directly on v1's `api/` package (FastAPI + SQLAlchemy + BullMQ
worker) — no new services.

```
 client ──GET /books/{id}/pdf──▶ FastAPI ──reads book.pdf_path──▶ local disk
                                    │                              (output/<id>/*.pdf)
 client ──GET /health──▶ FastAPI ──┼──ping──▶ PostgreSQL
                                    └──ping──▶ Redis

 API process ──┐
               ├──▶ structured JSON logs (stdout), fields: ts, level,
 worker process┘     message, book_id, step, [chapter_id]
```

**Logging**: a small `api/logging.py` configures Python's stdlib
`logging` with a JSON formatter and a `get_logger(book_id=..., step=...)`
helper (implemented via `logging.LoggerAdapter` so callers don't have to
pass those fields on every call site). Wired into `api/main.py` on
startup and `api/worker.py`'s entrypoint. The `POST /books/youtube`,
`GET /books/{id}`, and `process_run_book`'s status transitions all log
through it. No API keys, DB URLs with embedded credentials, or Redis URLs
are ever logged — only `book_id`, `step`/`status`, and (on failure) the
exception message already stored in `Book.error_message`.

**Health check**: `GET /health` runs `SELECT 1` against the configured
Postgres and a Redis `PING`, each independently try/excepted; 200 with
`{"status": "ok", "db": "ok", "redis": "ok"}` if both succeed, 503 with
whichever field(s) say `"error"` otherwise.

**PDF download**: `GET /books/{id}/pdf` looks up the `Book` row; 404 if
the id doesn't exist or `status != "done"`; otherwise streams
`book.pdf_path` back via FastAPI's `FileResponse` with
`media_type="application/pdf"`.

## Out of Scope (v3+)

- `GET/PUT /books/{id}/outline` and `POST /books/{id}/retry` — still
  blocked on populating `Video`/`Chapter` rows from ai_llm's output,
  which this sprint doesn't touch.
- `GET /books/{id}/events` (live per-node progress) and the Postgres
  checkpointer swap for LangGraph — status stays book-level
  (`queued`/`running`/`done`/`failed`), not per-node, until that swap
  happens.
- S3 file storage — `GET /books/{id}/pdf` still reads from local disk.
- Auth/login, per-user rate limiting, Sentry/error tracking, LangSmith
  tracing dashboards, Bull Board — full list in
  `backend/AGENTS.md`'s production-readiness checklist, still not
  addressed.

## Dependencies

- Sprint v1 (`sprints/v1/`) complete: `Book` model with `status`/
  `pdf_path`/`error_message`, the `POST`/`GET /books/{id}` endpoints, and
  the `process_run_book` worker handler all exist and are tested against
  real Postgres/Redis containers.
- `docker-compose up -d` (Postgres on `localhost:5433`, Redis on
  `6379`) available locally, same as v1.
