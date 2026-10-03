# Sprint v10 — PRD: Frames/Topics Parallelism + Elapsed/Percent Progress

## Overview

Two operator-facing asks, neither tied to a root `AGENTS.md` milestone:
processing a short video was taking longer than expected because `frames`
(screenshot/scene-detection) and `topics`/`write` (the LLM chain) ran
strictly sequentially even though they don't depend on each other; and the
existing progress UI (sprints/v9's per-chapter list) had no sense of overall
percent-through-the-pipeline or how long a run had been going.

## Goals

- `frames` and `topics`(+downstream write/outline/book_pass) run as
  parallel branches off `chunk` in both `BOOK_ORDER` graphs, converging
  before `render` (which needs both: it reads frames' saved screenshots
  from disk and book_pass's chapters/glossary from graph state) — cuts
  wall-clock time by roughly the smaller branch's duration, with zero
  quality/output change
- `get_progress()` reports `percent` (0-100, based on completed-node count
  out of the phase's total node count) and `elapsed_seconds` (wall time
  since the run's first checkpoint), without needing an ETA
- The fix generalizes to any video under `CHUNK_MINUTES` (30 min) — a
  5-minute video benefits the same relative amount as a 30-minute one,
  since both are 1 chunk and pay the same fixed frames+LLM-chain cost
  today

## Real findings during implementation

- **LangGraph join semantics**: two separate `add_edge("frames", "render")`
  / `add_edge("book_pass", "render")` calls do NOT wait for both —
  each triggers `render` independently (OR semantics), so `render` ran
  before `book_pass` had populated `state["chapters"]`, a real `KeyError`
  caught immediately by the existing test suite. Fixed with LangGraph's
  list-based join syntax: `add_edge(["frames", "book_pass"], "render")`.
- **Wall-clock assertions on the full graph are flaky**: a first attempt at
  proving concurrency via total `run_book()` wall-clock time was
  consistently ~1.9s against a ~1.2s parallel-case prediction — not because
  parallelism was broken (a direct instrumented trace confirmed `frames`
  and `topics` start within 1ms of each other and both proceed
  concurrently in separate `ThreadPoolExecutor` threads) but because a real
  `SqliteSaver` checkpointer does real disk I/O per superstep, adding
  variable overhead unrelated to branch overlap. Rewrote the test to assert
  on each branch's first-call start-time gap instead (robust to that
  overhead) rather than total wall-clock.
- **`get_progress()`'s multi-pending-node handling**: with two nodes
  (`frames`, `topics`) able to be simultaneously "next", the old
  `node_order[:node_order.index(current_node)]` logic (which assumed
  exactly one pending node) would have mis-set `current_node` and
  mis-sliced `completed_nodes` non-deterministically depending on
  `snapshot.next`'s tuple order. Fixed by sorting `next_nodes` by
  `node_order` position and slicing `completed_nodes` at the *minimum*
  pending index. Empirically verified (real `InMemorySaver` runs, not fake
  snapshots) both for the case LangGraph actually exhibits — each parallel
  task's checkpoint write commits independently, not superstep-atomically
  — and for a real crash mid-run.
- **Known display-accuracy limitation, documented, not fixed**: if the
  higher-`node_order`-index branch (`topics`) finishes before the
  lower-index one (`frames`) — the reverse of the position-based boundary
  assumption — `topics` is under-reported as not-yet-completed (and
  `percent` undercounts by one node's worth) until `frames` also finishes.
  Verified this doesn't affect pipeline correctness (`render`'s join edge
  still genuinely waits for both) — it's a progress-display trade-off,
  acceptable for the "elapsed + percent, no ETA" scope the user explicitly
  chose over a real predictive ETA.
- **Backend needed zero code changes**: `/events`' `_progress_events`
  already spread whatever dict `ai_llm_get_progress` returned straight into
  the SSE payload — adding `percent`/`elapsed_seconds` to that dict was
  enough for them to flow through automatically. Verified end-to-end via
  backend's existing real-pipeline SSE test
  (`tests/integration/test_books_events_real_pipeline.py`), which exercises
  the real (now-parallel) graph behind a real uvicorn server + real SSE
  client — its `indices == sorted(indices)` node-order-never-regresses
  assertion still holds under parallel execution because `current_node` is
  always derived as the *minimum* pending index, which is monotonically
  non-decreasing by construction regardless of which branch finishes first.

## Out of scope (explicitly declined)

- A predictive ETA (elapsed + percent only, per the operator's explicit
  choice over a real ETA — SCALE_REPORT.md's real per-phase rates would be
  the input if this is revisited later)
- Splitting the frames phase itself into concurrent sub-ranges within one
  chunk (discussed as a further lever, not requested/implemented this
  sprint)
- Reducing the LLM chain's 3 sequential calls (topics → write → judge) —
  would trade away the quality/verify guarantee in root `AGENTS.md`

## Dependencies

- Builds on sprints/v4 (frames/screenshots), v7 Task 3-4 (optional
  `checkpointer` param, `get_progress` itself), and backend v7/v9
  (`/events` SSE endpoint, per-chapter progress) — no new dependency on
  either.
