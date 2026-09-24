# Sprint v6 — Tasks

## Status: In Progress

- [x] Task 1: `book_pass.py` — glossary extraction + merge across chapters (P0)
  - Acceptance: `run_glossary(output_dir) -> list[dict]` sends every
    chapter's/topic's final notes (grouped by chapter, labeled) to a new
    `glossary.md` prompt in one call, parses `[{"term", "definition"}, ...]`,
    dedupes case-insensitively across chapters (first definition wins),
    and writes `work/book_pass/glossary.json`; unit test with 2 fixture
    chapters sharing one overlapping term asserts the merged glossary has
    exactly one entry for it
  - Files: app/nodes/book_pass.py, app/prompts/glossary.md, tests/unit/test_book_pass.py
  - Completed: 2026-09-24 — `run_glossary(chapters, output_dir)` sends
    every chapter's title+notes (labeled `=== Chapter: <title> ===`) in
    ONE combined LLM call, reusing the proven parse/retry/degrade pattern
    from `topics.py`/`plan.py` (one retry with a stricter suffix, then
    degrades to an empty glossary rather than crashing the book).
    Defensive case-insensitive dedup in code (not just prompted) — first
    occurrence's definition wins — since a single LLM call across many
    chapters can still emit a near-duplicate entry. Writes
    `work/book_pass/glossary.json`, alphabetized by term. 3 new unit
    tests: merge+dedupe (stubbed response has the same term twice with
    different definitions, asserts the first is kept), prompt includes
    every chapter's title and unique content, and the retry→degrade path.
    154/154 tests passing (3 skipped, known corrupted-PATH shell issue).
    bandit clean, pip-audit clean. Eval gate: new prompt file, technically
    applies — no `EVAL_DATASET_NAME`/runner exists yet, same finding as
    every prior prompt-touching task, flagged not skipped.

- [x] Task 2: `book_pass.py` — subject-index term extraction per chapter (P0)
  - Acceptance: `run_index_terms(chapter_id, notes, output_dir) -> list[str]`
    calls a new `index_terms.md` prompt to extract genuinely index-worthy
    terms (not every noun) from one chapter's notes, writes
    `work/book_pass/index_terms_<chapter_id>.json`; unit test with a
    stubbed response asserts the terms list is parsed and written, and a
    malformed response degrades to an empty list rather than raising
  - Files: app/nodes/book_pass.py, app/prompts/index_terms.md, tests/unit/test_book_pass.py
  - Completed: 2026-09-24 — `run_index_terms(chapter_id, notes,
    output_dir)` reuses the same `_call_with_retry` helper Task 1 built
    (shared retry/degrade logic across both generators). Case-insensitive
    dedup applied to the term list too. Writes
    `work/book_pass/index_terms_<chapter_id>.json`. 3 new unit tests:
    parse+write, case-insensitive dedup, and degrade-to-empty-list on an
    unparseable response. 157/157 tests passing (3 skipped, known
    corrupted-PATH shell issue). bandit clean, pip-audit clean. Eval gate:
    new prompt file, flagged not skipped, same as Task 1.

- [x] Task 3: `book_pass.py` — preface generation (P0)
  - Acceptance: `run_preface(chapters, output_dir) -> Path` calls a new
    `preface.md` prompt with the book's chapter/topic titles (not full
    notes — whole-book scope, not per-chapter) and writes
    `work/book_pass/preface.md`; unit test with a stubbed response asserts
    the file is written and the prompt includes every given chapter title
  - Files: app/nodes/book_pass.py, app/prompts/preface.md, tests/unit/test_book_pass.py
  - Completed: 2026-09-24 — `run_preface(chapters, output_dir)` sends only
    chapter/topic titles (not full notes — whole-book scope) to a new
    `preface.md` prompt in a single plain-text call (not JSON, unlike
    glossary/index-terms), instructed to stay general since it only knows
    titles, never specific facts. Writes `work/book_pass/preface.md`. 1
    new unit test: file written + every given chapter title reaches the
    prompt. 158/158 tests passing (3 skipped, known corrupted-PATH shell
    issue). bandit clean, pip-audit clean. Eval gate: new prompt file,
    flagged not skipped, same as Tasks 1-2.

- [x] Task 4: Subject index — `\index{}` markup + real `makeindex` compile (P0)
  - Acceptance: `latex/tex.py` inserts `\index{term}` at each index term's
    first occurrence per chapter (case-insensitive match, only the first
    occurrence, never inside already-escaped LaTeX commands);
    `main.tex.j2` gets `\usepackage{imakeidx}`, `\makeindex`, and
    `\printindex`; a **real** latexmk compile (integration test, skipped if
    latexmk isn't on PATH) of a 1-chapter book with 2 index terms produces
    a PDF whose page count includes an index page (`latexmk` auto-runs
    `makeindex` when it detects `\makeindex` — verified, no manual
    `makeindex` subprocess call needed in this codebase)
  - Files: app/latex/tex.py, app/latex/templates/main.tex.j2, tests/unit/test_tex.py, tests/integration/test_tex_compile.py
  - Completed: 2026-09-24 — `render_chapter()` gained an `index_terms`
    param; `_insert_index_markup()` walks a chapter's rendered sections in
    order, case-insensitively finds each term's first occurrence in
    paragraph body text only (never in headings — matches how a reader
    would expect an index to point at explanatory prose, not a heading
    already visible in the TOC) and splices in `\index{term}` right after
    it, removing that term from the search set so only the first
    occurrence is ever marked. `main.tex.j2` unconditionally gets
    `\usepackage{imakeidx}` + `\makeindex` + `\printindex` (harmless/empty
    when no chapter supplies index terms — confirmed via the 3 pre-existing
    integration tests, none of which pass `index_terms`, all still
    compiling clean). 4 new unit tests + 1 new real integration test.
    **Found a real test-data bug in my own first draft of the integration
    test** (not a code bug): I asked for the term "Neural Networks"
    (plural) to be indexed, but the fixture notes only contain "neural
    network" (singular) in paragraph body text — the plural only appears
    in a section heading, which `_insert_index_markup` correctly does not
    search. The code behaved correctly (silently skipped a term not
    present in body text, per Task 4's own "skips a term not present"
    unit test); fixed the integration test's term list to match real
    body text instead. Confirmed via the real `.ind` file makeindex
    produces (not just a successful compile) that both real terms
    actually appear in the generated index. 161/161 tests passing (4
    skipped, known corrupted-PATH shell issue; 0 skipped with a clean
    PATH — all 4 real integration tests, including the new one, ran and
    passed for real). bandit clean, pip-audit clean.

- [x] Task 5: Topic index — structural list from `outline.json` (P0)
  - Acceptance: a new render function builds a topic index section (one
    line per chapter, in outline order, chapter/topic title only — no LLM
    call, no `makeindex`) as its own `chapters/topic_index.tex` fragment;
    unit test with a 3-chapter outline asserts all 3 titles appear in
    order
  - Files: app/latex/tex.py, app/latex/templates/topic_index.tex.j2, tests/unit/test_tex.py
  - Completed: 2026-09-24 — `render_topic_index(chapters, output_dir)`
    builds `chapters/topic_index.tex`: an unnumbered `\chapter*{Topic
    Index}` (still listed in the TOC via `\addcontentsline`) with a
    simple `\begin{enumerate}` list of escaped chapter/topic titles, in
    the given order — no LLM call, distinct from Task 4's LLM-extracted,
    page-numbered subject index. 2 new unit tests (order, escaping). Also
    manually compiled the fragment for real (throwaway script, not a
    committed test — Task 6 is what wires it into `main.tex.j2` for real,
    so a formal integration test belongs there) to catch any LaTeX syntax
    issue early; compiled clean. 163/163 tests passing (4 skipped, known
    corrupted-PATH shell issue). bandit clean, pip-audit clean.

- [x] Task 6: Front/back matter assembly in `main.tex.j2` (P0)
  - Acceptance: `render_book()` accepts a preface path and glossary
    entries, in addition to the chapter list, and assembles: title page →
    preface → TOC → chapters → glossary chapter → subject index
    (`\printindex`) → topic index, in that order; unit test asserts the
    rendered `main.tex` contains all six sections in the right order
  - Files: app/latex/tex.py, app/latex/templates/main.tex.j2, app/latex/templates/glossary.tex.j2, tests/unit/test_tex.py
  - Completed: 2026-09-24 — `render_book()` gained `preface_path`,
    `glossary_entries`, and `include_topic_index` params (all optional,
    default off — omitting them reproduces v2-v5's exact prior output,
    confirmed by the pre-existing `test_render_book_empty_chapter_list_
    still_writes_valid_shell` test still passing unmodified). New
    `render_glossary()` writes `chapters/glossary.tex` (escaped
    term/definition pairs via `glossary.tex.j2`). `main.tex.j2` now
    conditionally includes an unnumbered Preface chapter (before the
    TOC), `\input{glossary}` and `\input{topic_index}` (after the
    chapters), with `\printindex` always present between them (harmless
    when empty). 4 new unit tests (glossary escaping, full 7-marker
    ordering assertion, and confirmed optional sections are cleanly
    omitted when not requested) + 1 new real integration test compiling
    a complete book — preface, chapter with a real index term, glossary,
    subject index, and topic index all together — via a throwaway script
    first, then formalized. 166/166 tests passing (5 skipped, known
    corrupted-PATH shell issue; 0 skipped with a clean PATH — all 5 real
    integration tests ran and passed, ~73s total). bandit clean,
    pip-audit clean.

- [x] Task 7: Volume splitting by total video duration (P0)
  - Acceptance: a new `VOLUME_HOURS` setting (default 10) in `config.py`;
    when the playlist's total video duration crosses a multiple of
    `VOLUME_HOURS`, `render_book()` splits the chapter list into multiple
    `main_vol<N>.tex` files, each compiled to `book_vol<N>.pdf`; a
    playlist under the threshold still produces a single `book.pdf`
    (unchanged filename — no behavior change for the common case); unit
    test with a fake total duration just over 2x the threshold asserts 2
    volume files are produced with the chapters split accordingly
  - Files: app/config.py, app/latex/tex.py, app/graph.py, tests/unit/test_config.py, tests/unit/test_tex.py
  - Completed: 2026-09-24 — `VOLUME_HOURS` (default 10) added to
    `config.py`. `split_into_volumes()` (tex.py) greedily bin-packs
    `(chapter_id, hours)` pairs into groups of at most `volume_hours` each,
    preserving order, never splitting a single over-long chapter across
    volumes. `render_book_volumes()` renders one `main_vol<N>.tex` per
    group, reusing the same `main.tex.j2` (now volume-number-aware for
    the title) — front matter (preface) in volume 1 only, back matter
    (glossary/indexes) in the last volume only, so neither repeats across
    volumes. `graph.py`'s shared `_render_chapters()` sums each chapter's
    `hours` (video mode: real `duration_seconds`/3600, added to
    `VideoRef`; topic mode: approximated from source-chunk count ×
    `CHUNK_MINUTES`, since a merged topic has no single clean duration)
    and only switches to the multi-volume path when the total exceeds
    `volume_hours` — the single-book.pdf path is byte-for-byte the same
    code as before, so every pre-v6 test needed zero changes (confirmed:
    171 pre-existing tests all still passed unmodified once this landed).
    7 new unit tests (pure `split_into_volumes`/`render_book_volumes`
    behavior) + 2 new graph-level tests (a real split trigger with 16
    fake hours over a 10h threshold producing `book_vol1.pdf`/
    `book_vol2.pdf`, and confirmation the common case still produces
    plain `book.pdf`). 173/173 tests passing (5 skipped, known
    corrupted-PATH shell issue). bandit clean, pip-audit clean.

- [x] Task 8: Wire `book_pass` into `graph.py` for both `BOOK_ORDER` modes (P0)
  - Acceptance: a new `book_pass` node runs after `write` (both modes),
    calling glossary/index-term/preface generation, cache-skippable
    (re-running doesn't redo an already-generated glossary/preface) and
    resume-safe (mirrors the Task 7 pattern from sprint v5); `render`
    then uses `work/book_pass/*` outputs for front/back matter; unit test
    confirms both graphs produce a `book.pdf` (or `book_vol*.pdf`) with a
    glossary and both indexes present
  - Files: app/graph.py, tests/unit/test_graph.py, tests/unit/test_graph_topic_order.py
  - Completed: 2026-09-24 — New shared `_run_book_pass(chapters,
    output_dir)`: builds each non-skipped chapter's `{title, notes}`,
    calls `run_index_terms()` per chapter and `run_glossary()`/
    `run_preface()` once each — every call wrapped in `run_cached()`
    (checking `book_pass.py`'s own path helpers), matching every other
    LLM step's caching. Two thin per-mode wrappers (`_book_pass_node`/
    `_book_pass_topic_node`) build the mode-specific `{file_key, title,
    notes_path}` list (same shape `_render_node`/`_render_topic_node`
    already build) and call the shared helper — inserted as a new
    `book_pass` node between `outline`→`render` (video mode) and
    `write`→`render` (topic mode). `_render_chapters()` (and both render
    nodes) extended to thread `preface_path`/`glossary_entries`/
    `topic_index_chapters` through to `render_book()`/
    `render_book_volumes()`, and each chapter's `index_terms` through to
    `render_chapter()`. **Found and fixed the same class of cross-module
    test hazard as sprint v5's judge call** (predicted from that
    precedent, not rediscovered by surprise): `book_pass.py` makes its
    own `call_writer` calls, separate from `write.py`'s/`topics.py`'s —
    added another autouse conftest fixture defaulting
    `book_pass.call_writer` to an inert `"[]"` response (empty glossary/
    index terms; literal preface text, harmless unless a test checks
    preface content) for the whole unit suite. Also fixed 2 existing
    tests that broke on contact: a fake `render_chapter` wrapper's
    signature (needed the new 6th `index_terms` param) and a
    `\input{...}` line-count assertion (book_pass now always adds a topic
    index once it runs, since `_run_book_pass`'s return dict always has
    keys even when its values are empty, so `bool(book_pass)` is always
    truthy). 2 new dedicated tests (one per mode) using *real* stubbed
    glossary/index-term/preface content (disambiguated by each prompt's
    distinct trailing data-section label, not fragile keyword matching)
    to prove the wiring reaches the compiled `main.tex`/`glossary.tex`,
    not just the inert conftest default. 180/180 tests passing with a
    clean PATH (0 skipped — every real latexmk/Graphviz integration test
    ran, ~89s total; 175/180 with the corrupted-PATH shell default, 5
    skipped, known issue). bandit clean, pip-audit clean.

- [ ] Task 9: End-to-end verification with the real multi-video test playlist (P1)
  - Acceptance: running the real pipeline against the picked multi-video
    test playlist (v2/v3) produces a `book.pdf` with a real preface, a
    glossary containing real terms from the transcripts (no invented
    definitions), a real page-numbered subject index, and a topic index
    listing every chapter; a lowered `VOLUME_HOURS` test value confirms
    the volume split actually produces `book_vol1.pdf`/`book_vol2.pdf`
    for that same playlist
  - Files: sprints/v6/PRD.md
