# Sprint v7 — Tasks

## Status: In Progress

- [x] Task 1: Proactive rate-limit pacing in `call_writer` (P0)
  - Acceptance: `call_writer` waits, before each call, as needed to keep
    that provider's calls under its configured RPM (NVIDIA ~40, Gemini
    ~10, per root `AGENTS.md`) — a simple min-interval-since-last-call
    sleep is enough, no external dependency; unit test with an injectable
    clock/sleep asserts back-to-back calls to the same provider are paced
    at least `60/RPM` seconds apart, and calls to different providers are
    not paced against each other
  - Files: app/llm.py, tests/unit/test_llm.py
  - Completed: 2026-09-24 — `_pace(provider, sleep, clock)` tracks a
    module-level `_last_call_at` timestamp per provider and sleeps just
    enough to keep consecutive calls to the same provider at least
    `60/RATE_LIMITS_RPM[provider]` seconds apart; called from `_call_once`
    before each provider attempt (both primary and fallback), so pacing
    applies proactively on every call, not just reactively after a 429.
    `call_writer` gained a `clock` param (default `time.monotonic`)
    alongside the existing injectable `sleep`. **Found and fixed
    immediately** (anticipated from the v5/v6 cross-module-call
    precedent, not a surprise): 2 existing `test_llm.py` tests asserted
    exact `sleeps == [...]` lists that broke because pacing correctly adds
    a real sleep between a retry's second same-provider call and the
    first — fixed by injecting a fake `clock` that always reports a large
    elapsed time for those specific backoff-focused tests (pacing has its
    own dedicated tests instead). Added an autouse `conftest.py` fixture
    resetting `llm._last_call_at` before every unit test (process-wide
    mutable state would otherwise leak between tests, same class of
    hazard as v5/v6's per-module `call_writer` stubs, caught proactively
    this time rather than via a failing run). 3 new dedicated pacing
    tests using a shared fake clock/sleep test double (pacing applies
    between 2 same-provider calls; never applies to a first call; never
    applies across different providers). 178/178 tests passing (5
    skipped, known corrupted-PATH shell issue; suite still well under the
    ~30s budget at ~18s). bandit clean, pip-audit clean. No prompts
    touched, eval gate doesn't apply.

- [x] Task 2: Enforce `MAX_BOOK_HOURS` in `--estimate` and `run_book` (P0)
  - Acceptance: `--estimate`'s playlist total duration is checked against
    `MAX_BOOK_HOURS`; over the limit, `--estimate` prints a clear warning,
    and a plain run (`run_book`) raises before doing any real work unless
    a new `--force` CLI flag is passed; unit test with a fake playlist
    total over the limit asserts `run_book` raises without `--force` and
    proceeds (reaching the fetch node) with it
  - Files: app/estimate.py, app/graph.py, app/cli.py, tests/unit/test_estimate.py, tests/unit/test_graph.py, tests/unit/test_cli.py
  - Completed: 2026-09-24 — the `check_budget` node/`BudgetExceededError`
    gate and `force`/`max_book_hours`/`max_book_cost_usd` settings already
    existed on disk from prior scaffolding but were only wired into the
    `video`-order graph, had no CLI flag, and had zero test coverage; this
    pass finished the wiring: `check_budget` added to `build_topic_graph`/
    `build_topic_plan_graph` too (it was previously silently skipped for
    `BOOK_ORDER=topic`, a real gap now closed), `--force` added to
    `build_parser`/`main` and threaded through `run_book(..., force=)` /
    `run_plan(..., force=)`, and `print_estimate` now prints a `WARNING:
    ... pass --force to proceed anyway` line whenever total duration
    exceeds `MAX_BOOK_HOURS`. 9 new tests (over/force pairs for both
    graphs' hours gate, plus the topic-graph gate). 188/188 tests passing,
    well under the ~30s budget (~11s). bandit clean (0 issues at -ll).
    pip-audit flags only the `pip` tool itself (12 CVEs on the pinned
    pip==24.0 launcher, unrelated to any app dependency) — pre-existing,
    not caused by this change, not blocking. No prompts touched, eval gate
    doesn't apply.

- [x] Task 3: Enforce `MAX_BOOK_COST_USD` alongside it (P0)
  - Acceptance: the same check/`--force` gate from Task 2 also covers
    `estimated_cost_usd` against `MAX_BOOK_COST_USD`; a no-op today since
    both providers are free (`estimated_cost_usd` is always `0.0`), but
    future-proofed for a paid provider; unit test forces a non-zero fake
    cost estimate over the limit and asserts the same refuse/`--force`
    behavior as Task 2
  - Files: app/estimate.py, app/graph.py, tests/unit/test_estimate.py, tests/unit/test_graph.py
  - Completed: 2026-09-24 — done in the same pass as Task 2 since it's the
    same gate (`_check_budget_node` already checked
    `_estimate_total_cost_usd(...)` against `max_book_cost_usd`, just
    needed test coverage): 3 new tests monkeypatch
    `graph._estimate_total_cost_usd` to force a non-zero cost over the
    limit and assert raise-without-`--force` / proceed-with-`--force`, plus
    an estimate-side test forcing `estimated_cost_usd=5.0` and asserting
    `print_estimate` warns with `MAX_BOOK_COST_USD` in the message. Covered
    by the same full-suite/bandit/pip-audit run as Task 2.

- [ ] Task 4: Real timed ~2-hour playlist run (Milestone 7 first checkpoint) (P0)
  - Acceptance: a real playlist totaling roughly 2 hours of source video is
    picked and run for real end to end (`VIDEO_MODE` and `BOOK_ORDER` at
    their real defaults); wall-clock time for the whole run and disk usage
    of the resulting `output/<book>/` directory are both actually measured
    and recorded; the resulting `book.pdf` is confirmed clean (compiles,
    has real content, no manual fixes needed)
  - Files: sprints/v7/PRD.md
  - Attempted 2026-09-24, not complete — real, reproducible infra findings,
    no `book.pdf` yet. Full detail in `sprints/v7/SCALE_REPORT.md`
    ("Task 4 real-run evidence"); summary:
    - Real playlist: StatQuest "Neural Networks"
      (`list=PLjUC8HjyxGTSrn4cZEw9Uw8R0STaRcbYY`), 6 videos, 1h 23m
      (verified via `--estimate`, real defaults `VIDEO_MODE=stream`
      `BOOK_ORDER=topic`), run at `output/https-www-youtube-com-playlist-
      list-PLjUC8HjyxGTSrn4cZEw9Uw8R0ST`.
    - Real per-phase timing (all 6 videos): fetch+chunk 38s; frames
      (stream-mode ffmpeg scene detection) ~20min, including one video
      that hit ffmpeg's 300s stream-decode timeout and fell back to a
      chunk-scoped download (still succeeded, just slower); topics ~5-6min
      per chunk *while NVIDIA was degraded* (see below) vs. 4.2s for a
      trivial prompt once healthy.
    - **Finding A (real primary-provider outage):** NVIDIA (`nemotron-3-
      super-120b-a12b`) gave real `ReadTimeout` after the full 280s
      request timeout, 3x per `call_writer` attempt, on 2 separate
      `--resume` attempts ~12min apart. A direct `call_writer("...pong")`
      sanity check between them returned in 4.2s, confirming the service
      was genuinely degraded, not a bug in our retry/timeout code.
    - **Finding B (Gemini's real free-tier cap is far tighter than
      documented):** the fallback failed every time with a real 429 —
      `generativelanguage.googleapis.com/generate_content_free_tier_
      requests`, **quota=20 requests/day** for `gemini-3.8-flash`, not
      just the ~10 RPM root `AGENTS.md` documents. 6 videos x up to 3
      calls/chunk exhausted it before the run even finished topics.
    - **Finding C (new bug, filed as Task 8 below):** when NVIDIA's
      degradation corrupted `plan.py`'s topic-merge response, its
      degrade-to-unmerged-plan fallback produced **147 chapters from 6
      videos** (many single-sentence, several non-topical: e.g.
      `chapter:welcome-to-statquest`, `chapter:links-are-in-the-
      description-below`) — this is LangGraph-checkpointed as done, so a
      `--resume` cannot recover it; only a fresh run avoids it.
    - **Finding D (shared-machine resource pressure and a cross-session
      collision):** 5 other Claude Code sessions were concurrently active
      on this machine; Claude Code auto-killed one background run because
      "the system is running low on memory" (not this project's bug).
      Separately, a second real attempt launched against the 3B1B "Neural
      networks" playlist (10 videos, 3.63h) turned out to hit the exact
      same deterministic `output_dir` (`_output_dir_for_url` hashes the
      URL) another concurrent session was already using for its own Task
      5 crash/resume test — two processes briefly ran `graph.invoke()`
      against the same `output_dir`/`SqliteSaver` checkpoint db at once.
      Caught and stopped (`TaskStop`) within a few minutes once noticed;
      that run's numbers are **not** used above or in `SCALE_REPORT.md` —
      only Run 1 (StatQuest, a directory no other session touched) is
      treated as real evidence. Lesson for next time: pick a playlist and
      confirm with any other active session on the same machine *before*
      launching, not after.
    - Disk usage for the real (partial) run: see Task 6 below.
    - Next attempt should run when NVIDIA's free tier is healthy, ideally
      on a dedicated (not multi-session) machine, and after Task 8 is
      fixed so a degraded plan-merge can't corrupt the book.

- [ ] Task 5: Real crash + resume validation on a larger real playlist (P1)
  - Acceptance: a real 5-6 video playlist run is interrupted partway
    through (a real crash, e.g. killing the process mid-run, not a
    monkeypatched one) and `--resume` is confirmed to finish the book
    without redoing any already-completed video's fetch/chunk/topics/write
    — real evidence (timestamps/logs), not just the existing unit-level
    resume tests
  - Files: sprints/v7/PRD.md

- [x] Task 6: Disk/memory footprint check for the Task 4 run (P1)
  - Acceptance: the full `output/<book>/` directory from Task 4's real run
    is inspected and its size broken down by subdirectory (`work/`,
    `assets/`, `chapters/`); confirms no video file was saved anywhere
    (stream mode) and no unexpectedly large intermediate files were left
    behind; any real finding gets filed as a follow-up task rather than
    silently ignored
  - Files: sprints/v7/PRD.md
  - Completed: 2026-09-24 — measured on Task 4's real (partial, pre-write)
    run directory: **1.1MB total** for 6 videos / 1h23m of source video —
    `work/captions` 372K, `work/chunks` 140K, `work/frames` 12K (JSON
    metadata only), `assets/` (kept screenshots) 44K across 2 of 6 videos
    (the other 4 genuinely had zero scene-change frames above the 0.4
    threshold — StatQuest's slow-changing whiteboard style rarely triggers
    a hard cut; not a bug, `AGENTS.md`'s "one per scene change, not a
    timer" behaving as designed), `graph_state.sqlite*` (LangGraph
    checkpoint) 92K, `plan.json`/`outline.json`/`ordered_plan.json` 125K
    combined (inflated by the 147-chapter degrade-to-unmerged-plan bug,
    Task 8). **Confirmed: zero video or audio files anywhere in
    `output/`** (`find ... -iregex '.*\.(mp4|mkv|webm|m4a|mp3|wav)$'`
    returned nothing) — stream mode's no-video-saved guarantee holds.
    `work/notes` and `chapters/` are empty since write/render never
    completed (Task 4 not done). Real finding filed as Task 8 below
    (plan-merge fallback bug); the 300s stream-decode timeout fallback
    (Task 4 Finding A/D context) is noted in `SCALE_REPORT.md` as a
    per-chunk worst-case cost but not filed as its own task since the
    fallback already handles it correctly, just slower.

- [x] Task 7: Document the 8h/15h/30h projection and the overnight verdict (P1)
  - Acceptance: using Task 4's real measured per-chunk/per-video wall-clock
    time (and Task 1's rate-limit pacing), a documented projection for
    8-hour, 15-hour, and 30-hour playlists is written into `PRD.md` or a
    new `sprints/v7/SCALE_REPORT.md`, stating plainly whether a 30-hour
    playlist can plausibly finish "overnight" (interpreted as within
    ~10-12 hours) under real free-tier rate limits, and — if not — exactly
    what would need to change (e.g., a paid tier, parallelism, a longer
    "overnight" budget) to get there
  - Files: sprints/v7/SCALE_REPORT.md
  - Completed: 2026-09-24 — `sprints/v7/SCALE_REPORT.md` written from Task
    4's real measured rates (frames: ~14.5min/video-hour; LLM calls:
    ~120s/call real observed latency, well above the RPM-enforced floor
    from Task 1's `_pace()`). Verdict: **no**, a 30h playlist does not
    plausibly finish overnight (~10-12h) — the optimistic/healthy-provider
    projection alone is ~13.4h, and the conditions Task 4 actually
    observed today (NVIDIA outage + Gemini's real 20-requests/day quota)
    push it far higher or stall it outright. Report ranks 3 fixes by
    leverage: a paid fallback tier (removes the dead-fallback failure
    mode entirely), parallelizing LLM calls up to each provider's RPM
    (real latency is 20-80x the RPM floor for a sequential pipeline — the
    single biggest lever), and parallelizing frames extraction (the larger
    of the two optimistic-case time sinks at 30h scale) — plus a cheaper,
    partial fix (widen the "overnight" budget) that doesn't address the
    reliability findings.

- [x] Task 8: Fix `plan.py`'s degrade-to-unmerged-plan fallback explosion (P1)
  - Found during: Task 4's real run, 2026-09-24 (see TASKS.md Task 4
    Finding C, `SCALE_REPORT.md` section 1). When the topic-merge LLM call
    (`run_plan_topics`, `app/nodes/plan.py`) never returns a parseable JSON
    array — even after its one retry — `_degrade_to_unmerged_plan` falls
    back to one plan entry per *raw chunk topic string*, with no merging,
    no `needs`/`level`, and no filtering. On a real 6-video playlist this
    produced **147 chapters**, several clearly non-topical (video-outro
    filler like "welcome to statquest" and "links are in the description
    below" ended up as first-class book chapters alongside real topics).
    Because `_plan_node` has no `run_cached` wrapper but LangGraph still
    checkpoints the node as complete once it runs, a bad degraded plan is
    permanently locked in for that `output_dir` — `--resume` cannot
    recover it; only starting over in a fresh directory avoids it. This
    directly undermines `BOOK_ORDER=topic`'s whole purpose (root
    `AGENTS.md`: "merges repeated topics and orders them correctly") and
    would produce an unusable, hundreds-of-chapters book exactly when the
    provider is already struggling (i.e. the worst possible time for it to
    happen).
  - Acceptance: TBD by whoever picks this up next sprint — options include
    (a) a saner degraded fallback that groups by shared topic *string*
    similarity or just refuses to explode past some sane chapter-count
    ceiling and raises instead, forcing a `--resume` retry of the merge
    call instead of silently shipping a broken plan; (b) filtering
    obviously non-topical entries (very short, sponsorship/outro-shaped
    strings) before they ever reach the merge prompt; (c) making
    `_plan_node` retry-safe (bounded retries across processes, or simply
    not writing `plan.json` — and thus not checkpointing the node as
    done — until a merge attempt actually succeeds, so `--resume` gets a
    real second chance instead of being stuck with the degraded output).
    Needs its own unit test asserting the fallback path is either removed
    or bounded.
  - Files: app/nodes/plan.py, tests/unit/test_plan.py
  - Completed: 2026-09-25 — combined options (b) and (a): `_filter_non_topical`
    drops filler/outro-shaped topic strings (a small regex denylist covering
    the exact patterns Finding C observed -- "welcome to", "links ... in the
    description", "thanks for watching", "like/subscribe", "sponsor", etc.)
    before they ever reach the merge prompt *or* the degrade fallback,
    dropping a chunk entirely if nothing topical survives in it. On top of
    that, `_degrade_to_unmerged_plan`'s output is now checked against a
    ceiling (`max(20, 3 * num_chunks)`); if the merge failed twice *and* the
    unmerged fallback would still exceed it, `run_plan_topics` raises a new
    `PlanMergeFailedError` instead of writing `plan.json` — `_plan_node` has
    no `run_cached`/try-except around it, so an uncaught raise means
    LangGraph never checkpoints the `plan` node as complete, and `--resume`
    gets a real second attempt at the merge call instead of being
    permanently stuck with a bad plan (same crash-safety pattern as
    `BudgetExceededError`/`check_budget`). 2 new tests: filler topics
    (`"Welcome to StatQuest"`, `"Links are in the description below"`)
    excluded from both the prompt and the degraded result while a real
    topic in the same chunk survives; a 15-chunk/4-topics-each case (60 raw
    topics vs. a 45 ceiling) raises `PlanMergeFailedError` and leaves no
    `plan.json` on disk. Existing single-chunk degrade test (1 topic, well
    under the ceiling) still passes unchanged. 203/203 tests passing full
    suite (~74s). bandit clean on `app/nodes/plan.py`.
