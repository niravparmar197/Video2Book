# Sprint v8 — PRD: Cost Ceiling Enforcement + Daily Spend Alert

## Overview

`ai_llm`'s `check_budget` node already enforces `MAX_BOOK_HOURS`/
`MAX_BOOK_COST_USD` for the standalone CLI, with a `--force` bypass for a
single operator who knows what they're doing. The backend API has no
equivalent: `POST /books/youtube` today creates a `Book` row and queues a
job for any URL, and the only way an over-budget playlist gets caught is
after the worker has already fetched every video and hit `ai_llm`'s
`BudgetExceededError` mid-run. This sprint adds an upfront check at
creation time — with no `--force` equivalent, since this is a shared
multi-tenant API, not a personal CLI — plus a global daily spend alert
that's correct today (every real cost is $0.00, both providers are free
tiers) and becomes real the moment a paid provider is configured, per
`backend/AGENTS.md`'s production-readiness checklist ("Cost ceiling:
`MAX_BOOK_COST_USD` enforced plus a global daily spend alert").

## Goals

- `POST /books/youtube` estimates a playlist's total duration and cost
  before creating any `Book` row or queuing any job, and rejects it
  (`422`) if either exceeds `MAX_BOOK_HOURS`/`MAX_BOOK_COST_USD` — reusing
  `ai_llm`'s own settings as the single source of truth, never a
  duplicated backend copy that could drift out of sync.
- `ai_llm`'s existing `check_budget` node stays the backstop for the case
  the upfront estimate can't catch (e.g. real per-video duration
  discovered only after fetch differs from the estimate) — no change
  needed there; `process_run_book` already surfaces any `BudgetExceededError`
  as a `failed` book with `error_message` set.
- `Book.estimated_cost_usd` is persisted at creation, so a global daily
  spend total can be computed without re-estimating every book on every
  request.
- Once the sum of `estimated_cost_usd` for books created since UTC
  midnight crosses a new `GLOBAL_DAILY_SPEND_ALERT_USD` setting, a warning
  is captured (Sentry, when configured — otherwise a safe no-op, same
  pattern as existing error tracking) — observational only, never blocks
  book creation.

## User Stories

- As an operator, I want an obviously-too-large playlist rejected at
  submission time with a clear reason, so it never occupies a worker slot
  or burns rate-limit budget before failing anyway.
- As an operator, I want to be warned once total estimated spend for the
  day crosses a threshold, so I notice a cost spike before it becomes a
  bill, once a paid provider is in the mix.
- As a developer, I want the backend to reuse `ai_llm`'s own
  `MAX_BOOK_HOURS`/`MAX_BOOK_COST_USD` values instead of a second copy, so
  the two layers can never silently disagree on what "over budget" means.

## Technical Architecture

```
 api/ai_llm_bridge.py
   + estimate_playlist = _estimate.estimate_playlist   (re-exported,
                                                          same pattern as
                                                          run_book/etc.)
   + load_settings = _config.load_settings             (re-exported
                                                          function, not a
                                                          baked-in value —
                                                          same reason
                                                          run_book isn't
                                                          called eagerly)

 POST /books/youtube
   │
   ▼  asyncio.to_thread(ai_llm_bridge.estimate_playlist, url)
   │  (network call to YouTube for metadata -- same call ai_llm's own
   │   --estimate makes; run off the event loop, same as every ai_llm
   │   call this router already makes)
   ▼
   sum hours / estimated_cost_usd across every video in the playlist
        │
        ├─ over ai_llm_bridge.load_settings().max_book_hours
        │  or .max_book_cost_usd
        │       │
        │       ▼  422, no Book row created, no job queued
        │
        └─ within budget
                │
                ▼  Book(estimated_cost_usd=<summed total>, ...) created,
                   plan job enqueued as today
                        │
                        ▼  sum(Book.estimated_cost_usd) for every book
                           created since UTC midnight today (including
                           this one)
                                │
                                ├─ >= GLOBAL_DAILY_SPEND_ALERT_USD
                                │       ▼  capture_message_with_context(
                                │            "...", level="warning")
                                │          (no-op if SENTRY_DSN unset)
                                │
                                └─ under threshold -> nothing

 api/error_tracking.py
   + capture_message_with_context(message, level="warning", **context)
       mirrors capture_exception_with_context; safe no-op with no DSN
       configured, same as the existing exception helper.
```

**Why an upfront estimate call, not just the existing backstop**: the
backstop only fires after `run_plan`'s worker job has already fetched
every video in the playlist — for a genuinely oversized playlist (the
motivating case) that's real wasted worker time and rate-limit budget
before it fails anyway. `ai_llm/`'s own `--estimate` CLI flag already does
exactly this duration/cost calculation without calling any LLM, so this
sprint reuses it rather than re-implementing it.

**Why no `--force` equivalent**: `ai_llm`'s `--force` exists for a single
operator running their own CLI who has decided to accept an over-budget
run. The backend serves multiple users sharing one worker pool and one
provider rate-limit budget — one user forcing an oversized playlist
through would degrade every other user's books, which
`max_concurrent_books_per_user` (v4) already exists to prevent in a
different dimension. A shared API should not offer a bypass at all.

**Why reuse `ai_llm`'s settings instead of a backend copy**: a duplicated
`MAX_BOOK_HOURS`/`MAX_BOOK_COST_USD` in `api/config.py` could silently
drift from `ai_llm`'s own values (set via the same env vars, read by two
different `Settings` dataclasses) — the backstop and the upfront check
would then disagree about what "over budget" means. Re-exporting
`load_settings` as a function (not calling it once at import time) keeps
this consistent with how `run_book`/`run_plan`/`get_progress` are already
re-exported, and keeps it testable via monkeypatching `os.environ` the
same way `ai_llm`'s own budget tests already do.

## Out of Scope (v9+)

- A backend-side cost *model* for a real paid provider (today's
  `estimated_cost_usd` is always `0.0` in `ai_llm`'s own `estimate.py` —
  this sprint plumbs the number through, it doesn't compute a new one).
- Per-user spend limits or billing (`GLOBAL_DAILY_SPEND_ALERT_USD` is a
  single global threshold, not per-user).
- Actually pausing new book creation once the daily alert fires — this
  sprint is observational only, per `backend/AGENTS.md`'s checklist
  wording ("a global daily spend alert").
- Everything else still open on `backend/AGENTS.md`'s production-readiness
  checklist: honoring a reordered outline, per-chapter progress,
  password/JWT/OAuth login, key rotation, backups, load testing,
  LangSmith dashboard, Bull Board, scheduling the retention script, legal
  terms, rollback-on-failed-eval.

## Dependencies

- Sprints v1-v7 complete: core loop, health/logging/PDF download, outline
  review + retry, auth + rate limiting, S3 storage, Sentry + worker
  heartbeat, Postgres checkpointer + `/events`.
- `ai_llm`'s `app/estimate.py` (`estimate_playlist`) and `app/config.py`
  (`load_settings().max_book_hours` / `.max_book_cost_usd`) already exist
  and are exercised by `ai_llm`'s own `--estimate` CLI path and its
  sprints/v7 budget-gate tests — this sprint only adds a second caller
  (the backend), no `ai_llm` changes.
- `docker compose up -d` Postgres (for the new `Book` column/migration) —
  no new local service.
