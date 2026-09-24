# Sprint v3 — Tasks

## Status: Complete

- [x] Task 1: Merge topics across the playlist via a new LLM call (P0)
  - Acceptance: given `work/topics/*.json` across 2+ videos where two
    chunks' topic lists both contain a paraphrase of the same underlying
    topic, `run_plan_topics()` writes `plan.json` as a list of `{title,
    needs, level, sources: [{video_id, chunk_index}]}`; unit test with a
    stubbed LLM response containing two paraphrased duplicate topics from
    different videos asserts they collapse into one plan entry whose
    `sources` list includes both video_ids; a real 2+ video playlist with a
    genuinely overlapping topic is picked and recorded in `PRD.md`'s test
    playlist note
  - Files: app/nodes/plan.py, app/prompts/plan_topics.md, tests/unit/test_plan.py
  - Completed: 2026-09-24 — `run_plan_topics()` loads every
    `work/topics/*.json`, sends video/chunk-labeled topic lists only (no
    transcript text, cheap on a 30h playlist) to a new `plan_topics.md`
    prompt via `call_writer`, and writes `plan.json`. Mirrors `topics.py`'s
    proven parse/retry/degrade pattern (Task 11, v1): one retry with a
    stricter suffix on an unparseable response, then degrades to an
    unmerged one-entry-per-topic plan rather than crashing the run. 4 new
    unit tests, fully mocked. Picked the real test playlist (3Blue1Brown
    "Essence of Linear Algebra" chapters 1-3, chosen because chapters 2-3
    both substantively cover basis vectors/linear transformations) and
    recorded it in `PRD.md`. **Could not live-verify the real merge**:
    YouTube's bot-detection ("Sign in to confirm you're not a bot") is
    blocking all yt-dlp calls from this session — confirmed session-wide by
    retrying a previously-working v2 test video, which now also fails.
    Documented in `PRD.md`; real end-to-end verification deferred to Task
    8 once the block clears. 89/89 tests passing (1 skipped, known
    corrupted-PATH shell issue). bandit clean, pip-audit clean (same
    pre-existing ambient CVEs). Eval gate: this task adds a new prompt
    file, so it technically applies — no `EVAL_DATASET_NAME`/runner exists
    in the repo yet (Milestone 5 scope), so there's no baseline to gate
    against; same finding as v1 Tasks 5/6/11, flagged rather than skipped
    silently.

- [x] Task 2: Order merged topics by needs/level with cycle-breaking (P0)
  - Acceptance: `order_topics(merged_topics)` returns a list ordered so no
    topic appears before any topic in its `needs`, ties broken by `level`
    then earliest source appearance; a synthetic 3-topic fixture with a
    circular `needs` reference (A needs B, B needs A) resolves without
    raising, removes one edge, and appends a line to `order_log.txt`
    explaining which edge was dropped and why
  - Files: app/nodes/order.py, tests/unit/test_order.py
  - Completed: 2026-09-24 — `order_topics()` is a pure function (Kahn's
    algorithm): repeatedly places whichever ready topic (no unresolved
    `needs`) has the lowest `(level, earliest_source, title)` key; when no
    topic is ready (a cycle), the lowest-level stuck topic is forced
    through by dropping its remaining `needs` edges, each drop logged as a
    `log_lines` entry — never raises, never silently drops. Unresolvable
    `needs` references (a title not present in the plan) are ignored at
    graph-build time, not treated as a cycle. `run_order_topics(output_dir)`
    wraps it: loads `plan.json`, builds the video-order tiebreak map from
    `videos.json`'s `playlist_index` (v2), writes `ordered_plan.json` +
    appends any cycle-break lines to `order_log.txt`. 6 new unit tests
    (needs-respecting order, level/earliest-source tiebreak, cycle
    breaking, unresolvable-reference handling, both at the pure-function
    and file-writing-wrapper level). 95/95 tests passing (1 skipped, known
    corrupted-PATH shell issue). bandit clean, pip-audit clean (same
    pre-existing ambient CVEs). No prompts/model config touched, eval gate
    doesn't apply.

- [x] Task 3: Topic-mode outline reusing v2's stable-id + skip/locked logic (P0)
  - Acceptance: `run_topic_outline(ordered_topics, output_dir)` writes
    `outline.json`/`outline.md` with `chapter:<topic-slug>` ids (slugified
    from topic title, deduped on collision) in the given order; re-running
    after a hand-edited `skip: true` preserves it, matching v2's
    `run_outline` behavior exactly via a shared preservation helper (not
    reimplemented); unit test covers both new-plan creation and skip
    preservation across a re-plan
  - Files: app/nodes/outline.py, tests/unit/test_outline.py
  - Completed: 2026-09-24 — Extracted `_preserve_flags(existing,
    chapter_id)` out of `run_outline` so both it and the new
    `run_topic_outline()` share the exact same skip/locked-preservation
    logic (not reimplemented). Added `_slugify()`/`_unique_slug()` (dedupes
    on collision with a `-2`, `-3`, ... suffix) for `chapter:<slug>` ids.
    Generalized `_write_outline_md` to print a `detail` field per chapter
    instead of hardcoding `video_id` — `run_outline` sets `detail` to the
    video_id (output text unchanged from v2), `run_topic_outline` sets it
    to `"level N; sources: <video_ids>"`. 3 new unit tests; all 3 existing
    v2 `run_outline` tests still pass unmodified. 98/98 tests passing (1
    skipped, known corrupted-PATH shell issue). bandit clean, pip-audit
    clean (same pre-existing ambient CVEs). No prompts/model config
    touched, eval gate doesn't apply.

- [x] Task 4: Multi-source topic writing (P0)
  - Acceptance: `run_write_topic(topic, output_dir)` reads every chunk file
    referenced in `topic["sources"]` (spanning 2+ videos), writes ONE
    `work/notes/topic_<slug>.md` from a single writer LLM call whose prompt
    includes all source excerpts labeled by video; unit test with 2 source
    videos' chunk text asserts the `call_writer` prompt contains both
    videos' transcript text and the output file is written once, not once
    per source video
  - Files: app/nodes/write.py, app/prompts/write_topic_notes.md, tests/unit/test_write.py
  - Completed: 2026-09-24 — `run_write_topic(topic, output_dir)` takes one
    chapter from Task 3's `run_topic_outline()` output (needs `slug`,
    `title`, `sources`), reads every referenced `work/chunks/<video_id>_
    <chunk>.json`, and makes exactly ONE `call_writer` call whose prompt
    (new `write_topic_notes.md`) includes every source excerpt labeled
    `[Source: <video_id>, chunk <n>]`, instructing the model to synthesize
    one coherent section rather than write "Video 1 says... Video 2
    says...". Deliberately takes an already-outlined chapter (not a raw
    `plan.py`/`order.py` topic) so the notes filename's slug is always
    identical to the chapter id's slug — no duplicate slug-computation
    logic to drift out of sync. Output path:
    `work/notes/topic_<slug>.md` (reuses the existing `notes_output_path`
    helper unchanged — it was already video_id-agnostic). 2 new unit
    tests: multi-source synthesis (asserts both videos' transcript text
    reached the single prompt, file written once) and a missing-source
    `FileNotFoundError`. 100/100 tests passing (1 skipped, known
    corrupted-PATH shell issue). bandit clean, pip-audit clean (same
    pre-existing ambient CVEs). Eval gate: new prompt file, technically
    applies — no `EVAL_DATASET_NAME`/runner exists yet, same finding as
    Task 1, flagged not skipped.

- [x] Task 5: Wire `BOOK_ORDER` into `graph.py` — topic-order graph (P0)
  - Acceptance: `build_graph()`/`build_plan_graph()` branch on
    `load_settings().book_order`: topic mode builds
    fetch→chunk→topics→plan→order→outline→write_topic→render; video mode is
    v2's existing graph, unchanged; unit test forces `BOOK_ORDER=topic` via
    monkeypatched settings and asserts the resulting `chapters/main.tex` has
    one `\input` per merged topic (not per video) for a 2-video fixture with
    an overlapping topic
  - Files: app/graph.py, tests/unit/test_graph.py
  - Completed: 2026-09-24 — Split the old single `build_graph`/
    `build_plan_graph` into `build_video_graph`/`build_video_plan_graph`
    (v2, unchanged logic) and new `build_topic_graph`/
    `build_topic_plan_graph` (fetch→chunk→topics→plan→order→outline→
    write→render); `build_graph`/`build_plan_graph` are now thin
    dispatchers on `load_settings().book_order` (default `"topic"`, per
    root `AGENTS.md`), so `run_book`/`run_plan`/`resume_book` pick the
    right graph with no changes to those three functions. Factored the
    render logic both modes now share into `_render_chapters(chapters,
    output_dir)` — a mode-agnostic list of `{file_key, title, notes_path}`
    — so `render_chapter`/`render_book`/`compile_chapter` don't need to
    know which mode built the chapter list (video mode: `file_key` =
    `video_id`; topic mode: `file_key` = topic slug). **Found and fixed a
    real regression while doing this**: `config.py`'s `BOOK_ORDER` default
    has been `"topic"` since v1 but was never actually read until this
    task's dispatcher — so v2's entire existing test suite (which only
    ever exercised the video graph, since topic mode didn't exist) started
    silently building the wrong graph and failing/erroring. Fixed by
    adding an autouse `monkeypatch.setenv("BOOK_ORDER", "video")` fixture
    to `test_graph.py` and `test_resume.py` (both files are v2/video-order
    specific), pinning them to the mode they actually test rather than
    relying on an implicit default. New `test_graph_topic_order.py`: a
    2-video fixture where both videos' single chunk's topic is merged by a
    stubbed `plan.py` response into one `"Gradient Descent"` topic sourced
    from both videos; asserts `plan.json`/`ordered_plan.json`/
    `work/notes/topic_gradient-descent.md` all exist and
    `chapters/main.tex` contains exactly one `\input{gradient-descent}`
    line (not one per video). 101/101 tests passing (1 skipped, known
    corrupted-PATH shell issue). bandit clean, pip-audit clean (same
    pre-existing ambient CVEs). No prompts/model config touched this task
    itself, eval gate doesn't apply.

- [x] Task 6: `--plan-only` and `--resume` work in topic mode (P0)
  - Acceptance: `--plan-only` in topic mode stops after
    `outline.json`/`outline.md` (topic chapters) without calling render,
    same guarantee as v2 Task 5; a crash mid `write_topic` (topic 2 of 2)
    followed by `--resume` finishes without re-invoking plan/order/outline
    or topic 1's write LLM call — mirrors v2 Task 8's playlist crash test,
    now for the topic pipeline
  - Files: app/graph.py, app/cli.py, tests/unit/test_cli.py, tests/unit/test_resume.py
  - Completed: 2026-09-24 — No `graph.py`/`cli.py` code changes needed:
    Task 5's dispatcher already makes `run_plan()`/`run_book()`/
    `resume_book()` pick the right graph, and `cli.py` calls those three
    functions generically with no `BOOK_ORDER` awareness of its own — the
    same LangGraph node-level checkpointing already validated in v2
    (Task 8/9) applies unchanged to the topic-mode `plan`/`order`/`outline`/
    `write`/`render` nodes with zero extra code. Verified both guarantees
    with new tests instead of assuming: `test_run_plan_topic_order_stops_
    before_render` (test_graph_topic_order.py) — asserts `render`/
    `compile_chapter` are never called and no `work/notes/` directory
    exists after `run_plan()` in topic mode.
    `test_resume_continues_topic_order_after_crash_without_redoing_
    completed_topic` (new tests/unit/test_resume_topic_order.py) — 2
    unmerged topics from 2 videos, topic one's write succeeds, topic two's
    write raises on its first attempt; asserts the plan LLM call count
    stays at 1 and topic one's write isn't retried (2→3 calls, not 2→4)
    across `resume_book()`, which finishes `book.pdf` with both chapters
    `\input`'d. 103/103 tests passing (1 skipped, known corrupted-PATH
    shell issue). bandit clean, pip-audit clean (same pre-existing ambient
    CVEs). No prompts/model config touched, eval gate doesn't apply.

- [x] Task 7: `BOOK_ORDER=video` regression guard (P1)
  - Acceptance: a unit test with `BOOK_ORDER=video` runs the full v2 graph
    and asserts `plan.json`/`order_log.txt`/topic-mode outline chapters are
    never created — confirms v3's new nodes are fully inert unless
    `BOOK_ORDER=topic`, so v2 behavior has zero regression
  - Files: tests/unit/test_graph.py
  - Completed: 2026-09-24 — `test_run_book_video_order_never_creates_topic_
    mode_artifacts`: runs a 2-video `run_book()` under the file's existing
    `BOOK_ORDER=video` autouse fixture, asserts `plan.json`/
    `ordered_plan.json`/`order_log.txt` are never created and every
    `outline.json` chapter has the video-mode shape (`id ==
    "chapter:<video_id>"`, no `slug`/`sources` fields). Also manually
    verified real latexmk compiles cleanly with hyphenated topic-slug `.tex`
    filenames and `\input{gradient-descent}`-style commands (a new code
    path from Task 5) — no LaTeX issue with hyphens in `\input` targets.
    104 tests passing via the normal corrupted-PATH shell (1 skipped, known
    issue), 105/105 with a clean PATH (0 skipped). bandit clean, pip-audit
    clean (same pre-existing ambient CVEs). No prompts/model config
    touched, eval gate doesn't apply.

- [x] Task 8: End-to-end verification with a real overlapping-topic playlist (P1)
  - Acceptance: `python -m app.cli "<picked playlist>"` with
    `BOOK_ORDER=topic` produces a `book.pdf` where a topic covered by 2+ of
    the playlist's videos appears as exactly one chapter (not duplicated),
    and `outline.md` shows a coherent needs/level-based order, not upload
    order
  - Files: sprints/v3/PRD.md
  - Completed: 2026-09-24 — Ran the full topic-order pipeline for real
    (real captions/chunks, real NVIDIA→Gemini fallback LLM calls — NVIDIA
    failed and Gemini's `google-genai` AFC path handled it, confirming the
    provider fallback chain works live too — real latexmk) against the
    picked playlist's first 3 videos. Result strongly validates the whole
    v3 design: 5 merged chapters, correctly ordered by level (1→4) with
    prerequisites first — "Vectors: geometric interpretation and coordinate
    representation" and "Vector operations..." and "Span, linear
    independence, and basis" each correctly cite all 3 source videos
    (`fNk_zzaMoSs, k7RM-ot2NWY, kYB8IZa5AuE`), and "Matrices as linear
    transformations" correctly cites 2 of the 3 — a genuine cross-video
    merge, not duplicated per-video sections. Real `book.pdf` produced
    (44KB, valid `%PDF` header). Also ran this while YouTube's bot-
    detection block (noted in Task 1) had cleared on its own, confirming
    it was transient. No lingering scratch output left on disk.
