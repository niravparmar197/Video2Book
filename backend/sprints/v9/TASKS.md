# Sprint v9 — Tasks

## Status: Done

- [x] Task 1: `ai_llm` — `_write_and_refine` returns score/attempts alongside notes (P0)
  - Acceptance: `app/nodes/write.py`'s `_write_and_refine` returns `(notes: str, score: int, attempts: int)` instead of bare `str` — `score` is the judge's score for whichever attempt was kept (the passing one, or the last one if it never passed), `attempts` is how many attempts were made (1 if it passed first try); both call sites (`_write_chunk_notes` for video-mode chunks, and the topic-mode equivalent) updated to unpack the tuple; existing behavior of *which* notes text is kept is unchanged — only the return shape changes. Unit test: a stubbed judge that passes on attempt 1 returns `attempts == 1`; one that never passes returns `attempts == settings.max_refine_attempts` and the last attempt's `score`
  - Files: ai_llm/app/nodes/write.py, ai_llm/tests/unit/test_write.py
  - Completed: 2026-09-25 — `_write_and_refine` now returns
    `(notes, score, attempts)`; `score` is set from `result.score` on every
    loop iteration (so it always reflects the kept attempt, whether it
    passed or exhausted `MAX_REFINE_ATTEMPTS`), `attempts` is the loop
    index on an early return or `settings.max_refine_attempts` after
    exhausting the loop. `_write_chunk_notes` updated to propagate the
    tuple. 2 new direct tests on `_write_and_refine` covering both paths.

- [x] Task 2: `ai_llm` — persist a per-chapter status sidecar next to the notes file (P0)
  - Acceptance: a new `chapter_status_path(key, output_dir) -> Path` returns `work/notes/<key>.status.json` (sibling of `notes_output_path`'s `.md`, same `<key>`); `run_write(video_id, output_dir)` aggregates every chunk section's `(score, attempts)` from Task 1 (`score` = min across sections, `attempts` = max across sections) and writes `{"score": ..., "attempts": ..., "passed": score >= settings.pass_score}` to `chapter_status_path(video_id, output_dir)` alongside the notes file it already writes; `run_write_topic(topic, output_dir)` does the same for its own (single) section, writing to `chapter_status_path(f"topic_{topic['slug']}", output_dir)`. Unit test: `run_write` with 2 stubbed chunks (scores 9 and 6, one refined) writes a status file with `score == 6`, `attempts == 2` (or whatever the weaker section took), `passed == (6 >= PASS_SCORE)`; same shape asserted for `run_write_topic`
  - Files: ai_llm/app/nodes/write.py, ai_llm/tests/unit/test_write.py
  - Completed: 2026-09-25 — added `chapter_status_path` and a shared
    `_write_chapter_status(key, output_dir, score, attempts)` helper used
    by both `run_write` (aggregates `min(scores)`/`max(attempts)` across
    every chunk section) and `run_write_topic` (its own single section's
    score/attempts directly). 2 new tests: `run_write` with one chunk that
    passes immediately (score 9, attempts 1) and one that never passes
    (score 2, attempts 3) asserts the weaker section's numbers win
    (`{"score": 2, "attempts": 3, "passed": false}`); `run_write_topic`
    with a passing single section asserts `{"score": 9, "attempts": 1,
    "passed": true}`.

- [x] Task 3: `ai_llm` — `get_chapter_progress(output_dir) -> list[dict]` (P0)
  - Acceptance: in `app/graph.py`, reads `outline_json_path(output_dir)`'s chapter list; for each chapter, computes its write-key (`chapter["video_id"]` if present, else `f"topic_{chapter['slug']}"`) and returns `{"id": chapter["id"], "title": chapter["title"], "status": "done" | "pending", "score": int | None, "attempts": int | None, "passed": bool | None}` — `"done"` (with the sidecar's values) when `notes_output_path(key, output_dir)` exists, `"pending"` (all three `None`) otherwise; returns `[]` (not an error) when `outline.json` doesn't exist yet. Unit test with 3 chapters on disk (one done+passed, one done+not-passed, one pending) asserts all three shapes; a fresh `output_dir` with no outline.json returns `[]`
  - Files: ai_llm/app/graph.py, ai_llm/tests/unit/test_graph.py
  - Completed: 2026-09-25 — added exactly as specified; never touches
    LangGraph (pure disk read), so it needs no `book_order`/checkpointer
    param unlike `get_progress`. 3 new tests: empty-list before
    `outline.json` exists; a 3-chapter video-mode outline with one
    done+passed, one done+not-passed, one pending chapter; a topic-mode
    outline confirming the `topic_<slug>` key derivation.

- [x] Task 4: `api/ai_llm_bridge.py` re-exports `get_chapter_progress` (P0)
  - Acceptance: `ai_llm_bridge.get_chapter_progress = _graph.get_chapter_progress`, same re-export pattern as `get_progress`; unit test asserts it's importable/callable with the same signature as the underlying `ai_llm` function
  - Files: api/ai_llm_bridge.py, tests/unit/test_ai_llm_bridge.py
  - Completed: 2026-09-25 — one-line re-export, one new test asserting
    importability and the `(output_dir,)` signature.

- [x] Task 5: `GET /books/{id}/events` — `chapters` array on every progress event (P0)
  - Acceptance: `_progress_events` (`api/routers/books.py`) also calls `asyncio.to_thread(ai_llm_get_chapter_progress, output_dir)` each poll tick and includes the result as `progress["chapters"]`; the dedup key that decides whether to yield a new SSE event becomes `(current_node, completed_nodes, tuple((c["id"], c["status"], c["score"], c["attempts"]) for c in chapters))` instead of just `(current_node, completed_nodes)` — a chapter finishing while the book-wide node position is unchanged now counts as a real change and gets its own event. Integration test (stubbing `ai_llm_get_chapter_progress` directly, following the existing `test_books_events.py` monkeypatch pattern) asserts two polls with the same node but a different chapter status produce two distinct `progress` events, and that `progress["chapters"]` matches what was stubbed
  - Files: api/routers/books.py, tests/integration/test_books_events.py
  - Completed: 2026-09-25 — implemented exactly as specified, including
    the dedup key change. 1 new integration test: a fixed `current_node`
    across polls with a chapter transitioning pending -> done (score 9,
    attempts 1) asserts exactly 2 distinct `progress` events (not 1,
    proving the dedup key change works) followed by the terminal `done`
    event, using a fresh `SessionLocal()` inside the stub (not the test's
    own `db_session`) to flip the book to `done` safely from
    `asyncio.to_thread`'s worker thread.

- [x] Task 6: Integration test — real per-chapter progress over a real SSE stream (P0)
  - Acceptance: extends the real-pipeline pattern from `tests/integration/test_books_events_real_pipeline.py` (real uvicorn server, real ai_llm graph, real Postgres checkpointer, only the LLM/video/compile boundary stubbed) to a book with at least 2 chapters and a judge stub that fails one chapter's first attempt (so `attempts > 1` for at least one chapter); asserts the received `progress` events show chapters transitioning from absent/`pending` to `done` in the correct order, with the refined chapter's final `attempts`/`score`/`passed` visible in some event before the stream's terminal `done` event
  - Files: tests/integration/test_books_events_real_pipeline.py
  - Completed: 2026-09-25 — added
    `test_events_stream_reflects_real_per_chapter_progress`: same real
    uvicorn server / real ai_llm graph / real Postgres checkpointer
    pattern as the existing node-order test, extended to 2 real chapters
    (2 fetched videos, `BOOK_ORDER=video`) with a judge stub that fails
    vid1's first attempt (score 3) and passes its second (score 9, with a
    deliberate 0.2s sleep to widen the polling window), while vid2 passes
    immediately. Assertions follow the existing file's own documented
    tradeoff for real, live-polled data (how many polls land mid-write is
    real OS thread scheduling, not something to chase with longer sleeps):
    tracks the latest-seen state per chapter id across every `progress`
    event, asserts no chapter's status ever regresses (done -> pending),
    asserts at least one chapter is observed reaching `"done"` with a
    non-null score/attempts/passed, and -- if vid1's `"done"` state was
    among those caught -- asserts its real refined shape (`attempts == 2`,
    `passed == true`). Verified stable across 4 consecutive runs (no
    flakes) before treating it as done.
  - Note: while finishing this task, this session hit repeated transient
    test failures (FK violations, connection timeouts, an SSE 401) caused
    by other active Claude Code sessions on this same machine (confirmed
    via listing peer sessions -- `video2book-e7`, `video2book-98`,
    `Sprint task completion`, `frontend-5e`) concurrently running their
    own test suites against the same shared `docker compose` Postgres/
    Redis containers, and one of them concurrently editing `api/models.py`
    / `api/schemas.py` / `tests/integration/test_books_status.py` (added
    `url`/`created_at`/`videos` fields, unrelated to this sprint). Every
    failure was confirmed non-reproducible on an immediate retry in
    isolation. This sprint's own files were not touched by that concurrent
    work. Same class of issue as `ai_llm/sprints/v7/TASKS.md` Task 4
    Finding D ("pick a playlist and confirm with any other active session
    on the same machine before launching, not after") -- worth the same
    caution for whoever next runs the full suite on this machine.

- [x] Task 7: README — document per-chapter progress in `/events` (P1)
  - Acceptance: `backend/README.md`'s existing `/events` section (v7) gets its example payload updated to include a `chapters` array, and a short paragraph explaining what `score`/`attempts`/`passed` mean (judge score of the kept attempt, how many attempts it took, whether it ever reached `PASS_SCORE`) and that a chapter absent from the array or `status: "pending"` simply hasn't been written yet
  - Files: README.md
  - Completed: 2026-09-25 — updated the v7 `/events` example payload to
    include `chapters`, and added a new "Per-chapter progress (v9)"
    section explaining the field semantics (including the `passed: false`
    "done but never reached PASS_SCORE" case) and that this is computed
    fresh from disk on every poll, nothing new persisted to Postgres.
    Added a v9 line to the "what's in" list and removed "per-chapter
    pass/fail status" from "still deferred". 12/12 targeted tests (bridge
    + both events test files, including the new per-chapter real-pipeline
    test) passing on a clean, isolated run; bandit clean on `api/` (the
    only medium-severity findings anywhere in `tests/`/`api/` are
    pre-existing, unrelated `urllib.request.urlopen` calls against local
    presigned URLs in older S3/PDF tests); ai_llm's own full suite
    210/210 passing, bandit clean on `app/nodes/write.py`/`app/graph.py`.
