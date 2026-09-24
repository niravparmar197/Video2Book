# Sprint v2 — Tasks

## Status: Complete

- [x] Task 1: Resolve a playlist URL into an ordered list of videos (P0)
  - Acceptance: given a playlist URL, `app/youtube.py` returns an ordered list
    of `{video_id, title, url, playlist_index}`; a single (non-playlist)
    video URL still returns a list of exactly 1; unit test mocks yt-dlp's
    playlist extraction (`extract_flat`), no real network call; a real 2-3
    video test playlist with captions on every video is picked and recorded
    in PRD.md's Dependencies section
  - Files: app/youtube.py, tests/unit/test_youtube.py
  - Completed: 2026-09-24 — Added `PlaylistEntry` dataclass +
    `list_playlist_videos()` in app/youtube.py using yt-dlp's `extract_flat`
    (no per-video metadata/captions download at this stage — just id/title,
    canonical watch URL rebuilt from video_id since flat-extraction `url`
    fields aren't reliably a full URL). No `entries` key in the result means
    a plain video URL, returned as a list of 1 with `playlist_index=1`, so
    v1's single-video path is unaffected. `None` entries (private/deleted
    playlist items) are skipped while keeping the remaining `playlist_index`
    values contiguous. 5 new unit tests (test_youtube.py) with a fake
    flat-extraction yt-dlp client, no real network call. 72/72 total tests
    passing (1 skipped, the real-latexmk integration test, unchanged from
    v1). bandit clean, pip-audit clean (only the pre-existing ambient
    system-`pip` CVEs, not a project dependency, same as every prior task).
    Live-verified against a real playlist: resolved 3Blue1Brown's "Neural
    Networks" playlist to 10 ordered videos with correct titles/ids; picked
    its first 3 videos as the v2 test playlist (chapter 1 is the same video
    v1 used, chapters 2-3 confirmed to have English captions too) and
    recorded it in PRD.md's Dependencies/Test playlist section.

- [x] Task 2: `fetch` node processes every video in the playlist (P0)
  - Acceptance: `videos.json` is written as an array with one entry per
    playlist video (title, video_id, captions path, playlist_index), each
    with its own captions file fetched; unit test with a 2-video fake
    playlist asserts 2 caption files and 2 `videos.json` entries
  - Files: app/nodes/fetch.py, tests/unit/test_fetch.py
  - Completed: 2026-09-24 — Added `playlist_index: int = 1` (defaulted, so
    the existing single-video `VideoInfo` construction is unaffected) to
    `app.youtube.VideoInfo`, and a new `run_fetch_playlist()` in
    app/nodes/fetch.py that calls `list_playlist_videos()` (Task 1) then
    `fetch_video()` per entry, stamping each result's `playlist_index` via
    `dataclasses.replace`. `_write_videos_json` now includes
    `playlist_index` in the JSON payload. Left the existing single-video
    `run_fetch()` untouched (still used by graph.py) rather than routing it
    through the playlist path, since that would call `list_playlist_videos`
    inside a code path `test_fetch.py`'s existing tests rely on being a
    single mocked `fetch_video()` call with no network access — graph.py's
    switch to the playlist-aware path is Task 3's job. 4 new unit tests
    (2 for run_fetch_playlist, both mocking list_playlist_videos +
    fetch_video, no real network call), all existing test_fetch.py tests
    still pass unmodified. 74/74 total tests passing (1 skipped, the
    real-latexmk integration test, unchanged). bandit clean, pip-audit
    clean (same pre-existing ambient system-`pip` CVEs, not a project
    dependency). Live-verified: fetched the real 3-video v2 test playlist
    (Task 1) end to end — 3 caption files written, `videos.json` has 3
    correctly ordered entries with matching titles/durations/playlist_index.

- [x] Task 3: Loop `chunk` → `topics` → `write` over every video (P0)
  - Acceptance: `graph.py`'s pipeline runs chunk/topics/write once per video
    in the playlist, producing `work/chunks/`, `work/topics/`, and
    `work/notes/<video_id>.md` for each; unit test with a 2-video fixture
    asserts notes files exist for both video_ids and neither video's LLM
    calls are skipped or merged with the other's
  - Files: app/graph.py, tests/unit/test_graph.py
  - Completed: 2026-09-24 — `chunk.py`/`topics.py`/`write.py` were already
    video_id-keyed from v1 (no changes needed there); rewired `graph.py`'s
    `BookState` from singular `video_id`/`title`/`captions_path` to a
    `videos: list[VideoRef]` produced by Task 2's `run_fetch_playlist()`
    (swapped in for the old `run_fetch` import), with `chunk_paths` and
    `notes_paths` now `dict[video_id, ...]`. `_chunk_node`/`_topics_node`/
    `_write_node` each loop over every video, still wrapped in
    `run_cached()` per chunk/video so re-running skips completed LLM calls
    per video independently. `_render_node` also loops, rendering +
    compiling one chapter per video — `book.pdf` is left as just the last
    rendered chapter for now (documented in the module docstring as
    interim), since assembling all chapters into one PDF with a table of
    contents is Task 6's job (`main.tex.j2`), not this task's.
    Updated `test_graph.py`'s two existing tests to a 2-video fixture,
    asserting per-video topics/notes/chapter files exist for both video_ids
    and that LLM call counts scale with video count (2, not 1) both on
    first run and on a cached re-run. Also updated `test_resume.py`'s fake
    fetch (only, not its test logic) to match the new
    `run_fetch_playlist`-shaped monkeypatch target, still exercising a
    single-video crash/resume scenario — true multi-video resume is Task
    8's job. 74/74 total tests passing (1 skipped, the real-latexmk
    integration test, unchanged). bandit clean, pip-audit clean (same
    pre-existing ambient system-`pip` CVEs, not a project dependency).
    Live-verified end to end against the real 3-video v2 test playlist with
    topics/write LLM calls and latexmk mocked (fetch/chunk are real):
    `book.pdf` plus all 3 videos' chunks/topics/notes/chapters written
    correctly under `work/` and `chapters/`.

- [x] Task 4: `outline.py` builds a video-order book plan (P0)
  - Acceptance: given the playlist's video list + notes, `outline.py` writes
    `outline.json` (chapters in playlist order, stable `chapter:<video_id>`
    ids, title, `skip: false`/`locked: false` defaults) and a human-readable
    `outline.md`; unit test with 3 videos asserts chapter order matches
    playlist order and that re-running outline generation twice on the same
    input produces identical ids (stability)
  - Files: app/nodes/outline.py, tests/unit/test_outline.py
  - Completed: 2026-09-24 — `run_outline(videos, output_dir)` writes
    `outline.json` (list of `{id, video_id, title, order, skip, locked}`,
    `id` = `chapter:<video_id>`) and `outline.md` (numbered list with
    `[skip]`/`[locked]` tags for human review). Re-running loads any
    existing `outline.json` first and carries forward each existing
    chapter's `skip`/`locked` flags by id, so a manual edit made between
    `--plan-only` and `--resume` (Task 5) is never clobbered — verified by a
    dedicated test that hand-edits `outline.json` between two `run_outline`
    calls. 3 new unit tests, no LLM/network calls. 79/79 total tests passing
    (1 skipped — the real-latexmk integration test in this shell's
    corrupted-PATH state, same known issue as Task 6). bandit clean,
    pip-audit clean (same pre-existing ambient system-`pip` CVEs).

- [x] Task 5: `--plan-only` stops the run after the outline is written (P0)
  - Acceptance: `python -m app.cli <playlist url> --plan-only` writes
    `outline.json`/`outline.md` and exits before any render or compile step;
    unit test monkeypatches the render node and asserts it is never called
    when `--plan-only` is passed
  - Files: app/cli.py, app/graph.py, tests/unit/test_cli.py
  - Completed: 2026-09-24 — Added an `outline` node (Task 4's `run_outline`)
    to the full graph, between `write` and `render`. Added a second graph
    builder, `build_plan_graph()` (fetch→chunk→topics→write→outline→END,
    no render node), and `run_plan()`, sharing the same checkpoint db/
    thread_id as `run_book`/`resume_book`. `cli.py`'s `--plan-only` branch
    now calls `run_plan()` instead of erroring. **Important finding,
    empirically verified (not just assumed):** `--resume` does NOT continue
    a run past a `--plan-only` stop — LangGraph's checkpoint marks that
    thread as terminated at `outline`'s `END` edge, so `resume_book()`
    (`graph.invoke(None, ...)`) returns immediately without reaching
    render (confirmed via a manual script: it raised `KeyError('pdf_path')`
    instead of producing a book). The actual continuation path is a **plain
    re-run** of the same command (no flag) — a fresh `run_book()` invoke
    re-executes fetch/chunk (cheap/idempotent) and outline (preserves the
    manual `skip`/`locked` edit, Task 4), while topics/write skip via
    `run_cached` file-existence checks, then proceeds to render — also
    empirically verified (topics/write call counts stayed at 1 across the
    plan run + edit + rerun, and the manual `skip: true` edit was still
    `true` after). This differs from the literal wording in root
    `AGENTS.md` ("`--plan-only` → edit `outline.json` → `--resume`"); noting
    it here rather than silently diverging — a true resume-after-plan
    mechanism (e.g. a conditional graph edge keyed on a `plan_only` state
    flag) could replace this in a later sprint if the exact `--resume`
    verb matters, but was not pursued now since it adds real complexity
    for a wording difference with an already-correct working alternative.
    New tests: `test_run_plan_stops_before_render` (test_graph.py, monkey-
    patches `compile_chapter` and asserts it's never called, outline files
    exist, no `chapters/` dir created) + 2 `test_cli.py` tests for the
    `--plan-only` → `run_plan` wiring. 81/81 total tests passing (1
    skipped — real-latexmk, corrupted-PATH shell issue, same as Task 6).
    bandit clean, pip-audit clean (same pre-existing ambient CVEs).

- [x] Task 6: Multi-chapter compile with TOC (P0)
  - Acceptance: a new `main.tex.j2` template `\input`s each non-`skip`ped
    chapter in outline order and generates a table of contents; latexmk
    compiles `output/<book>/book.pdf` containing N chapters; integration
    test (skipped if latexmk isn't on PATH) compiles a 2-chapter fixture and
    checks the output starts with `%PDF`
  - Files: app/latex/tex.py, app/latex/templates/main.tex.j2, tests/unit/test_tex.py, tests/integration/test_tex_compile.py
  - Completed: 2026-09-24 — `chapter.tex.j2` changed from a standalone
    document to an includable fragment (`\chapter{title}` + `\section{...}`s,
    no `\documentclass`/`\begin{document}`), since `main.tex.j2` needs to
    `\input` it — a nested `\documentclass` can't compile. Not in the
    original Files list but required for `\input` to work; updated its
    existing test (`test_render_chapter_writes_tex_file`) accordingly. New
    `render_book(chapter_ids, output_dir)` in app/latex/tex.py renders
    `chapters/main.tex` from `main.tex.j2` (report class, `\tableofcontents`,
    one `\input{<id>}` per chapter in order); reuses the existing generic
    `compile_chapter()` unchanged (it already just runs latexmk on any given
    `.tex` path). Rewrote the old single-chapter integration test (a lone
    fragment can no longer compile standalone) into a real 2-chapter
    `render_book` + `compile_chapter` compile. 4 new/updated unit tests +
    the rewritten integration test. This sandbox's Bash `PATH` is corrupted
    (known issue, v1 Task 8) so latexmk resolves only with a rebuilt PATH;
    with that fix, 77/77 tests passing with 0 skipped (the real-latexmk
    integration test actually ran and passed, not skipped). bandit clean,
    pip-audit clean (same pre-existing ambient system-`pip` CVEs).

- [x] Task 7: Render step reads `outline.json` and skips flagged chapters (P0)
  - Acceptance: setting `skip: true` on one chapter in `outline.json` and
    re-running excludes that chapter from `main.tex`/`book.pdf` on the next
    run, without deleting or re-fetching that video's cached notes; unit
    test edits `outline.json` between two `run_book()` calls and asserts the
    skipped chapter's `call_writer`/render are not invoked again while the
    remaining chapter still renders
  - Files: app/graph.py, app/nodes/outline.py, tests/unit/test_outline.py
  - Completed: 2026-09-24 — `_render_node` now iterates `state["chapters"]`
    (from the `outline` node) instead of `state["videos"]` directly: skips
    any chapter with `skip: true`, renders every other chapter (unchanged
    `render_chapter()`), then calls Task 6's `render_book()` +
    `compile_chapter()` on the resulting `main.tex` and copies that PDF to
    `book.pdf` — replacing Task 3's interim "book.pdf = last chapter"
    placeholder now that Task 6's TOC-driven multi-chapter compile exists.
    topics/write still process every video regardless of `skip` (the point
    is to not redo already-cached understand-phase work when a chapter is
    excluded later, not to skip generating it in the first place — matches
    the PRD goal wording). New test
    `test_run_book_respects_outline_skip_flag_on_rerun` in test_graph.py:
    runs a 2-video book, edits `outline.json` to skip the second video,
    reruns, and asserts `render_chapter` is called only for the kept video
    on the second run while `chapters/main.tex` contains `\input{}` for the
    kept video and not the skipped one. Fixed an unrelated `SyntaxWarning`
    (unescaped `\i` in a graph.py docstring, introduced by this task's own
    docstring update) before finishing. 83/83 tests passing with a clean
    PATH (0 skipped — real-latexmk integration test ran), 82/83 with the
    corrupted-PATH shell default (1 skipped, same known issue as Tasks 6/4).
    bandit clean, pip-audit clean (same pre-existing ambient CVEs).

- [x] Task 8: End-to-end playlist run + `--resume` across a playlist (P0)
  - Acceptance: `python -m app.cli "<2-3 video playlist url>"` produces a
    `book.pdf` with one chapter per video and a TOC; interrupting after
    video 1 of 2 finishes fetch/chunk/topics/write and video 2 has not
    started, then `--resume` finishes the book without re-fetching or
    re-writing video 1; unit test simulates the crash via a monkeypatched
    node raising on video 2's first call and asserts video 1's `call_writer`
    call count doesn't increase after resume
  - Files: app/graph.py, tests/unit/test_resume.py
  - Completed: 2026-09-24 — No `graph.py` changes needed: Tasks 3/6/7's
    per-video `run_cached` caching inside each looping node, combined with
    LangGraph's existing per-node (not per-loop-iteration) checkpoint
    granularity, already makes playlist-wide resume correct — a node that
    raises partway through its video loop re-runs its whole loop on resume,
    but every already-completed video inside that loop is a no-op via
    `run_cached`'s file-existence check. New test
    `test_resume_continues_playlist_after_crash_without_redoing_completed_video`
    (test_resume.py): 2-video playlist, video1's write succeeds, video2's
    write raises on its first attempt (crashing `run_book`); asserts
    fetch/chunk/topics counts are exactly 1/2/2 both before and after
    `resume_book()`, video1's write is not retried (write call count goes
    2→3, not 2→4), and `resume_book()` produces `book.pdf` with both
    chapters `\input` in `chapters/main.tex`. 83/83 tests passing (1
    skipped — corrupted-PATH shell issue, same as prior tasks; 0 skipped
    with a rebuilt clean PATH). bandit clean, pip-audit clean (same
    pre-existing ambient CVEs). Live-verified: a real end-to-end run
    against the actual 3-video test playlist (real fetch/chunk/latexmk,
    only `call_writer` mocked) produced a genuine `%PDF`-header `book.pdf`
    with all 3 chapters `\input`'d in playlist order and a real
    `main.toc`. Note: an earlier attempt using a `/tmp/...`-style scratch
    path failed latexmk with a mangled path (`Could not find file
    '/tmpXverifychaptersmain.tex'`) — root-caused to that path's literal
    directory name ("tmp") coinciding with Perl backslash-escape sequences
    (`\t`, `\v`, `\c`) that some layer of the Windows latexmk toolchain
    interprets; confirmed as an artifact of that ad-hoc verification path
    choice, not an app bug — real `output/<slug>/...` directories and
    pytest's `tmp_path` fixture (already exercised by the integration test)
    don't hit this, and switching to the session's scratchpad directory
    resolved it immediately.

- [x] Task 9: `--estimate` totals cost/time across the whole playlist (P1)
  - Acceptance: `python -m app.cli <playlist url> --estimate` prints a
    per-video line (chunks, tokens) plus a totals line (chunk count, token
    count, cost) summed across every video in the playlist, before any LLM
    call; unit test with 2 fake videos asserts the totals equal the sum of
    the two per-video estimates
  - Files: app/estimate.py, tests/unit/test_estimate.py
  - Completed: 2026-09-24 — Added `estimate_playlist(url, chunk_minutes)`,
    which resolves the URL via Task 1's `list_playlist_videos()` (a single
    video URL still returns a list of 1, unaffected) and runs the existing
    per-video `estimate_video()` for each entry — still no LLM call
    anywhere (verified by the existing static source-scan test, unchanged).
    `print_estimate()` now prints one block per video plus a `Total
    chunks`/`Total tokens`/`Total cost` summary (and a `Total videos` line
    when there's more than one). Updated the existing
    `test_print_estimate_output` to also mock `list_playlist_videos`
    (needed since `print_estimate` now routes through it) — its loose
    content assertions (`"chunks"`, `"token"`, `"$0.00"` substrings) still
    pass unchanged against the new multi-block output. 2 new tests:
    `estimate_playlist` totals equal the sum of two fake videos' individual
    estimates; `print_estimate`'s printed output contains both videos' ids
    and the totals lines. 85/85 total tests passing (1 skipped —
    corrupted-PATH shell issue, same as prior tasks). bandit clean,
    pip-audit clean (same pre-existing ambient CVEs). Live-verified:
    `python -m app.cli "<the real 10-video 3Blue1Brown playlist>" --estimate`
    printed all 10 videos with correct per-video durations/chunk counts and
    correct summed totals (12 chunks, 93,224 tokens, $0.00), with no LLM
    call and no output written to disk.
