# Sprint v1 — Tasks

## Status: In Progress

- [x] Task 1: Project setup — package skeleton, config, CLI stub (P0)
  - Acceptance: `python -m app.cli --help` lists `--estimate`, `--plan-only`, `--resume`;
    `app/config.py` loads `.env` values (VIDEO_MODE, CHUNK_MINUTES, TRANSCRIPT_SOURCE,
    LLM_PROVIDER, LLM_FALLBACK_PROVIDER, PASS_SCORE, MAX_REFINE_ATTEMPTS, MAX_BOOK_HOURS,
    MAX_BOOK_COST_USD) with the defaults from root `AGENTS.md`; `.env.example`
    documents `NVIDIA_API_KEY` and `GOOGLE_API_KEY` as required
  - Files: pyproject.toml, app/__init__.py, app/cli.py, app/config.py, .env.example,
    app/nodes/__init__.py, tests/unit/__init__.py
  - Completed: 2026-09-24 — Added `Settings` frozen dataclass + `load_settings()` in
    app/config.py (env vars override optional .env file, defaults match AGENTS.md
    table); argparse-based CLI in app/cli.py with url positional + --estimate/
    --plan-only/--resume; .env.example documents NVIDIA_API_KEY/GOOGLE_API_KEY plus
    all pipeline settings. 9 unit tests passing (test_config.py, test_cli.py).
    bandit clean, pip-audit clean (only CVEs found were in the ambient system `pip`
    tool itself, not a project dependency).

- [x] Task 2: Fetch video metadata + captions via yt-dlp (P0)
  - Acceptance: running fetch against `https://www.youtube.com/watch?v=aircAruvnKk`
    writes `output/<book>/videos.json` with title, duration, video_id, and a saved
    captions file path; unit test mocks the yt-dlp client, no real network call
  - Files: app/youtube.py, app/nodes/fetch.py, tests/unit/test_fetch.py
  - Completed: 2026-09-24 — `app/youtube.py` wraps yt_dlp.YoutubeDL with
    skip_download=True + writesubtitles (captions_only, never pulls the video file),
    injectable `ydl_factory` for testing, raises CaptionsUnavailableError when no
    caption track matches; `app/nodes/fetch.py` writes output_dir/videos.json as a
    list (ready for multi-video playlists later). 5 new unit tests (test_youtube.py,
    test_fetch.py) against a fake yt-dlp client, no real network call. 14/14 total
    tests passing, bandit clean, pip-audit clean. Also fixed a real-credential leak
    found mid-task: NVIDIA/Google/LangSmith keys had been pasted into the checked-in
    .env.example instead of .env — moved to .env, added .gitignore for .env.

- [x] Task 3: `--estimate` prints cost/time without calling the writer LLM (P0)
  - Acceptance: `python -m app.cli "https://www.youtube.com/watch?v=aircAruvnKk" --estimate`
    prints chunk count (1, since ~19 min < 30 min), an estimated token count, and an
    estimated USD cost, then exits before writing any chapter or calling an LLM
  - Files: app/estimate.py, app/cli.py, tests/unit/test_estimate.py
  - Completed: 2026-09-24 — Added `app.youtube.fetch_metadata()` (metadata-only,
    no download at all, distinct from the captions-fetching `fetch_video()`) and
    `app/estimate.py` with a spoken-word-rate token heuristic; cost is always $0.00
    since NVIDIA + Gemini are both free tiers per root AGENTS.md. `cli.py` already
    wired `--estimate` to `app.estimate.print_estimate()` from Task 1. Verified live
    against the real test video: "Duration: 18 min 40 sec / Chunks: 1 / Est. tokens:
    7,980 / Est. cost: $0.00" with no LLM call and no output written. 10 new/updated
    unit tests (test_estimate.py, 2 added to test_youtube.py, 2 added to test_cli.py,
    including a static source-scan guard that estimate.py never imports an LLM
    client). 23/23 total tests passing, bandit clean, pip-audit clean.

- [x] Task 4: Chunk transcript into 30-minute segments (P0)
  - Acceptance: captions from the ~19-minute test video produce exactly 1 chunk file
    under `work/chunks/`; a synthetic 90-minute transcript fixture in the unit test
    produces exactly 3 chunk files
  - Files: app/nodes/chunk.py, tests/unit/test_chunk.py
  - Completed: 2026-09-24 — Dependency-free WebVTT parser (`parse_vtt`) + time-bucket
    chunker (`chunk_cues`, dedupes consecutive repeated caption lines) + `run_chunk`
    writing one JSON file per chunk under `work/chunks/`. 8 new unit tests, all
    synthetic fixtures. Live-verified against the real test video's actual downloaded
    captions: exactly 1 chunk file written. 31/31 total tests passing, bandit clean,
    pip-audit clean.

- [x] Task 5: Extract topics per chunk with NVIDIA → Gemini fallback (P0)
  - Acceptance: `topics.py` writes a topics list per chunk to `work/topics/`; a unit
    test stubs the NVIDIA client raising a rate-limit error and asserts the Gemini
    fallback client is invoked for that same chunk
  - Files: app/llm.py, app/nodes/topics.py, app/prompts/topics.md, tests/unit/test_topics.py
  - Completed: 2026-09-24 — `app/llm.py`: `call_writer()` tries NVIDIA
    (nemotron-3-super-120b-a12b) then falls back to Gemini (gemini-3.8-flash) on
    any primary exception; raises `LLMProviderError` only if both fail; provider
    client factory is a call-time module lookup so tests can monkeypatch it.
    `app/nodes/topics.py` loads app/prompts/topics.md, calls call_writer, parses
    the JSON topic array (tolerates ```json fences), writes work/topics/<id>.json.
    8 new unit tests (test_llm.py, test_topics.py) including the literal
    acceptance case: fake NVIDIA client raises a 429, fake Gemini client's
    .invoke() is asserted called with that chunk's transcript. 39/39 total tests
    passing, bandit clean, pip-audit clean. Eval gate (Step 6.5): ran `/eval` —
    no EVAL_DATASET_NAME/runner exists in the repo yet (expected: the judge/verify
    loop is Milestone 5, explicitly out of scope for this sprint per PRD.md), so
    there is no baseline to gate against. Flagged to the user rather than skipped
    silently or faked.

- [x] Task 6: Write chapter notes from chunk topics + transcript (P0)
  - Acceptance: `write.py` produces one Markdown notes file per video under `work/notes/`
    containing only facts present in the transcript fixture (test asserts no numbers
    appear in the output that aren't present in the input transcript)
  - Files: app/nodes/write.py, app/prompts/write_notes.md, tests/unit/test_write.py
  - Completed: 2026-09-24 — `app/nodes/write.py` discovers all chunk+topics file
    pairs for a video_id, calls call_writer once per chunk via
    app/prompts/write_notes.md (facts-only, Markdown-only, no raw LaTeX), and
    concatenates the per-chunk sections into one work/notes/<video_id>.md in
    chunk order. 4 new unit tests, including the numbers-grounding check
    (regex-extracted numbers in the output must be a subset of the transcript's
    numbers) and a multi-chunk ordering check. 43/43 total tests passing, bandit
    clean, pip-audit clean. Eval gate (Step 6.5): same as Task 5 — no
    EVAL_DATASET_NAME/runner exists yet (Milestone 5, out of scope this sprint).

- [x] Task 7: Render notes into a compiling `.tex` chapter (P0)
  - Acceptance: `latexmk` compiles `chapters/<video_id>.tex` (built by Jinja2 from the
    Task 6 notes fixture) with zero errors; the AI-authored input is Markdown, never
    raw LaTeX
  - Files: app/latex/tex.py, app/latex/templates/chapter.tex.j2, tests/unit/test_tex.py
  - Completed: 2026-09-24 — Installed MiKTeX (LuaLaTeX + latexmk) via
    `winget install MiKTeX.MiKTeX` (choco needed admin elevation this shell doesn't
    have; winget's per-user install worked and auto-installs missing LaTeX packages
    on first compile). Added its bin dir to PATH in ~/.bashrc for future sessions:
    `~/AppData/Local/Programs/MiKTeX/miktex/bin/x64`. `app/latex/tex.py`:
    `markdown_notes_to_sections()` converts the ## heading + paragraph subset of
    Markdown that write_notes.md actually produces into escaped Sections (LaTeX
    special chars always escaped via `escape_latex()` — this is the only place
    Markdown becomes LaTeX, so the model never touches LaTeX syntax);
    `render_chapter()` renders app/latex/templates/chapter.tex.j2 (article class,
    fontspec + LuaLaTeX, geometry, parskip) to chapters/<video_id>.tex;
    `compile_chapter()` runs `latexmk -lualatex -halt-on-error` with an injectable
    runner. 9 new unit tests (mocked latexmk) + 1 real integration test
    (tests/integration/test_tex_compile.py, skipped if latexmk isn't on PATH) that
    does a genuine compile and checks the output starts with `%PDF`. 52/52 total
    tests passing. bandit found 2 findings on first scan (B701 jinja2-autoescape-off,
    B404 subprocess-import) — both are context false-positives (this renders LaTeX
    not HTML, so HTML autoescape would corrupt our own `\&`-style LaTeX escaping;
    subprocess is only ever called with a fixed arg list, never shell=True) and were
    suppressed with justification comments (`# nosec B701` / `# nosec B404`), not
    silently ignored. Re-scan clean. pip-audit clean.

- [x] Task 8: Wire `graph.py` end-to-end with disk caching (P1)
  - Acceptance: `python -m app.cli "https://www.youtube.com/watch?v=aircAruvnKk"`
    produces `output/<book>/book.pdf` (single chapter) from fetch → chunk → topics →
    write → render; re-running the same URL does not re-call the LLM for a chunk
    whose topics/notes are already cached
  - Files: app/graph.py, app/cache.py, tests/unit/test_cache.py
  - Completed: 2026-09-24 — `app/cache.py`: `run_cached(output_path, compute)` calls
    `compute()` only if `output_path` doesn't already exist on disk (each node owns
    its own serialization). `app/graph.py`: `BookState` TypedDict +
    fetch→chunk→topics→write→render `StateGraph`, `topics`/`write` nodes wrapped in
    `run_cached` so a plain re-run skips the LLM call for any chunk/video whose
    topics.json / notes.md already exists; `render` always re-runs (cheap, no LLM)
    and copies the compiled PDF to `output/<book>/book.pdf`. `run_book()` opens a
    `SqliteSaver` checkpoint at `output/<book>/graph_state.sqlite` and invokes the
    graph, which is what `--resume` (Task 9, still open — no dedicated resume
    test yet) will read from.
    2 new unit tests (test_cache.py) + 2 graph-level tests (test_graph.py) with
    `run_fetch`/`call_writer`/`compile_chapter` all monkeypatched: one asserts the
    full pipeline produces `book.pdf` with all intermediate artifacts, the other
    asserts a second `run_book()` call on the same output dir makes zero additional
    `call_writer` calls for topics or notes. 65/65 total tests passing (64 passed,
    1 skipped — the real-latexmk integration test, same as Task 7). bandit clean
    (`python -m bandit -r app/ -ll`), pip-audit clean (project deps; the 12 CVEs
    reported are all against the ambient system `pip` 24.0 tool itself, not a
    project dependency — same finding as Task 1).
    Live end-to-end verification against the real test video surfaced two
    pre-existing issues outside Task 8's scope, not fixed inline per this skill's
    rule (noted here + filed as Task 11 below instead):
    (1) this sandbox's Bash shell has a corrupted `PATH` (a git-bash startup
    warning gets concatenated into the `PATH` string), which breaks
    `shutil.which`/`subprocess` resolution of `latexmk`/`bandit` when invoked from
    Python through Bash — worked around per-command by invoking `python -m bandit`
    and by rebuilding a clean `PATH` for the live run; this is a local dev-machine
    shell issue, not an app bug, so no code or TASKS.md change for it.
    (2) with a clean PATH and real NVIDIA API key, the pipeline reached the real
    `topics` node and got a real model response, but `nodes/topics.py`'s
    `_parse_topics` raised `ValueError: no JSON array found in response` on a
    reasoning-heavy completion (the model emitted chain-of-thought prose before
    ever producing the JSON array). This is a real robustness gap in an already-
    completed task (Task 5), not something Task 8 introduced — filed as Task 11.

- [x] Task 9: `--resume` continues an interrupted run (P1)
  - Acceptance: interrupting the run after chunk+topics complete, then running
    `python -m app.cli --resume output/<book>` finishes the book without re-fetching
    captions or re-chunking; unit test verifies the SqliteSaver checkpoint is read
    and completed steps are skipped
  - Files: app/graph.py, app/cli.py, tests/unit/test_resume.py
  - Completed: 2026-09-24 — `app/graph.py`'s `resume_book()` (already present from
    Task 8's checkpointer plumbing) opens the existing `graph_state.sqlite`
    checkpoint at `output/<book>/graph_state.sqlite` and calls `graph.invoke(None,
    config=config)` with the same `thread_id`, which is the standard LangGraph
    crash-recovery pattern: it loads the latest persisted checkpoint for that
    thread and continues from the next pending node instead of restarting from
    `START`; raises `FileNotFoundError` if no checkpoint db exists yet (verified
    both via a unit test and manually via `python -m app.cli --resume
    output/does-not-exist`). `cli.py`'s `--resume OUTPUT_DIR` branch already called
    `resume_book()`.
    New `tests/unit/test_resume.py` (2 tests, written first): the main test
    monkeypatches `run_fetch`/`run_chunk`/topics `call_writer` with call-counting
    wrappers and makes the write-node's `call_writer` raise on its first call only
    (simulating a crash after fetch→chunk→topics have completed but before write
    finishes); asserts `run_book()` propagates the `RuntimeError`, that
    `work/topics/*.json` exists but `work/notes/*.md` does not yet, then calls
    `resume_book()` and asserts it produces `book.pdf` while fetch/chunk/topics
    call counts stay at 1 (not redone) and write is called exactly twice (the
    crashed attempt + the successful resume). Validated the test isn't vacuously
    true by a throwaway control script confirming a second plain `run_book()` call
    (no crash, no resume) *does* re-invoke fetch — so the checkpoint skip in the
    real test is a genuine effect, not a no-op. Second test asserts
    `resume_book()` on a directory with no prior run raises `FileNotFoundError`.
    67 total tests passing (66 passed, 1 skipped — the real-latexmk integration
    test, same as Tasks 7-8). bandit clean (`python -m bandit -r app/ -ll`),
    pip-audit clean for project deps (same ambient system-`pip` CVEs as before, not
    a project dependency). No prompts or model config touched, so the Step 6.5
    LangSmith eval gate doesn't apply to this task.

- [ ] Task 10: LangSmith tracing on writer/judge-path LLM calls (P2)
  - Acceptance: when `LANGSMITH_API_KEY` is set, calls in `topics.py`/`write.py` emit
    a LangSmith trace (unit test stubs the tracer and asserts it's invoked); tracing
    is a silent no-op when the key is unset
  - Files: app/config.py, app/nodes/topics.py, app/nodes/write.py, tests/unit/test_tracing.py

- [x] Task 11: Harden `topics.py` JSON extraction against reasoning-style LLM output (P1)
  - Discovered during Task 8's live end-to-end verification: a real NVIDIA response
    can emit chain-of-thought prose before (or instead of, if it runs out of output
    tokens) the actual JSON topics array, and `_parse_topics` raises
    `ValueError: no JSON array found in response` with no fallback/retry —
    `run_topics` then crashes the whole graph run instead of degrading gracefully
  - Acceptance: a unit test with a fixture response that has reasoning prose before
    a trailing JSON array still parses correctly; a response that never produces a
    JSON array at all (simulating a truncated/reasoning-only completion) is retried
    once (e.g. with a stricter follow-up prompt) or fails that one chunk without
    aborting the rest of the book, per root AGENTS.md crash-safety rules
  - Files: app/nodes/topics.py, app/prompts/topics.md, tests/unit/test_topics.py
  - Completed: 2026-09-24 — `_parse_topics` now returns `None` (never raises) when
    a response doesn't resolve to a JSON array, whether because no `[...]` block
    exists at all or because the parsed JSON value isn't a list — both are the same
    "no usable topics" failure. `run_topics`: on `None`, retries once by re-calling
    `call_writer` with the original prompt plus a new `_RETRY_SUFFIX` telling the
    model explicitly not to reason/explain, just return the array; if the retry is
    also `None`, logs a `logger.warning` and writes `topics: []` for that chunk
    instead of raising, so one bad chunk degrades gracefully rather than aborting
    the whole graph run (root AGENTS.md crash safety). `app/prompts/topics.md`:
    strengthened the existing "no other text" rule to explicitly rule out
    reasoning/explanation, as defense in depth against hitting the retry path at
    all. `tests/unit/test_topics.py`: replaced
    `test_run_topics_rejects_non_list_response` (old behavior: raised `ValueError`)
    with 3 tests — retry succeeds on the second attempt after a reasoning-only
    first response; both attempts fail (reasoning-only) and the chunk degrades to
    `topics: []` with exactly 2 `call_writer` calls; a well-formed-but-wrong-type
    JSON response (an object, not a list) also degrades the same way after a
    retry. All 3 new tests were run against the old code first and failed for the
    expected reason (`ValueError`/`AttributeError`, not a broken test) before
    implementing. 69 total tests passing (68 passed, 1 skipped — the real-latexmk
    integration test, same as Tasks 7-9). bandit clean (`python -m bandit -r app/
    -ll`), pip-audit clean for project deps (same ambient system-`pip` CVEs as
    before). Eval gate (Step 6.5): this task edited `app/prompts/topics.md`, so the
    gate applies — ran `/eval`: no `EVAL_DATASET_NAME` and no eval runner exist in
    the repo yet (same finding as Tasks 5 and 6 — the eval runner itself doesn't
    exist until Milestone 5's judge/verify loop), so there is no baseline to gate
    against; flagged to the user rather than faked or silently skipped.
