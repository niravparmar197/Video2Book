# Sprint v10 — Tasks

## Status: Done

- [x] Task 1: Run `frames` and `topics`/write concurrently instead of sequentially (P0)
  - Acceptance: `build_video_graph()`/`build_topic_graph()` wire `frames`
    and `topics` as parallel branches off `chunk`, converging before
    `render` via a proper LangGraph join (`add_edge([...], "render")`, not
    two separate edges); unit test proves genuine concurrency (not just
    that the resulting state is correct, which sequential execution would
    also produce) by asserting each branch's first call starts within a
    small window of the other, not via total wall-clock time (found to be
    flaky against unrelated real SqliteSaver checkpoint I/O overhead); full
    existing suite (209 tests) stays green, proving zero behavior change
    to what gets written where
  - Files: app/graph.py, tests/unit/test_graph.py, tests/unit/test_graph_topic_order.py
  - Completed: 2026-09-25 — Both `build_video_graph()` and
    `build_topic_graph()` now have `chunk` fan out to `frames` and `topics`
    independently (`frames`/`topics` both return `{}` — no BookState keys —
    so there's no merge conflict and no data dependency between them),
    reconverging at `render` via `builder.add_edge(["frames", "book_pass"],
    "render")`. **Found and fixed a real bug immediately via the existing
    test suite**: two separate `add_edge("frames", "render")` /
    `add_edge("book_pass", "render")` calls do not wait for both (LangGraph
    OR semantics per-edge, not AND) — `render` ran the instant `frames`
    finished, before `book_pass` had populated `state["chapters"]`, a real
    `KeyError` on `render`. Fixed with the list-based join syntax. Proved
    genuine thread-level concurrency two ways: an instrumented manual
    trace (real `perf_counter()` + `threading.current_thread().name`
    logging) showing `frames` and `topics` starting within 1ms of each
    other in separate `ThreadPoolExecutor` threads and finishing together;
    and a permanent unit test per graph asserting the same start-time gap
    (`< 0.2s`) rather than total wall-clock, since a first total-wall-clock
    version of the test was flaky (~1.9s observed vs. a ~1.2s parallel
    prediction) due to real disk I/O from the default `SqliteSaver`
    checkpointer across the graph's now-larger number of supersteps —
    unrelated to whether the two branches actually overlapped, which the
    instrumented trace independently confirmed they did. 2 new tests
    (video-order, topic-order). 209/209 unit tests passing, bandit clean
    (0 issues, all severities/confidence).

- [x] Task 2: `get_progress()` gains `percent` and `elapsed_seconds` (P0)
  - Acceptance: `get_progress()` returns two new keys — `percent` (0-100,
    completed-node count / phase's total node count) and `elapsed_seconds`
    (wall time since the run's first checkpoint, frozen once the run
    reaches a terminal `next=()` state so it doesn't keep growing on a
    later poll) — alongside the existing `completed_nodes`/`current_node`/
    `next_nodes`/`step`; correctly handles `next_nodes` holding more than
    one entry now that `frames` runs in parallel (Task 1), deriving
    `current_node`/`completed_nodes` from the lowest-`node_order`-index
    pending node rather than naively from `next_nodes[0]`; unit tests cover
    the not-started/mid-run/full-run cases plus a dedicated case proving
    correct behavior when one parallel branch (`frames`) finishes while the
    other (`topics`) crashes
  - Files: app/graph.py, tests/unit/test_graph.py
  - Completed: 2026-09-25 — `_parse_checkpoint_dt()` handles LangGraph's
    ISO-8601 `created_at` strings; `started_at` comes from
    `graph.get_state_history(config)`'s earliest entry. `next_nodes` is now
    sorted by `node_order` position and `completed_nodes`'s boundary is the
    *minimum* index among currently-pending nodes, not `current_node`'s own
    index — behaviorally identical to the old logic whenever exactly one
    node is pending (every pre-v10 test), and correctly handles 2+ pending
    nodes without falling into the old code's undefined `next_nodes[0]`
    ordering dependence. **Empirically verified against real LangGraph
    behavior, not assumptions**: a real crash test (topics raises while
    frames has already succeeded) confirmed LangGraph commits each
    parallel task's checkpoint write independently, not
    superstep-atomically — `frames` correctly reports as completed even
    though its sibling `topics` failed in the same superstep. **Documented,
    not fixed, known limitation**: if `topics` (the higher-index branch)
    finishes before `frames` (the lower-index one) — the reverse of the
    position-based assumption — `topics` is under-reported as pending (and
    `percent` undercounts by one node) until `frames` also finishes;
    verified via a dedicated empirical test this never affects pipeline
    correctness (`render`'s join still genuinely waits for both), only
    progress-display accuracy, which is an accepted trade-off for the
    "elapsed + percent, no ETA" scope chosen over a real predictive ETA. 2
    existing exact-dict-equality tests updated for the 2 new keys; 3 new
    tests (percent assertion on the existing mid-run/full-run tests, plus
    the dedicated frames-done-topics-crashed case). 209/209 unit tests
    passing, bandit clean.

- [x] Task 3: Pass `percent`/`elapsed_seconds` through backend's `/events` (P0)
  - Acceptance: the SSE `progress` event payload includes `percent` and
    `elapsed_seconds`; backend's real-pipeline SSE integration test (real
    graph, real Postgres checkpointer, real uvicorn server, real SSE
    client) still passes against the now-parallel graph, including its
    node-order-never-regresses assertion
  - Files: (none — pure pass-through, see Completed note)
  - Completed: 2026-09-25 — Zero backend code changes needed:
    `_progress_events()` already spreads whatever dict
    `ai_llm_get_progress` returns straight into the SSE payload via
    `_sse("progress", progress)`, so Task 2's new keys flow through
    automatically. Verified two ways: backend's full test suite (128
    tests, including the mocked `test_books_events.py`) stays green
    unmodified, and specifically re-ran
    `tests/integration/test_books_events_real_pipeline.py` (the one test
    that exercises the *real* ai_llm graph, not a mock) to confirm the
    parallel graph change doesn't break its
    `indices == sorted(indices)` node-sequence-never-regresses assertion —
    holds because `current_node` is always derived as the *minimum*
    pending node_order index (Task 2), which is monotonically
    non-decreasing over time regardless of which parallel branch finishes
    first. 128/128 backend tests passing.

- [x] Task 4: Frontend — overall pipeline progress bar with live elapsed time (P0)
  - Acceptance: `ProgressEvent` gains `percent`/`elapsed_seconds`;
    `ProgressView` renders an overall progress bar (`percent`) distinct
    from the existing per-chapter completion bar, plus a live-ticking
    elapsed-time display; the elapsed display keeps advancing locally
    between SSE events (which only push on a real node/chapter change, per
    `_progress_events`' dedup) rather than freezing until the next event;
    E2E test proves both the initial rendered values and that the clock
    genuinely advances without a new SSE event arriving
  - Files: src/types.ts, src/components/ProgressView.tsx, tests/e2e/progress-view.spec.ts
  - Completed: 2026-09-25 — `OverallProgress` component (percent bar +
    percent text + elapsed text), separate from `ChapterSummary`'s
    per-chapter bar. A `useRef`-tracked `{elapsedSeconds, receivedAtMs}`
    plus a 1s `setInterval` extrapolates the displayed elapsed time forward
    between SSE events using real wall-clock time since the last event was
    received — necessary because the backend intentionally doesn't push a
    new event just because time passed (no-op ticks aren't sent). Defensive
    `?? 0` fallbacks for `percent`/`elapsed_seconds` since several other
    existing E2E tests' SSE mocks predate these fields and don't include
    them (untyped JSON route mocks, not caught by `tsc`). New test asserts
    the initial `44%` / `37s` render, then waits 2.1s with no further SSE
    event and asserts the displayed elapsed text actually changed — proving
    the local tick, not just the initial value. `tsc --noEmit` clean; full
    E2E suite 44/44 passing.

## Verification summary

- ai_llm: 209/209 unit tests passing, `bandit -r app/ -ll` clean (0
  issues, all severities/confidence)
- backend: 128/128 tests passing (including the real-pipeline SSE
  integration test against the now-parallel graph)
- frontend: 44/44 E2E tests passing, `tsc --noEmit` clean
- Net effect: for any video ≤ `CHUNK_MINUTES` (30 min), wall-clock time
  drops from roughly `frames_time + llm_chain_time + overhead` to roughly
  `max(frames_time, llm_chain_time) + overhead` — for the ~15-17 min
  estimate discussed with the operator for a 30-min video, this is the
  ~10 min figure; the operator's separately-raised "10-min video shouldn't
  take longer than expected" concern is the same root cause (fixed
  per-chunk cost regardless of video length under 30 min) and benefits the
  same relative amount.
- `semgrep` was unavailable in this environment (not installed) — not run
  for this sprint's frontend change; flagged rather than silently skipped.
