# Sprint v9 — Walkthrough

## Summary

Sprint v9 extends the `GET /books/{id}/events` Server-Sent Events stream
(shipped in v7) with per-chapter progress. `ai_llm`'s write step now
persists a small `score`/`attempts`/`passed` sidecar file next to each
chapter's notes as soon as that chapter's write-and-verify loop finishes,
a new read-only `get_chapter_progress()` reads those sidecars back off
disk, and the backend folds the result into every `progress` event as a
`chapters` array — so a book that spends most of its wall-clock time
inside one long `write` node (writing and judging every chapter one at a
time) now produces real, visible progress instead of going silent for
that entire stretch.

## Architecture Overview

```
 ai_llm/ (per output_dir, on disk — unchanged storage model, new files)
 ┌───────────────────────────────────────────────────────────────────┐
 │ work/chunks/<video_id>_<NNN>.json  ─┐                              │
 │ work/topics/<video_id>_<NNN>.json  ─┼─▶ app/nodes/write.py          │
 │                                     │      _write_and_refine()      │
 │                                     │      (write, judge, refine,   │
 │                                     │       up to MAX_REFINE_ATTEMPTS)│
 │                                     │           │                  │
 │                                     │           ▼ (notes, score,   │
 │                                     │              attempts)       │
 │                                     ▼                              │
 │                       work/notes/<key>.md            (unchanged)   │
 │                       work/notes/<key>.status.json   (NEW, v9)     │
 │                       {"score": 9, "attempts": 1, "passed": true}  │
 └───────────────────────────────────────┬─────────────────────────────┘
                                          │  read-only, no LangGraph
                                          ▼
                       app/graph.py: get_chapter_progress(output_dir)
                         reads outline.json (chapter list) +
                         work/notes/<key>.md / .status.json per chapter
                                          │
                                          ▼
 backend/                    api/ai_llm_bridge.py
                                get_chapter_progress = _graph.get_chapter_progress
                                          │
                                          ▼
                       api/routers/books.py: _progress_events()
                         (v7's existing poll loop, extended)
                         each tick:
                           progress = ai_llm_get_progress(...)      (v7)
                           chapters = ai_llm_get_chapter_progress(...)  (v9, NEW)
                           progress["chapters"] = chapters
                           dedup key now includes chapter state too
                                          │
                                          ▼  event: progress
                       GET /books/{id}/events (SSE)      data: {..., "chapters": [...]}
                                          │
                                          ▼
                                     API client
```

## Files Created/Modified

### `ai_llm/app/nodes/write.py`

**Purpose**: Writes chapter notes from chunk transcripts and judges/refines
them (unchanged responsibility) — now also records the outcome of that
judging as a small artifact on disk.

**Key Functions/Components**:
- `_write_and_refine(initial_prompt, transcript) -> tuple[str, int, int]` — was `-> str`; now also returns the judge score of whichever attempt was kept and how many attempts it took.
- `chapter_status_path(key, output_dir) -> Path` — new. `work/notes/<key>.status.json`, sibling of the existing `notes_output_path`'s `.md` file, same `<key>`.
- `_write_chapter_status(key, output_dir, score, attempts)` — new private helper; writes `{"score", "attempts", "passed"}` (`passed = score >= settings.pass_score`).
- `run_write(video_id, output_dir)` — unchanged signature/notes output; now also aggregates every chunk section's `(score, attempts)` and writes the chapter's status sidecar.
- `run_write_topic(topic, output_dir)` — same, for the topic-mode (one merged-topic chapter, one section) case.

**How it works**:

`_write_and_refine`'s loop already tracked a judge score internally to
decide whether to keep refining; it just never returned that information
to its caller. The change is minimal — track `score` across iterations and
return it plus the attempt count that was reached:

```python
for attempt in range(1, settings.max_refine_attempts + 1):
    notes = call_writer(prompt).strip()
    result = run_verify(transcript, notes)
    score = result.score

    if score >= settings.pass_score:
        return notes, score, attempt
    ...
return notes, score, settings.max_refine_attempts
```

A video-mode chapter (`run_write`) is actually built from *several*
sections — one per transcript chunk — each independently written and
judged. Rather than exposing per-section detail (a unit a caller outside
this module has no reason to know about), the chapter-level status
aggregates the *weakest* section: `min(scores)` and `max(attempts)`. A
chapter with five clean sections and one that needed every refine attempt
is reported as "needed help," not "5/6 clean" — the number a human
actually wants when deciding whether to go look at a chapter.

```python
sections, scores, attempts_list = [], [], []
for chunk_path in chunk_paths:
    ...
    notes, score, attempts = _write_chunk_notes(chunk_path, topics_path)
    sections.append(notes); scores.append(score); attempts_list.append(attempts)

notes_path.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
_write_chapter_status(video_id, output_dir, min(scores), max(attempts_list))
```

`run_write_topic` has only one section (the merged-topic synthesis is a
single LLM call across every source chunk), so it writes its own
`(score, attempts)` straight through, no aggregation needed.

### `ai_llm/app/graph.py`

**Purpose**: Owns the LangGraph pipeline definitions — now also owns the
one new read-only function that reports per-chapter progress.

**Key Functions/Components**:
- `get_chapter_progress(output_dir) -> list[dict]` — new.

**How it works**:

Unlike `get_progress` (v7), this function never touches LangGraph — a
chapter's status is a plain disk artifact (the notes file and its status
sidecar), not graph checkpoint state, so there's no graph to build and no
`checkpointer`/`book_order` parameter needed. It reads `outline.json` (the
chapter list `ai_llm`'s outline node already writes) and, for each
chapter, works out which notes-file "key" that chapter maps to. That key
is self-evident from the chapter's own shape: video-mode chapters carry a
`video_id`; topic-mode chapters don't, so `f"topic_{chapter['slug']}"` is
used instead — the exact same key convention `run_write`/`run_write_topic`
already use.

```python
for chapter in chapters:
    key = chapter["video_id"] if "video_id" in chapter else f"topic_{chapter['slug']}"
    done = notes_output_path(key, output_dir).exists()
    status = json.loads(chapter_status_path(key, output_dir).read_text(...)) if done and ... else None
    progress.append({
        "id": chapter["id"], "title": chapter["title"],
        "status": "done" if done else "pending",
        "score": status["score"] if status else None,
        "attempts": status["attempts"] if status else None,
        "passed": status["passed"] if status else None,
    })
```

If `outline.json` doesn't exist yet (the outline node hasn't run), the
function returns `[]` rather than raising — the same "not started yet
isn't an error" convention `get_progress` already established in v7.

### `backend/api/ai_llm_bridge.py`

**Purpose**: The one place `ai_llm/`'s standalone `app.*` modules are
imported into the backend, since `ai_llm/` isn't pip-installed (see root
`AGENTS.md`).

**Key Functions/Components**:
- `get_chapter_progress = _graph.get_chapter_progress` — new one-line re-export, same pattern as `run_book`/`run_plan`/`resume_book`/`get_progress`/`estimate_playlist`/`load_settings`.

**How it works**: nothing new mechanically — this file's whole job is to
add `ai_llm/` to `sys.path` just long enough to import its modules, then
remove it again so the two projects' same-named `app`/`api` packages never
collide. `get_chapter_progress` slots into the existing list of
re-exported function references.

### `backend/api/routers/books.py`

**Purpose**: The books router — `_progress_events`, the async generator
backing `GET /books/{id}/events`, is the piece this sprint touches.

**Key Functions/Components**:
- `_progress_events(book_id)` — extended: now also polls `get_chapter_progress` every tick and folds it into the `progress` payload; its change-detection key is extended to include chapter state.

**How it works**:

Each poll tick already called `ai_llm_get_progress` for book-wide node
position (v7). This sprint adds a second cheap disk read alongside it and
merges the result into the same payload:

```python
progress = await asyncio.to_thread(ai_llm_get_progress, output_dir, checkpointer, None, phase)
chapters = await asyncio.to_thread(ai_llm_get_chapter_progress, output_dir)
progress["chapters"] = chapters

key = (
    progress["current_node"],
    tuple(progress["completed_nodes"]),
    tuple((c["id"], c["status"], c["score"], c["attempts"]) for c in chapters),
)
if key != last_sent:
    last_sent = key
    yield _sse("progress", progress)
```

The important change is in that `key` tuple. Before v9, the stream only
emitted a new event when the *node* position changed — during a long
`write` node, that position doesn't move while chapter after chapter gets
written and judged underneath it, so the stream would go quiet for the
entire stretch. Including each chapter's `(id, status, score, attempts)`
in the dedup key means a single chapter finishing — with the book-wide
node position completely unchanged — now produces a real, distinct SSE
event.

## Data Flow

1. A book reaches the `write` phase; `ai_llm`'s `write` node starts looping over chapters (one video per chapter, or one merged topic per chapter, depending on `BOOK_ORDER`).
2. For each chapter, `_write_and_refine` writes a draft, judges it, and refines up to `MAX_REFINE_ATTEMPTS` times; once resolved, `run_write`/`run_write_topic` writes both `work/notes/<key>.md` (the chapter's content) and `work/notes/<key>.status.json` (its score/attempts/pass outcome) to disk.
3. Independently, a client holding open `GET /books/{id}/events` triggers `_progress_events`'s poll loop (`EVENTS_POLL_SECONDS`, default 2s) — each tick calls both `get_progress` (book-wide node position, from the Postgres checkpointer) and `get_chapter_progress` (per-chapter status, from disk).
4. If either the node position or any chapter's `(id, status, score, attempts)` changed since the last tick, a new `event: progress` is sent with the full current picture, including the `chapters` array.
5. Once the book's `Book.status` reaches `done`/`failed`, one final terminal event is sent and the stream closes — unchanged from v7.

## Test Coverage

- **Unit (ai_llm)**: 7 new tests.
  - `ai_llm/tests/unit/test_write.py` (4 new): `_write_and_refine` returns `attempts == 1` on a first-try pass and `attempts == settings.max_refine_attempts` with the last score when it never passes; `run_write` aggregates two chunk sections' `(score, attempts)` down to the weaker one; `run_write_topic` writes its own single-section status correctly.
  - `ai_llm/tests/unit/test_graph.py` (3 new): `get_chapter_progress` returns `[]` before `outline.json` exists; a 3-chapter video-mode fixture (one done+passed, one done+not-passed, one pending) reports all three shapes correctly; a topic-mode fixture confirms the `topic_<slug>` key derivation.
- **Unit (backend)**: 1 new test in `tests/unit/test_ai_llm_bridge.py` — `get_chapter_progress` is importable/callable with the expected `(output_dir,)` signature.
- **Integration (backend)**: 2 new tests.
  - `tests/integration/test_books_events.py` — a deterministic test (stubbed `ai_llm_get_progress`/`ai_llm_get_chapter_progress`) proving a chapter transitioning from `pending` to `done` while the book-wide node stays fixed produces two distinct `progress` events, not one.
  - `tests/integration/test_books_events_real_pipeline.py` — a real end-to-end test: a real uvicorn server, the real `ai_llm` graph, a real Postgres checkpointer, and a real 2-chapter run (only the LLM/video/compile boundary stubbed) where one chapter's first judge attempt deliberately fails and its second passes. Asserts no chapter's observed status ever regresses, at least one chapter is observed reaching `done` with a real, non-null score/attempts/passed, and — when it's caught by a poll — the refined chapter's real `attempts == 2`/`passed == true` shape. Verified stable across 4 consecutive runs before being treated as done, given this test's inherent sensitivity to real OS thread scheduling (same documented tradeoff as v7's own real-pipeline test).

Full suite counts at the end of this sprint: **210/210** passing in `ai_llm/`, **12/12** passing on the targeted backend test files touched by this sprint (bridge + both events test files).

## Security Measures

- No new attack surface: `get_chapter_progress` is a pure, read-only disk read scoped to a book's own `output_dir`; nothing new is written to Postgres, and no new endpoint was added (the existing `/events` auth/ownership check — 404 for an unknown or another user's book, 401 without auth — is unchanged and still applies).
- `bandit -r api -ll` clean on the backend; `bandit -q -ll app/nodes/write.py app/graph.py` clean on the touched `ai_llm` files.
- No real LLM/YouTube calls introduced in any new test — the real-pipeline test stubs the same LLM/video/compile boundary every other test in that file already stubs, per root `AGENTS.md`'s testing rule.

## Known Limitations

- **Aggregated, not per-section, detail**: a video-mode chapter's `score`/`attempts` are the weakest section's numbers, not a breakdown per chunk. Deliberate (see "How it works" above), but it means a caller can't tell *which* section of a multi-chunk chapter needed the extra attempts, only that one did.
- **Render/compile phase not covered**: `chapters` only reflects the write/verify phase. A chapter that's been written and judged but not yet compiled to PDF still shows as `"done"` — "done" here means "notes finalized," not "fully rendered."
- **Nothing persisted to Postgres**: chapter status is recomputed from disk on every single poll. This is consistent with how v7's book-wide progress already works (also recomputed every poll, nothing cached), but it does mean a very large chapter count means a proportionally larger number of small file reads per poll tick — not measured against a real 30-hour/hundred-chapter playlist in this sprint.
- **Polling can miss transitions**: same tradeoff v7 already accepted for node-level progress. A chapter can go from `pending` straight to `done` between two polls without an intermediate "in progress" state ever being observed — there's no "chapter N is currently being written" signal, only "not yet" and "finished."
- **This session hit real cross-session test flakiness**: while finishing this sprint, several other active Claude Code sessions on the same machine were concurrently running their own test suites against the same shared `docker compose` Postgres/Redis containers, and one was concurrently editing `api/models.py`/`api/schemas.py`/a status test (adding unrelated `url`/`created_at`/`videos` fields) and, after this sprint's work was finished, `api/routers/books.py` again (adding an unrelated `POST /books/{id}/cancel` endpoint, visible in the file's current state but **not** part of this sprint's scope). Every transient failure this sprint hit was confirmed non-reproducible on an immediate isolated retry, and this sprint's own files were not the ones being concurrently edited. Documented here, not silently absorbed, per the same lesson `ai_llm/sprints/v7/TASKS.md`'s Task 4 already logged for exactly this class of shared-machine collision.

## What's Next

- Per-chapter render/compile status, if the write/verify signal proves useful in practice — this sprint deliberately scoped that out (see PRD's Out of Scope) since write/verify is where the real "pass/fail" content lives.
- Section-level (chunk-level) detail within a video-mode chapter, if the aggregated min/max signal turns out to hide too much (e.g. a user wanting to know *which* chunk of a 6-chunk video needed refining).
- The rest of `backend/AGENTS.md`'s production-readiness checklist remains open regardless of this sprint: honoring a reordered outline, password/JWT/OAuth login, key rotation, backups, load testing, LangSmith dashboard, Bull Board, scheduling the retention script, legal terms, rollback-on-failed-eval.
- Given the concurrent-session collision noted above, whoever plans the next sprint should confirm with any other active session on this machine before running the full test suite or editing `api/models.py`/`api/schemas.py`/`api/routers/books.py` — at least one other in-flight change (a cancel-book endpoint) already landed in `books.py` outside of any tracked sprint here.
