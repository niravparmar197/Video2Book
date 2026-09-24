# Sprint v6 — PRD: Error Tracking + Worker Heartbeat

## Overview

v2 gave the API and worker structured logs and a `/health` that checks
Postgres/Redis/S3, but an unhandled exception today is only visible if
someone is actively tailing logs, and a worker process that's silently
stuck (hung, crashed without exiting, OOM-killed) is indistinguishable
from one that's just idle between jobs. This sprint wires in error
tracking with `book_id`/phase context on every unhandled exception, and a
worker heartbeat `/health` can check — closing two more items on
`backend/AGENTS.md`'s production-readiness checklist.

## Goals

- Every unhandled exception in the API (via a global FastAPI exception
  handler) and every final-attempt worker failure is reported through
  `sentry_sdk`, tagged with whatever's available (`book_id`, `phase`,
  request path) — genuinely optional: with no `SENTRY_DSN` set, the SDK
  is never initialized and every call is a safe no-op, so local dev/CI
  never needs a real Sentry account.
- The worker writes a heartbeat to Redis on a fixed interval (survives
  the worker being killed: it's a TTL'd key, not a "last write ever"
  record) and clears it on a clean shutdown, so a stuck/crashed worker
  is detectable within one heartbeat interval, not just "eventually,
  when someone notices."
- `GET /health` reports the heartbeat's freshness alongside the existing
  Postgres/Redis/S3 checks from v2/v5.

## User Stories

- As an operator, I want an unhandled exception to page/notify me with
  enough context (`book_id`, what phase it was running) to start
  debugging immediately, instead of grepping logs after a user reports
  a problem.
- As an operator, I want to know within a minute that the worker process
  died, not discover it hours later because books have silently stopped
  moving past `queued`.
- As a developer running this locally, I want error tracking to be
  invisible until I actually configure a `SENTRY_DSN` — no extra local
  service to stand up, no test failures from a missing Sentry account.

## Technical Architecture

Builds on v2's logging + `/health` and v5's Redis usage. No new local
dev service — the heartbeat reuses the existing Redis container.

```
 FastAPI: @app.exception_handler(Exception)
        │  logs the exception (existing api/logging.py) +
        ▼  error_tracking.capture_exception_with_context(exc, path=...)
   sentry_sdk.capture_exception  (no-op if SENTRY_DSN unset)
        │
        ▼  still returns a normal 500 JSON body -- Sentry wiring is
           observability, it never changes API behavior

 worker: process_run_book, final-attempt failure branch
        │  existing error-level log (v2) +
        ▼  error_tracking.capture_exception_with_context(exc, book_id=, phase=)
   sentry_sdk.capture_exception

 worker: background asyncio task, every WORKER_HEARTBEAT_INTERVAL_SECONDS
        │
        ▼
   Redis SETEX "worker:heartbeat" WORKER_HEARTBEAT_TTL_SECONDS <iso ts>
        (cleared on clean shutdown, so /health flips to "stale"
         immediately instead of waiting out the TTL)

 GET /health ──▶ existing db/redis/s3 checks + Redis GET "worker:heartbeat"
                  present & unexpired -> "ok", else -> "stale"
```

**Why no local Sentry service**: unlike Postgres/Redis/S3, there's no
practical free, quick-to-run local Sentry (self-hosted Sentry is a
multi-container stack disproportionate to this sprint). Tests instead
verify *this project's* wiring — that the right `sentry_sdk` calls
happen with the right context — by monkeypatching `sentry_sdk.capture_exception`/
`set_tag`/`set_context`, never by asserting against a real Sentry
server. `init_error_tracking()` only calls `sentry_sdk.init()` at all
when `SENTRY_DSN` is set, so test/dev runs never attempt real network
I/O to Sentry regardless.

## Out of Scope (v7+)

- Per-chapter error context (`chapter_id`) — still blocked on ai_llm
  returning per-chapter results, same gap v3/v5 already noted.
- Alerting/paging on top of Sentry (Slack/PagerDuty integration,
  on-call routing) — Sentry's own alerting config, not this API.
- A dashboard for the heartbeat/error data — `/health` and Sentry's own
  UI are the interfaces this sprint ships.
- Everything else already deferred as of v5 (honoring a reordered
  outline, per-chapter status, `/events` + Postgres checkpointer,
  password/JWT/OAuth login, key rotation, Bull Board, backups, a global
  spend ceiling, scheduling the retention script).

## Dependencies

- Sprints v1-v5 complete: core loop, health/logging/PDF download,
  outline review + retry, auth + rate limiting, S3 storage, all tested
  against real Postgres/Redis/S3Mock.
- `docker-compose up -d` available locally (Postgres, Redis, S3Mock —
  no new service this sprint).
