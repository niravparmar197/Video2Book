# Video2Book — backend

FastAPI + PostgreSQL + BullMQ wrapper around `ai_llm`'s `app.graph.run_book`.
See `AGENTS.md` for the stack and endpoint spec, `sprints/v1/PRD.md` for
what this sprint covers.

## Local dev quickstart

> **Worker after code changes.** The worker imports `ai_llm` once at startup, but
> `ai_llm/app/prompts/*.md` are read fresh on every call -- so after editing
> Python code, a running worker mixes old code with new prompts (a real failure:
> `KeyError 'channel'`). In development run it under `watchfiles`, which restarts
> it whenever `api/` or `ai_llm/app/` changes (an in-flight job is picked up again
> by BullMQ once its lock expires):
>
> ```
> watchfiles "python -m api.worker" api ../ai_llm/app
> ```


1. **Copy env vars**

   ```
   cp .env.example .env
   ```

   `DATABASE_URL` points at `localhost:5433` (not 5432) so it doesn't clash
   with a locally installed Postgres, if you have one.

2. **Start Postgres + Redis + S3Mock**

   ```
   docker compose up -d
   ```

3. **Install dependencies**

   ```
   pip install -e ".[dev]"
   ```

   `ai_llm/` itself is *not* pip-installed — it's a standalone CLI project
   (see root `AGENTS.md`). `api/ai_llm_bridge.py` imports its `app.graph`
   module directly by adding `../ai_llm` to `sys.path` at import time, so
   `ai_llm`'s own dependencies (langgraph, yt-dlp, etc.) must already be
   installed in this environment.

4. **Run the initial migration**

   ```
   alembic upgrade head
   ```

5. **Run the API**

   ```
   uvicorn api.main:app --reload
   ```

   Every book-scoped endpoint requires an API key — see "Auth + rate
   limiting" below for how to get one. Once you have `$API_KEY`:

   ```
   curl -X POST http://127.0.0.1:8000/books/youtube \
     -H "Content-Type: application/json" \
     -H "X-API-Key: $API_KEY" \
     -d '{"url": "https://www.youtube.com/watch?v=..."}'
   ```

   returns `{"id": "...", "status": "queued", ...}`. This only starts the
   **plan** phase (see "Outline review + retry" below) — it does not render
   a PDF by itself.

6. **Run the worker** (separate process — picks up queued jobs and calls
   the `ai_llm` pipeline)

   ```
   python -m api.worker
   ```

## Auth + rate limiting (v4)

Every book-scoped endpoint (`/books/youtube`, `/books/{id}`,
`/books/{id}/outline`, `/books/{id}/retry`, `/books/{id}/pdf`) requires
an `X-API-Key` header. `/health` and `/users` itself are the only
unauthenticated endpoints.

```
# 1. Sign up -- the api_key is shown exactly once, only its SHA-256 hash
#    is stored server-side. Save it now; there's no way to recover or
#    rotate it yet.
curl -X POST http://127.0.0.1:8000/users \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com"}'
# {"user_id": "...", "api_key": "<save this>"}

# 2. Use it on every book-scoped call
curl http://127.0.0.1:8000/books/<id> -H "X-API-Key: <your key>"
```

- Missing or invalid key → `401`.
- A book that exists but belongs to a different user → `404`, identical
  to an unknown id (no existence leak via `403`).
- `POST /books/youtube` → `429` once you have
  `MAX_CONCURRENT_BOOKS_PER_USER` (default 3, env-overridable) books that
  aren't yet `done`/`failed` — finish or wait one out before starting
  another.

## Operability (v2)

- **Health check** — `GET /health` pings Postgres, Redis, S3, and the
  worker's heartbeat independently and returns 503 if any of them is
  unreachable/stale:

  ```
  curl http://127.0.0.1:8000/health
  # {"status": "ok", "db": "ok", "redis": "ok", "s3": "ok", "worker": "ok"}
  ```

  `"worker": "stale"` (and an overall `503`) is expected and correct if
  you've started the API but not `python -m api.worker` yet, or if the
  worker process has died — see "Error tracking + worker heartbeat"
  below.

- **PDF download** — once a book's `status` is `"done"`, `GET
  /books/{id}/pdf` redirects (307) to a 15-minute presigned S3 URL (see
  "File storage" below):

  ```
  curl -L -o book.pdf http://127.0.0.1:8000/books/<id>/pdf -H "X-API-Key: $API_KEY"
  ```

  404s for an unknown id or a book that isn't `done` yet.

- **Logs** — both the API and worker emit one JSON object per line on
  stdout (`api/logging.py`), e.g.:

  ```
  {"ts": "2026-09-24T14:48:00+00:00", "level": "INFO", "message": "status changed", "book_id": "...", "step": "run_book:render", "status": "rendering"}
  ```

  Every line carries `book_id` and `step` so a single run is `grep`-able;
  no connection strings or API keys are ever logged.

## Outline review + retry (v3)

The pipeline now stops after planning so you can review the chapter list
before the slow render step runs:

```
# 1. Create a book — this only runs ai_llm's plan phase (fetch/chunk/
#    topics/write/outline), no render.
curl -X POST http://127.0.0.1:8000/books/youtube \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"url": "https://www.youtube.com/watch?v=..."}'
# {"id": "<id>", "status": "queued", ...}

# 2. Poll until status is "outline_ready"
curl http://127.0.0.1:8000/books/<id> -H "X-API-Key: $API_KEY"

# 3. Review the chapter plan
curl http://127.0.0.1:8000/books/<id>/outline -H "X-API-Key: $API_KEY"
# [{"id": "chapter:...", "title": "...", "order": 1, "skip": false, "locked": false, "source_video_ids": [...]}]

# 4. Save edits (skip/locked only — see limitation below) and start the
#    render. Saving with no changes is equivalent to "approve".
curl -X PUT http://127.0.0.1:8000/books/<id>/outline \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '[{"id": "chapter:...", "skip": true, "locked": false}]'

# 5. Poll again for "done", then GET /books/<id>/pdf
```

If a book's `status` becomes `"failed"`, retry it without redoing
completed work (ai_llm's `resume_book` skips disk-cached/already-verified
steps):

```
curl -X POST http://127.0.0.1:8000/books/<id>/retry -H "X-API-Key: $API_KEY"
```

409s unless the book is currently `failed`.

**Known limitation**: `PUT /outline` only persists `skip`/`locked` —
ai_llm's outline node (`app/nodes/outline.py`) always recomputes `order`
from playlist/topic position on every re-run, so a reordered chapter list
in the request body does not currently change render order. See
`sprints/v3/PRD.md`.

`Book.status` values: `queued → planning → outline_ready → rendering →
done` / `failed` (a `failed` book can move back to `rendering` via
`/retry`).

## File storage (v5)

Once a `render`/`retry` phase succeeds, the worker uploads
`output/<book_id>/book.pdf` to S3 and deletes the local copy (everything
else in `output/<book_id>/` — chunks, the checkpoint db, chapter `.tex`
files — stays local, since a future `/retry` still needs it).
`Book.pdf_path` becomes the S3 object key (`<book_id>/book.pdf`), not a
local path.

Local dev/test run against **S3Mock** (`adobe/s3mock`, Apache-2.0), not
real AWS — see `docker-compose.yml`. MinIO's Docker Hub images now
require a login to pull and `localstack/localstack:latest` refuses to
start without a paid license token, so S3Mock stands in as the free,
no-auth S3-compatible service instead. In a real deploy, set
`S3_ENDPOINT_URL=` (empty) so `boto3` talks to actual AWS S3 — every
other S3 env var doubles as real AWS credentials at that point.

**Retention**: `PDF_RETENTION_DAYS` (default 30) plus a script that
actually deletes expired objects — not just a documented policy:

```
python -m api.retention
# Deleted 3 expired PDF(s) older than 30 day(s).
```

Deletes the S3 object and clears `Book.pdf_path` for every book whose
`updated_at` is older than the window. Not scheduled by this sprint — run
it by hand, or wire it into a cron job / scheduled task at deploy time.

## Error tracking + worker heartbeat (v6)

**Error tracking** is off by default — `SENTRY_DSN` is empty, so
`sentry_sdk.init()` is never called and no network I/O to Sentry is ever
attempted. Set a real DSN to turn it on:

```
SENTRY_DSN=https://<key>@<org>.ingest.sentry.io/<project>
SENTRY_ENVIRONMENT=production
```

Once enabled, every unhandled API exception (via a global FastAPI
exception handler) and every final-attempt worker failure is reported
with `book_id`/`phase`/request-`path` tags attached, alongside the
existing structured log line — the client still just gets a normal `500`
or the book's `error_message`, Sentry wiring never changes API behavior.

**Worker heartbeat**: `python -m api.worker` writes a TTL'd key to Redis
every `WORKER_HEARTBEAT_INTERVAL_SECONDS` (default 15s, expires after
`WORKER_HEARTBEAT_TTL_SECONDS`, default 45s) and clears it on a clean
shutdown (Ctrl-C). `GET /health`'s `"worker"` field reflects whether that
key is currently present — a killed, hung, or never-started worker shows
up as `"stale"` within one heartbeat interval, not "whenever someone
notices books have stopped moving."

## Postgres checkpointer + live progress events (v7)

**Postgres checkpointer**: LangGraph now checkpoints every API-created
book's run to Postgres (`api/checkpointer.py`, `PostgresSaver`) instead of
the per-book `graph_state.sqlite` file `ai_llm/` uses when run standalone
from its own CLI. `ai_llm/` itself is unaffected — its `run_book`/
`run_plan`/`resume_book` all take an optional `checkpointer=` param; every
existing `ai_llm` caller (the CLI, its own tests) omits it and keeps
getting the same SQLite file as before. The API/worker pass
`api.checkpointer.get_checkpointer()` (a shared connection pool, one per
process) into all three calls instead. Both the API and the worker call
`ensure_checkpoint_tables()` on startup — idempotent, creates LangGraph's
checkpoint tables on first run, no-ops after.

**`GET /books/{id}/events`**: a Server-Sent Events stream of live
pipeline progress, polling the shared checkpointer's state every
`EVENTS_POLL_SECONDS` (default 2) and emitting a `progress` event only
when the current/completed node (or, since v9, any chapter's status)
actually changed, ending in one `done` or `failed` event:

```
curl -N http://127.0.0.1:8000/books/<id>/events -H "X-API-Key: $API_KEY"

event: progress
data: {"completed_nodes": ["fetch", "chunk", "frames"], "current_node": "topics", "next_nodes": ["write"], "step": 3, "chapters": []}

event: progress
data: {"completed_nodes": ["fetch", "chunk", "frames", "topics"], "current_node": "write", "next_nodes": ["outline"], "step": 4, "chapters": [{"id": "chapter:vid1", "title": "Introduction", "status": "done", "score": 9, "attempts": 1, "passed": true}, {"id": "chapter:vid2", "title": "Gradient Descent", "status": "pending", "score": null, "attempts": null, "passed": null}]}

event: done
data: {"completed_nodes": ["fetch", "chunk", "frames", "topics", "write", "outline", "book_pass", "render"], "current_node": null, "next_nodes": [], "step": 8}
```

Same 404 (unknown book / another user's book) and 401 (no auth) rules as
`GET /books/{id}`.

## Cost ceiling + daily spend alert (v8)

**Upfront budget check**: `POST /books/youtube` now estimates the
playlist (`ai_llm`'s own `app.estimate.estimate_playlist` — no LLM call,
same calculation its `--estimate` CLI flag makes) *before* creating a
`Book` row or queuing any job. If the total duration or estimated cost
exceeds `MAX_BOOK_HOURS`/`MAX_BOOK_COST_USD`, the request is rejected with
`422` and nothing is created. These limits are read from `ai_llm`'s own
settings (`api/ai_llm_bridge.py` re-exports `load_settings`), never a
separate backend copy that could drift out of sync. Unlike the `ai_llm`
CLI's `--force` flag, there is **no bypass** here — a shared multi-tenant
worker pool and provider rate-limit budget can't be signed away by one
user's request.

`Book.estimated_cost_usd` is persisted at creation time (from the same
estimate that passed the check above), visible on every `BookResponse`.

**Global daily spend alert**: `GLOBAL_DAILY_SPEND_ALERT_USD` (default 20)
— after each book is created, the sum of `estimated_cost_usd` for every
book created since UTC midnight (including the new one) is checked
against this threshold. Crossing it captures a Sentry warning via
`capture_message_with_context` (a safe no-op with `SENTRY_DSN` unset, same
as the existing exception tracking) — this is purely observational and
never blocks a request. Since both NVIDIA and Gemini are free tiers,
every real `estimated_cost_usd` is `0.0` today, so this alert cannot
actually fire in production yet — the wiring is in place for the day a
paid provider is added.

## Per-chapter progress (v9)

`GET /books/{id}/events`'s `progress` payload now includes a `chapters`
array (see the updated example above), one entry per chapter in the
book's outline: `{"id", "title", "status": "pending" | "done", "score",
"attempts", "passed"}`. A book can spend most of its wall-clock time
inside a single `write` node while it writes and judges every chapter one
at a time — previously `/events` went silent for that entire stretch since
the book-wide node position never changed; now a chapter finishing counts
as a real change and gets its own event.

`score`/`attempts`/`passed` are `null` until a chapter is `"done"`:
`score` is the judge's score for whichever attempt `ai_llm` kept (the one
that passed, or the last one if it never did), `attempts` is how many
tries it took (1 means it passed on the first attempt), and `passed` is
whether that score ever reached `PASS_SCORE`. A chapter can be `"done"`
with `passed: false` — root `AGENTS.md`'s quality gate never blocks the
book, so a chapter that exhausts `MAX_REFINE_ATTEMPTS` still gets its best
attempt kept and included; `passed: false` is a real diagnostic signal to
go look at that chapter, not a failure state.

This data is computed fresh from disk on every poll (`ai_llm`'s
`work/notes/<key>.md` + `<key>.status.json` sidecar, one pair per chapter)
— nothing new is written to Postgres, the same way book-wide node progress
already isn't.

## Tests

Tests run against the real Postgres/Redis from `docker compose up -d`
(no DB mocking, per `backend/AGENTS.md`'s testing rules) and a separate
`video2book_test` database so they never touch dev data:

```
docker compose exec postgres psql -U video2book -d video2book -c "CREATE DATABASE video2book_test OWNER video2book;"
pytest
```

No real LLM or YouTube calls are made in tests — `ai_llm.app.graph.run_book`
is monkeypatched at the `api.jobs.run_book.ai_llm_run_book` boundary. S3
is real (the local S3Mock container), same as Postgres/Redis — no S3
client mocking either.

## What's in v1 / v2 / v3 / v4 / v5 / v6 / v7 / v8 / v9 / what's not

- **v1** (`sprints/v1/PRD.md`): create → queue → worker → status core loop.
- **v2** (`sprints/v2/PRD.md`): `/health`, structured JSON logging,
  `GET /books/{id}/pdf`.
- **v3** (`sprints/v3/PRD.md`): plan/render phase split, `GET`/`PUT
  /books/{id}/outline`, `POST /books/{id}/retry`.
- **v4** (`sprints/v4/PRD.md`): `POST /users` + API-key auth on every
  book-scoped endpoint, per-user concurrent-book rate limiting.
- **v5** (`sprints/v5/PRD.md`): rendered PDFs move to S3, `GET
  /books/{id}/pdf` redirects to a presigned URL, `PDF_RETENTION_DAYS` +
  `python -m api.retention`, `/health` also checks S3.
- **v6** (`sprints/v6/PRD.md`): optional Sentry error tracking with
  `book_id`/`phase` context, worker heartbeat, `/health` also checks it.
- **v7** (`sprints/v7/PRD.md`): Postgres checkpointer for LangGraph
  (replaces per-book SQLite for API-created books), live per-node
  progress via `GET /books/{id}/events` (SSE).
- **v8** (`sprints/v8/PRD.md`): upfront `MAX_BOOK_HOURS`/`MAX_BOOK_COST_USD`
  rejection at book creation (no bypass), `Book.estimated_cost_usd`
  persisted, `GLOBAL_DAILY_SPEND_ALERT_USD` global daily spend alert.
- **v9** (`sprints/v9/PRD.md`): per-chapter `score`/`attempts`/`passed`
  progress in `GET /books/{id}/events`'s `chapters` array.
- Still deferred: password/JWT/OAuth login, key rotation, actually
  honoring a reordered outline (needs an `ai_llm` change, not just this
  API), scheduling the retention script, and the rest of
  `backend/AGENTS.md`'s production-readiness checklist (backups, load
  testing, LangSmith dashboard, Bull Board, legal terms,
  rollback-on-failed-eval).
