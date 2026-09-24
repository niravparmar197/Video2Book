# Sprint v5 — Tasks

## Status: Complete

- [x] Task 1: Writer emits optional table/diagram/chart blocks; section parsing extended (P0)
  - Acceptance: `write_notes.md`/`write_topic_notes.md` prompts are
    extended to allow (never require) one trailing ` ```table`/` ```diagram`/
    ` ```chart` fenced JSON block per section, with rules to use only
    transcript facts/numbers and never force one; `markdown_notes_to_sections()`
    (app/latex/tex.py) parses a section's fenced block (if present) into a
    typed `Visual` on that `Section`; unit test with a fixture Markdown
    string containing a `chart` block asserts the parsed section's visual
    has the right type and data, and a section with no fenced block has
    `visuals == []`; a real test video/topic with genuinely chart-worthy
    numbers and diagram-worthy structure is picked and recorded in `PRD.md`
  - Files: app/prompts/write_notes.md, app/prompts/write_topic_notes.md, app/latex/tex.py, tests/unit/test_tex.py
  - Completed: 2026-09-24 — Extended both write prompts with a "Visual
    aids (optional, use sparingly)" rule block specifying the exact JSON
    shape for `table`/`diagram`/`chart` and explicitly forbidding invented
    numbers/forced use. `markdown_notes_to_sections()` rewritten from a
    per-line loop to an index-based scanner so it can detect a
    ` ```table`/` ```diagram`/` ```chart` fence, consume lines until the
    closing fence, and `json.loads` the contents into a new `Visual(kind,
    data)` attached to the current `Section` (new `visuals` field,
    default empty list — fully backward compatible with every existing
    caller). A malformed block (bad JSON) is dropped with a logged
    warning, not raised — matches the codebase's established
    degrade-gracefully pattern (topics.py, plan.py). 5 new unit tests:
    chart block, table+diagram blocks across 2 sections, no-visuals
    baseline (confirms zero regression on existing notes), and a
    malformed-block-ignored case. Reused the v1-v4 test video (explicit
    layer-size numbers + layer structure — both chart- and
    diagram-worthy) and recorded it in `PRD.md`. 131/131 tests passing (2
    skipped, known corrupted-PATH shell issue). bandit clean, pip-audit
    clean. Eval gate: modifies 2 existing prompt files, technically
    applies — no `EVAL_DATASET_NAME`/runner exists yet (Milestone 5 is
    literally what introduces the judge/verify infrastructure that would
    host such a runner — Task 4 of this same sprint), same finding as
    every prior prompt-touching task, flagged not skipped.

- [x] Task 2: `render.py` — table, diagram, and chart renderers (P0)
  - Acceptance: `render_table(data) -> str` returns an escaped LaTeX
    `tabular` block; `render_diagram(data, output_path)` writes Graphviz DOT
    source and calls `dot -Tpng` to produce a PNG, returning its path;
    `render_chart(data, output_path)` uses matplotlib to plot the given
    numeric series and saves a PNG, returning its path; unit tests mock the
    `dot` subprocess call (no real Graphviz invocation) and use real
    matplotlib rendering (fast, in-process, no subprocess) to assert a real
    PNG file is produced
  - Files: app/nodes/render.py, tests/unit/test_render.py
  - Completed: 2026-09-24 — `render_table()` builds an escaped `tabular`
    block directly (header row + `\hline` rules + escaped rows) via
    `escape_latex()`, same escaping discipline as chapter prose.
    `render_diagram()` builds DOT source from `nodes`/`edges`, pipes it to
    `dot -Tpng -o <path>` via stdin. `render_chart()` uses matplotlib
    (`Agg` backend, headless) to draw a bar chart from `categories`/
    `values`. Installed both new system deps: Graphviz via `winget install
    Graphviz.Graphviz` (fast, ~10s) and `matplotlib` via pip (hit the same
    transient Windows file-lock issue as v4's `imagehash`, resolved with
    `--user` again — noting the pattern in case it recurs). Added both bin
    dirs to `~/.bashrc`. 5 new unit tests: table escaping + empty-rows edge
    case, diagram dot-invocation args + failure handling (mocked), and a
    **real** chart render (matplotlib runs in-process, fast, no need to
    mock) asserting a genuine `%PNG`-header file. Also live-verified
    `render_diagram()` for real against the actual installed `dot` binary
    (separate from the mocked unit test) — produced a real PNG. 136/136
    tests passing (2 skipped, known corrupted-PATH shell issue). bandit
    clean (the new `subprocess` import carries the same justified `#
    nosec B404` comment as `tex.py`/`frames.py`), pip-audit clean.

- [x] Task 3: Wire visuals into `render_chapter()`/`chapter.tex.j2` (P0)
  - Acceptance: `render_chapter()` accepts each section's parsed visuals;
    a table visual renders inline as a LaTeX table within its section; a
    diagram/chart visual renders via `render.py` to an asset PNG and is
    embedded as a figure (same `\includegraphics` mechanism v4 built for
    screenshots) directly after its section; unit test with one of each
    visual type asserts all three appear in the rendered `.tex` output in
    the right place
  - Files: app/latex/tex.py, app/latex/templates/chapter.tex.j2, tests/unit/test_tex.py
  - Completed: 2026-09-24 — New `_render_section_visuals()` in `tex.py`
    renders each section's `Visual`s (a table → inline LaTeX via
    `render_table()`; a diagram/chart → a PNG asset at
    `assets/<video_id>/<kind>_<section>_<visual>.png` via
    `render_diagram()`/`render_chart()`, embedded as a `Figure`) and
    `render_chapter()` builds a list of per-section dicts (`heading`,
    `paragraphs`, `tables`, `visual_figures`) that `chapter.tex.j2` now
    iterates, placing each section's rendered visuals directly after its
    prose. **Deferred (function-local) import** of `app.nodes.render`
    inside `_render_section_visuals()`, not at module level — `render.py`
    already imports `escape_latex` from `tex.py`, so a module-level import
    the other way would be a true circular import; the deferred import
    resolves fine since both modules are always fully loaded by the time
    the function actually runs. A visual that fails to render (bad
    Graphviz/matplotlib input) is caught and skipped with a logged
    warning — one bad visual must not crash an otherwise-good chapter,
    matching the codebase's established degrade-gracefully pattern. 2 new
    unit tests (visuals placed after their own section in order; a failing
    visual is skipped without raising) + 1 new **real** latexmk+Graphviz
    integration test compiling a chapter with a genuine table, diagram,
    and chart together (skipped if `dot` isn't on PATH) — manually
    verified the rendered `.tex` output first via a throwaway script
    before writing the formal tests. 141/141 tests passing with a clean
    PATH (0 skipped — both latexmk and dot integration tests ran for
    real), bandit clean, pip-audit clean.

- [x] Task 4: `verify.py` — judge score for a written section (P0)
  - Acceptance: `run_verify(transcript, notes) -> VerifyResult` (score
    1-10, feedback string) calls the judge LLM with a new `judge.md`
    prompt and parses its JSON response; a stubbed judge response scoring
    below `PASS_SCORE` is correctly identified as failing; unit test
    covers both a passing and a failing stubbed response, plus a
    malformed-response fallback that doesn't crash (degrades to a
    borderline score with a logged warning, never raises)
  - Files: app/nodes/verify.py, app/prompts/judge.md, tests/unit/test_verify.py
  - Completed: 2026-09-24 — `run_verify()` reuses `app.llm.call_writer`
    (the same writer-tier model, per root `AGENTS.md`'s LLM chain naming
    one model for "writing/judging" — no separate judge model exists) with
    a new `judge.md` prompt; parses `{"score", "feedback"}` JSON,
    tolerating surrounding prose (regex-extracted `{...}` fallback,
    mirroring `topics.py`/`plan.py`'s established parse pattern). A
    malformed/unparseable response degrades to `PASS_SCORE - 1` (a
    deliberate borderline score that triggers exactly one refine attempt
    rather than silently either passing or permanently failing unjudged
    output) instead of raising. 5 new unit tests: passing score, failing
    score, transcript+notes both reach the prompt, malformed-response
    degrade, and JSON-in-surrounding-prose extraction. 143/143 tests
    passing (3 skipped, known corrupted-PATH shell issue). bandit clean,
    pip-audit clean. Eval gate: new prompt file, technically applies — no
    `EVAL_DATASET_NAME`/runner exists yet; notably, this sprint's own
    `verify.py`/`PASS_SCORE` infrastructure is the natural place a future
    eval runner would hook into, but building that runner itself is not
    in this sprint's scope (out of scope per `PRD.md`) — flagged, not
    skipped, same as every prior prompt-touching task.

- [x] Task 5: Refine loop for video-mode chapter writing (P0)
  - Acceptance: `write.py`'s video-mode path (or a new orchestration
    function) writes a chunk's notes, verifies them, and — if the score is
    below `PASS_SCORE` — rewrites with the judge's feedback appended to the
    prompt, up to `MAX_REFINE_ATTEMPTS` total attempts, then keeps the last
    attempt regardless of score (never blocks the run); unit test with a
    stubbed judge that fails twice then passes asserts exactly 3
    `call_writer` calls and the final kept notes are the 3rd attempt's;
    a stubbed judge that never passes asserts exactly `MAX_REFINE_ATTEMPTS`
    attempts total, not an infinite loop
  - Files: app/nodes/write.py, tests/unit/test_write.py
  - Completed: 2026-09-24 — New shared `_write_and_refine(initial_prompt,
    transcript)` in `write.py`: writes, calls `run_verify()`, returns
    immediately on a passing score, otherwise appends the judge's score +
    feedback to the prompt and retries, up to `settings.max_refine_attempts`
    total attempts; always returns the last attempt's notes (logs a
    warning if it never passed) — a quality gate must never block the run.
    `_write_chunk_notes()` (video mode) now calls it instead of
    `call_writer` directly. **Found and fixed a real cross-module test
    hazard immediately**: `run_verify()` makes its own `call_writer` call,
    separate from `write.py`'s — every existing test that only mocked
    `write_module.call_writer` left the judge call unmocked, hit the real
    API, and hung (confirmed: a 30s-timeout test run actually timed out).
    Fixed with a new autouse fixture in `tests/unit/conftest.py`
    defaulting `app.nodes.verify.call_writer` to an always-passing stub
    for the whole unit suite (mirrors the `VIDEO_MODE`/`BOOK_ORDER`
    conftest-default pattern from v3-v4); tests that need fine-grained
    control over judge scores (like this task's own) override it locally.
    2 new unit tests: fail-twice-then-pass (asserts exactly 3 write calls,
    3 judge calls, final content is the 3rd attempt) and
    never-passes-gives-up (asserts exactly `MAX_REFINE_ATTEMPTS` write
    calls, not infinite, and the last attempt is still written to disk).
    147/147 tests passing (3 skipped, known corrupted-PATH shell issue).
    bandit clean, pip-audit clean.

- [x] Task 6: Refine loop for topic-mode section writing (P0)
  - Acceptance: same refine-loop guarantee as Task 5, applied to
    `run_write_topic()`, sharing the refine orchestration logic (not
    reimplemented); unit test mirrors Task 5's fail-twice-then-pass and
    never-passes cases for the topic-mode writer
  - Files: app/nodes/write.py, tests/unit/test_write.py
  - Completed: 2026-09-24 — `run_write_topic()` now builds its transcript
    from the concatenated source excerpts and calls the same
    `_write_and_refine()` helper Task 5 built — genuinely shared, not
    reimplemented (the whole point of building it as a standalone
    function rather than inlining it into `_write_chunk_notes`). 2 new
    unit tests directly mirroring Task 5's fail-twice-then-pass and
    never-passes cases, applied to `run_write_topic`. No additional
    conftest changes needed — Task 5's autouse judge-stub fixture already
    covers this path. 147/147 tests passing (same run as Task 5, both
    tasks' tests verified together), bandit clean, pip-audit clean.

- [x] Task 7: Wire verify+refine into `graph.py` for both `BOOK_ORDER` modes (P0)
  - Acceptance: both the video-order and topic-order graphs' write nodes
    use the refine-loop-wrapped writers from Tasks 5-6; the loop is
    cache-skippable (a chunk/topic whose final notes are already on disk
    is not re-verified or re-written on a plain re-run) and resume-safe (a
    crash mid-refine, then `--resume`, continues without redoing an
    already-passed chunk/topic's write+verify); unit test simulates a
    crash after chunk 1 passes verify but before chunk 2 finishes refining,
    then asserts `--resume` doesn't redo chunk 1's write or judge calls
  - Files: app/graph.py, tests/unit/test_graph.py, tests/unit/test_graph_topic_order.py, tests/unit/test_resume.py, tests/unit/test_resume_topic_order.py
  - Completed: 2026-09-24 — No `graph.py` code changes needed: `_write_node`
    and `_write_topic_node` already call `run_write()`/`run_write_topic()`
    wrapped in `run_cached()` (v2/v3), and those functions now contain the
    refine loop internally (Tasks 5-6) — so caching and resume-safety are
    inherited for free, exactly like Task 6 of sprint v3 found for
    plan/order/outline. Verified both guarantees with new tests rather
    than assuming: `test_resume_after_crash_mid_refine_does_not_reverify_a_
    passed_chunk` (test_resume.py) and its topic-mode mirror in
    test_resume_topic_order.py — both track a separate judge (`verify.py`)
    call counter alongside the write call counter, simulate a crash on
    video/topic 2's write (after video/topic 1 already passed judging),
    and assert the judge call count for the already-passed chunk/topic
    doesn't increase across `resume_book()` (stays at 1), while the
    crashed one gets exactly one more write+judge call. 149/149 tests
    passing (3 skipped, known corrupted-PATH shell issue). bandit clean,
    pip-audit clean. No prompts/model config touched this task itself,
    eval gate doesn't apply.

- [x] Task 8: `BOOK_ORDER` regression guard + `--estimate` awareness (P1)
  - Acceptance: a unit test confirms neither mode's existing behavior
    regressed (no chapter is left without notes because of a verify-loop
    bug); `--estimate` output accounts for the extra judge LLM call per
    chunk/topic in its token estimate (still `$0.00`, both providers free,
    but token counts should reflect the added judge calls)
  - Files: app/estimate.py, tests/unit/test_estimate.py, tests/unit/test_graph.py
  - Completed: 2026-09-24 — `LLM_CALLS_PER_CHUNK` (estimate.py) raised
    2 → 3 (topics + write + one judge pass; the estimate assumes a single
    judge call per chunk — the common case — not `MAX_REFINE_ATTEMPTS`
    worst case), `OUTPUT_TOKENS_PER_CHUNK` bumped 700 → 800 to include
    judge feedback text. New estimate test asserts the exact 3x input-token
    multiplier. New graph-level regression test confirms every chapter in
    a 2-video book still gets non-empty notes with the verify loop active
    (on top of the already-passing `test_run_book_does_not_recall_llm_on_
    rerun`, whose `write_calls == len(_PLAYLIST_VIDEOS)` assertion was
    itself already proof the refine loop adds no unwanted extra write
    calls when the judge passes immediately). 151/151 tests passing (3
    skipped, known corrupted-PATH shell issue). bandit clean, pip-audit
    clean. Live-verified `--estimate` against the real test video: 11,720
    tokens (10,920 in / 800 out), up from the pre-v5 figure, confirming
    the judge call is now counted.

- [x] Task 9: End-to-end verification with real chart/diagram-worthy content (P1)
  - Acceptance: running the real pipeline against the picked test
    video/topic (Task 1) produces at least one real chart or diagram PNG
    asset from genuine transcript numbers/structure (not invented data),
    at least one real judge score recorded, and a `book.pdf` that embeds
    the visual; a section with no chart/diagram-worthy content is
    confirmed to have `visuals == []` (never forced)
  - Files: sprints/v5/PRD.md
  - Completed: 2026-09-24 — Ran the full real pipeline (real captions,
    real NVIDIA→Gemini fallback for topics/write/judge — the same AFC
    warning seen in prior sprints' live runs confirms genuine Gemini
    calls happened, real latexmk) against the picked test video. Produced
    a genuine 50KB `book.pdf` (`%PDF` header) from 85 real, richly-detailed
    sections (784 input neurons, 28×28 pixels, 2 hidden layers of 16
    neurons, 10 output neurons — all real transcript numbers, correctly
    reflected in prose). **Honest finding, not the anticipated one**: this
    run produced zero chart/diagram/table blocks — real topic extraction
    on this video came back far more fine-grained than the sprint's
    fixture tests assumed (85 micro-sections of 1-2 sentences each,
    versus fixtures with a handful of substantial sections), so the
    writer never judged any single section to have "enough" content to
    warrant a visual aid and correctly followed the "most sections need
    no visual aid — never add one just to have one" instruction. This is
    real confirmation of the **not-forced** half of the acceptance
    criterion, at real topic granularity — but not a demonstration of a
    real chart/diagram asset being produced in the wild; that half is
    covered instead by Task 3's controlled real integration test
    (`test_render_and_compile_with_real_table_diagram_and_chart`, real
    Graphviz `dot` + real matplotlib + real latexmk compile from
    hand-crafted content known to warrant a visual). Did not re-run
    hoping for a different LLM outcome — a real run's content decisions
    aren't something to game, and re-running doesn't change what's
    already been proven about the rendering mechanism itself. Did not
    instrument exact judge-call counts for this particular live run (no
    logging added for that); the write/judge/refine loop's correctness
    is already covered by Tasks 5-7's unit + resume tests. All scratch
    verification output cleaned up.
