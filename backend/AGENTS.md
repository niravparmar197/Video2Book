# backend/ — API, Database, Queue

Scope: built only after `ai_llm/` produces good PDFs. This layer does not reimplement the pipeline — it wraps `ai_llm`'s `graph.py` behind an API, a job queue, and persistent storage. Do not duplicate video/LLM logic here; import and call the core engine. See the root `AGENTS.md` for the cross-project decisions this builds on.

## Stack

| Part | Tool |
|---|---|
| API | FastAPI |
| Database | PostgreSQL + SQLAlchemy + Alembic — replaces the JSON files `ai_llm/` uses standalone: `users`, `books`, `videos`, `chapters` tables |
| Checkpointer | Postgres checkpointer for LangGraph (replaces SqliteSaver) |
| Queue | BullMQ (Python) + Redis — one `run_book` job per book, `jobId = book_id`, 3 retries, 5-min lock |
| Queue dashboard | Bull Board |
| Files | S3 |
| Deploy | Docker + AWS (ECS, RDS, ElastiCache) |
| CI | GitHub Actions |

Run the graph from a worker with `asyncio.to_thread()` — don't block the event loop on a LangGraph run.

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | /books/youtube | Create a book from links or a playlist |
| GET | /books/{id} | Book and chapter status |
| GET | /books/{id}/outline | Get the plan for review |
| PUT | /books/{id}/outline | Save order changes |
| GET | /books/{id}/events | Live progress |
| GET | /books/{id}/pdf | Download |
| POST | /books/{id}/retry | Re-run failed chapters |

## Production readiness checklist

This layer is not ship-ready until every item below holds — it's what "production-ready" means for Video2Book beyond "it makes a good PDF":

- Reliability: every job survives a crash/restart via the Postgres checkpointer — no job silently disappears.
- LLM fallback: NVIDIA → Gemini → (optional) Claude chain tested under real rate-limit conditions, not just mocks.
- Monitoring: LangSmith tracing on in production; errors, latency, and fallback rate visible on a dashboard, not just in logs.
- Error tracking: Sentry (or equivalent) catches unhandled exceptions with `book_id`/`chapter_id` context attached.
- Logging: structured JSON logs with `book_id`, `chapter_id`, `step` on every line — no secrets in logs.
- Health checks: `/health` endpoint on the API; a worker heartbeat so a stuck job is detectable.
- Secrets: API keys (NVIDIA, Gemini, Claude, LangSmith) in env vars or a secrets manager, never committed.
- Rate limiting (inbound): the API limits how many books one user can queue, so one user can't exhaust the LLM quota for everyone.
- Data retention: a clear rule for how long output files/videos are kept, with a delete path.
- Backups: Postgres has daily backups before this goes live with real user data.
- Cost ceiling: `MAX_BOOK_COST_USD` enforced plus a global daily spend alert, even though the default path is free.
- Legal: terms of use state the user is responsible for having rights to the videos they submit.
- Load test: at least one test with several books queued at once, to see how the rate limiter and queue behave under real concurrency.
- Rollback: a release that fails the LangSmith eval check does not ship.

## Testing

- Integration tests use the framework's test client (FastAPI `TestClient`) — test success and error paths, including auth and validation failures.
- Never mock the database layer in DB tests — assert against real query results against a real or test-container database, not mocks.
- Never call a real LLM or YouTube endpoint from a test — the same mocking rule from `ai_llm/AGENTS.md` applies here.
