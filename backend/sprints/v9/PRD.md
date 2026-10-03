# Sprint v9 — PRD: Per-Chapter Progress in `/events`

## Overview

`GET /books/{id}/events` (v7) reports book-wide pipeline position —
"currently on the `write` node" — but a book can spend most of its
wall-clock time inside that single node while it writes and judges every
chapter one at a time, and today's `/events` stream goes silent for that
entire stretch (v7 PRD's own "Out of Scope"). This sprint adds a `score`/
`attempts`/pass-fail outcome per chapter, persisted by `ai_llm` as each
chapter's write-and-verify loop finishes, and surfaces it as a `chapters`
array on the existing `/events` stream — no new endpoint, no ai_llm change
that isn't required to make the data exist in the first place.

## Goals

- `ai_llm`'s write step persists a small per-chapter status sidecar
  (`score`, `attempts`, `passed`) next to the notes file it already
  writes, for both `BOOK_ORDER=video` (one chapter per video) and
  `BOOK_ORDER=topic` (one chapter per merged topic).
- `ai_llm.app.graph.get_chapter_progress(output_dir)` reads the outline's
  chapter list plus whatever notes/status files exist on disk and returns
  each chapter's current state — `pending` or `done`, with `score`/
  `attempts`/`passed` once done.
- `GET /books/{id}/events` includes a `chapters` array on every `progress`
  event, and only emits a new event when either the book-wide node
  position *or* any chapter's status actually changed — chapter-by-chapter
  writing inside a single long `write` node now produces visible
  progress instead of silence.
- `ai_llm/` run standalone from its own CLI is unaffected in output shape
  — the new sidecar file is additive next to the existing notes file, no
  existing caller's return value changes shape.

## User Stories

- As a user watching a 30-chapter book render, I want to see "12 of 30
  chapters written, chapter 7 needed 2 refine attempts" instead of just
  "still on write", so I have a real sense of progress during the longest
  part of the pipeline.
- As an operator debugging quality complaints, I want to see which
  chapters never reached `PASS_SCORE` even after refinement, so I know
  where to look without re-reading every chapter's notes by hand.
- As a developer running `ai_llm/` standalone, I want this to be
  invisible unless I go looking for the new sidecar files — `--resume`
  and every existing test keep passing unchanged.

## Technical Architecture

```
 ai_llm/app/nodes/write.py
   _write_and_refine(...) -> (notes: str, score: int, attempts: int)
       (was: -> str; both call sites below updated)

   chapter_status_path(key, output_dir) -> Path
       work/notes/<key>.status.json  (sibling of notes_output_path's
       work/notes/<key>.md -- same <key>: video_id in BOOK_ORDER=video,
       "topic_<slug>" in BOOK_ORDER=topic)

   run_write(video_id, output_dir)        -- aggregates every chunk section
   run_write_topic(topic, output_dir)     -- aggregates every source section
       both now also write chapter_status_path(key, output_dir):
       {"score": <min section score>, "attempts": <max section attempts>,
        "passed": score >= PASS_SCORE}
       (min/max, not per-section detail -- the weakest section is the
       diagnostically useful number; a chapter with 6 clean sections and
       1 that needed every attempt is a "needed help" chapter, not a
       "5/6 clean" one)

 ai_llm/app/graph.py
   get_chapter_progress(output_dir) -> list[dict]
       reads outline_json_path(output_dir) for the chapter list (mode is
       self-evident per chapter: "video_id" key present -> BOOK_ORDER=video
       key; else "topic_<slug>" -> BOOK_ORDER=topic key -- no book_order
       param needed, unlike get_progress)
       for each chapter: notes file exists? -> "done" (+ status sidecar's
       score/attempts/passed) : "pending"
       missing outline.json (outline hasn't run yet) -> [] instead of
       raising, same leniency as get_progress's empty-checkpoint case

 api/ai_llm_bridge.py
   + get_chapter_progress = _graph.get_chapter_progress

 api/routers/books.py  (_progress_events, sprints/v7's existing loop)
   each poll tick now also calls
   asyncio.to_thread(ai_llm_get_chapter_progress, output_dir)
   dedup key becomes (current_node, completed_nodes, chapters-as-tuple)
   instead of just (current_node, completed_nodes) -- a chapter finishing
   inside an unchanged "write" node position now counts as a real change
        │
        ▼  event: progress
   data: {"completed_nodes": [...], "current_node": "write",
          "next_nodes": [...], "step": 4,
          "chapters": [
            {"id": "chapter:vid1", "status": "done", "score": 9,
             "attempts": 1, "passed": true},
            {"id": "chapter:vid2", "status": "pending", "score": null,
             "attempts": null, "passed": null}
          ]}
```

**Why min/max aggregation, not per-section arrays**: `run_write` (video
mode) writes one chapter from several chunk sections; a per-section score
array would leak an internal-only unit (the chunk) into a chapter-shaped
API response, and the min score / max attempts pair already answers the
one question a caller has — "did this chapter need help, and how much."

**Why no `book_order` param on `get_chapter_progress`, unlike
`get_progress`**: `get_progress` needs `book_order` because it has to
*build a graph* (which requires knowing which graph variant) before it
can call `get_state`. `get_chapter_progress` never touches LangGraph — it
only reads `outline.json`, whose own chapter shape already tells it which
mode produced it (`video_id` present or not), so threading the parameter
through would be a second, redundant way to say the same thing.

**Why extend `/events`, not a new endpoint**: `/events` already streams
book-wide progress by polling a cheap disk read; a chapter's status is
also a cheap disk read on the same polling loop, so adding a field to the
existing payload costs one more `asyncio.to_thread` call per tick, not a
second connection, a second auth check, and a second thing to poll.

## Out of Scope (v10+)

- Per-section (chunk-level) detail within a chapter — this sprint reports
  one aggregated status per chapter, not per chunk.
- Render/compile-phase per-chapter status (which chapters have been
  compiled to PDF) — write/verify is the phase with real "pass/fail"
  content; render is comparatively fast.
- Persisting chapter status to the `Chapter` table (Postgres) — it's
  computed fresh from disk on every `/events` poll, the same as book-wide
  progress already is; no new column, no new write path to keep in sync.
- Automatically re-running a chapter that scored below `PASS_SCORE` after
  the run finishes — this sprint surfaces the signal, it doesn't act on
  it (a human deciding to `--resume` after inspecting `passed: false`
  chapters is the intended workflow for now).
- Everything else still open on `backend/AGENTS.md`'s production-readiness
  checklist: honoring a reordered outline, cost ceiling was v8 (done),
  password/JWT/OAuth login, key rotation, backups, load testing,
  LangSmith dashboard, Bull Board, scheduling the retention script, legal
  terms, rollback-on-failed-eval.

## Dependencies

- Sprints v1-v8 complete: core loop through cost-ceiling enforcement and
  the daily spend alert.
- Sprint v7's Postgres checkpointer + `/events` SSE endpoint and polling
  loop (`api/routers/books.py`'s `_progress_events`) — this sprint extends
  that loop rather than building a new one.
- `ai_llm`'s `run_outline`/`run_topic_outline` already write a stable,
  disk-persisted `outline.json` with a deterministic chapter id/slug/
  video_id shape per mode (confirmed in `app/nodes/outline.py`) — this
  sprint reads it, doesn't change its shape.
- This sprint touches `ai_llm/app/nodes/write.py` and `ai_llm/app/graph.py`.
  Check `ai_llm/sprints/` for any in-progress work on those files before
  landing, same caution v7's PRD noted for its own `graph.py` change.
