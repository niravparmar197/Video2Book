# Sprint v7 — PRD: Live Progress (`/events` + Postgres Checkpointer)

## Overview

`GET /books/{id}/events` and the Postgres checkpointer swap for LangGraph
have been listed in the API table and stack table since v1 and deferred
every sprint since (most recently v6's "Out of Scope"). Today a book's
only visibility while running is the coarse `status` column
(`planning`/`rendering`/etc.) from `GET /books/{id}` — a user watching a
30-hour playlist render has no way to tell "fetching video 4 of 12" from
"stuck." This sprint ships both together, since `/events` needs
per-node state that only a shared, queryable checkpointer can provide —
`ai_llm`'s current per-book SQLite checkpoint file isn't visible to the
API process at all.

## Goals

- `run_book`/`run_plan`/`resume_book` checkpoint into Postgres instead of
  a per-`output_dir` SQLite file, so the API process can read a book's
  live LangGraph state without touching the worker's filesystem.
- `GET /books/{id}/events` streams node-level progress (which pipeline
  step just finished, which is next) via Server-Sent Events, from
  `queued` through `done`/`failed`.
- `ai_llm/` stays a working standalone CLI with zero behavior change by
  default — the checkpointer becomes an optional, injectable parameter;
  omitting it keeps today's exact SQLite-per-`output_dir` behavior.

## User Stories

- As a user, I want to watch a book move through fetch → chunk → topics →
  write → outline → book_pass → render in real time, so I know it's
  actually progressing on a long playlist instead of just waiting on a
  spinner.
- As an operator, I want a book's current LangGraph node visible from the
  API process itself, so debugging a stuck book doesn't require SSH'ing
  into the worker to inspect a SQLite file under `output/`.
- As a developer running `ai_llm/` standalone from the CLI, I want this
  change to be invisible — `--resume` and the existing SQLite checkpoint
  file must keep working exactly as before.

## Technical Architecture

```
 api/checkpointer.py
   get_checkpointer() -> PostgresSaver bound to settings.database_url
   ensure_checkpoint_tables()  -- idempotent .setup(), called once at
                                   API + worker startup

 ai_llm/app/graph.py  (backward-compatible, optional param)
   run_book(url, output_dir, force=False, checkpointer=None)
   run_plan(url, output_dir, force=False, checkpointer=None)
   resume_book(output_dir, checkpointer=None)
       checkpointer=None -> unchanged: SqliteSaver.from_conn_string(
                              output_dir/graph_state.sqlite)   (CLI path)
       checkpointer=<given> -> used as-is, caller (backend) owns its
                              lifecycle                        (API path)

   get_progress(output_dir, checkpointer, book_order) -> dict
       read-only: graph.get_state(config) against whichever graph
       variant book_order implies; returns
       {"completed_nodes": [...], "current_node": str | None,
        "next_nodes": [...], "step": int}
       -- node-name/ordering knowledge stays in ai_llm, same place the
       graphs themselves are defined; backend never hardcodes a node list.

 api/ai_llm_bridge.py
   + get_progress = _graph.get_progress   (re-exported, same pattern as
                                            run_book/run_plan/resume_book)

 api/jobs/run_book.py
   process_run_book(...) now passes get_checkpointer() (thread_id=book_id)
   into every ai_llm_run_book/run_plan/resume_book call

 GET /books/{id}/events   (api/routers/books.py or a new events.py)
   auth + ownership check (existing pattern) -> 404 if not found/not yours
        │
        ▼  StreamingResponse, media_type="text/event-stream"
   loop: asyncio.to_thread(get_progress, ...) every EVENTS_POLL_SECONDS
        │  diff against last-sent node -> yield `event: progress` on change
        ▼
   book status flips to done/failed (poll api.models.Book) -> yield a
   final event, close the stream
```

**Why polling, not pub/sub**: v6 deliberately avoided adding new
infrastructure for observability (no local Sentry service); this sprint
follows the same principle. The Postgres checkpointer is already the
source of truth and already paid for (Postgres is running regardless) —
polling it on a short interval is simpler than adding a Redis pub/sub
channel the worker has to remember to publish to on every node
transition, and it can't drift out of sync with what actually happened
since it reads the same state `--resume` would.

**Why an optional parameter, not a full rewrite**: `ai_llm/` must keep
working standalone (root `AGENTS.md`). Every `run_book`/`run_plan`/
`resume_book` caller that doesn't pass `checkpointer` — the CLI, every
existing `ai_llm` test — gets byte-for-byte the same SQLite-backed
behavior as today.

## Out of Scope (v8+)

- Per-chapter progress within a book (e.g. "chapter 4 of 12 written") —
  still blocked on `ai_llm` returning per-chapter results mid-run, the
  same gap v3/v5/v6 already noted; this sprint's `/events` reports
  per-*node* progress (one book-wide pipeline position), not per-chapter.
- Honoring a reordered outline mid-run.
- Cost ceiling enforcement (`MAX_BOOK_COST_USD` + a global daily spend
  alert), LangSmith tracing dashboard, Bull Board, password/JWT/OAuth
  login, key rotation, backups, load testing — all still open per
  `backend/AGENTS.md`'s production-readiness checklist, deferred again.
- Migrating existing in-flight SQLite-checkpointed books to Postgres —
  this sprint's Postgres checkpointer applies to books created after it
  ships; no backfill tooling.

## Dependencies

- Sprints v1-v6 complete: core loop, health/logging/PDF download, outline
  review + retry, auth + rate limiting, S3 storage, Sentry + worker
  heartbeat.
- `ai_llm`'s `build_graph`/`build_plan_graph`/`build_topic_graph`/
  `build_topic_plan_graph` already accept an optional `checkpointer`
  param (confirmed in `app/graph.py`) — this sprint threads that same
  parameter through the three public entry points backend calls
  (`run_book`/`run_plan`/`resume_book`), which don't yet expose it.
- `docker-compose up -d` Postgres (already required for `users`/`books`/
  `videos`/`chapters`) — no new local service.
- This sprint touches `ai_llm/app/graph.py`. It's unrelated to `ai_llm`'s
  own in-progress `sprints/v7` (rate-limit pacing, budget gates, scale
  testing) — different concern, same file; check for merge conflicts
  against that work before landing.
