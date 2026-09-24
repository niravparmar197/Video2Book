# Sprint v3 — PRD: Outline Review + Retry

## Overview

v1/v2 run a book start-to-finish with no stop for review, and never
populate `Video`/`Chapter` — both were explicitly deferred because the
video set isn't known until ai_llm's fetch node runs. This sprint splits
the pipeline into two phases (**plan** then **render**) so a user can
review and adjust the chapter plan before the (slow, LLM-heavy) render
step runs, and adds `POST /books/{id}/retry` to resume a failed book
without redoing completed work — both by calling ai_llm's own existing
`run_plan`/`run_book`/`resume_book` functions, never reimplementing their
logic here.

## Goals

- `POST /books/youtube` now stops after planning: it runs ai_llm's
  `run_plan` (fetch→chunk→topics→write→outline, no render) and lands the
  book in `outline_ready`, with `Video`/`Chapter` rows populated from the
  result — instead of running the full pipeline unattended.
- `GET /books/{id}/outline` returns the persisted chapter plan (id,
  title, order, skip, locked) once it exists.
- `PUT /books/{id}/outline` persists skip/locked edits — the two fields
  ai_llm's outline node actually preserves across a re-run (see
  "Known limitation" below) — to both the DB and `outline.json` on disk,
  then enqueues the render phase (`run_book`) to produce the PDF. This
  doubles as "approve": saving with no changes still triggers the render.
- `POST /books/{id}/retry` re-enqueues a `failed` book by calling ai_llm's
  own `resume_book(output_dir)` — its checkpoint + disk-cached steps mean
  chapters that already passed verification aren't redone. 409 if the
  book isn't currently `failed`.
- `Book.status` grows from v1/v2's `queued`/`running`/`done`/`failed` to
  `queued → planning → outline_ready → rendering → done`/`failed`.

## User Stories

- As a user, I want to see the chapter plan before the expensive render
  step runs, so I can skip a chapter I don't want in the book.
- As a user, I want to mark a chapter `locked` so re-running the plan
  (e.g. after adding more videos to a playlist in a later sprint) never
  silently changes something I already reviewed.
- As a user, whose book failed partway through rendering, I want to
  retry it without waiting for the whole book to be regenerated from
  scratch.

## Technical Architecture

Builds on v1/v2's `api/` package + `ai_llm`'s `app.graph` bridge. The
worker's single job queue now carries a `phase` and dispatches
differently per phase:

```
 POST /books/youtube ──▶ Book(status=queued) ──▶ enqueue phase=plan
                                                        │
                                                        ▼
                                    worker: ai_llm.run_plan(url, output_dir)
                                    status: queued → planning → outline_ready
                                    upserts Video + Chapter rows from the result
                                                        │
        GET /books/{id}/outline ◀── reads Chapter rows ┘
                │
                ▼
 PUT /books/{id}/outline (skip/locked edits)
        │  persists DB + outline.json on disk
        ▼
   enqueue phase=render
        │
        ▼
 worker: ai_llm.run_book(url, output_dir)   [re-reads outline.json;
 status: outline_ready → rendering → done    fetch/chunk/topics/write are
                                              disk-cached, so only
                                              outline→render actually reruns]

 POST /books/{id}/retry (only if status == "failed")
        │
        ▼
 enqueue phase=retry
        │
        ▼
 worker: ai_llm.resume_book(output_dir)
 status: failed → rendering → done/failed
```

**Chapter/Video schema rework**: v1's `Chapter` FK'd to a single `Video`,
which only fits `BOOK_ORDER=video`. ai_llm's actual default
(`BOOK_ORDER=topic`, root `AGENTS.md`) merges chapters across multiple
source videos (`chapter["sources"]`), so `Chapter` now belongs directly
to `Book`, with a `source_video_ids` (JSON-encoded list) column instead
of a single-video FK, plus `ai_llm_chapter_id` (ai_llm's own stable
`chapter:<id>`), `order_index`, `skip`, `locked`. A new Alembic migration
replaces the v1 `chapters` table shape.

**ai_llm change**: `run_plan()` currently returns only `chapters`; it
needs to also return `videos` so the backend can populate the `Video`
table without re-deriving it. One small, additive change to
`ai_llm/app/graph.py`'s return value and its one CLI caller in
`ai_llm/app/cli.py` — no pipeline logic changes, ai_llm still works
standalone from the CLI.

**Known limitation (by design this sprint)**: ai_llm's `run_outline`/
`run_topic_outline` always recompute `order` from playlist/topic
position — only `skip`/`locked` survive a re-run
(`_preserve_flags` in `ai_llm/app/nodes/outline.py`). So `PUT
/books/{id}/outline` only persists skip/locked; a reordered chapter list
will not actually change render order until a follow-up sprint teaches
ai_llm's outline node to honor a persisted order. Flagged explicitly so
nobody is surprised the "order" field in the response doesn't change on
PUT.

## Out of Scope (v4+)

- Actually honoring a manually edited chapter *order* (see "Known
  limitation" above) — needs a change to `ai_llm/app/nodes/outline.py`
  itself, not just this API layer.
- Per-chapter pass/fail status (`Chapter.status` stays `"pending"`,
  informational only) — would need ai_llm's `run_book`/`resume_book` to
  return per-chapter verify results, which they don't yet.
- `GET /books/{id}/events` (live per-node progress) and the Postgres
  checkpointer swap for LangGraph.
- S3 storage, auth, and the rest of `backend/AGENTS.md`'s
  production-readiness checklist.

## Dependencies

- Sprints v1 (`sprints/v1/`) and v2 (`sprints/v2/`) complete: the
  create → queue → worker → status core loop, `/health`, structured
  logging, and `GET /books/{id}/pdf` all exist and are tested against
  real Postgres/Redis.
- `docker-compose up -d` available locally, same as v1/v2.
