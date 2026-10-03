# Sprint v7 — Tasks

## Status: Done

- [x] Task 1: Distinguish a genuine stream error from a clean end or an intentional abort (P0)
  - Acceptance: `ProgressView`'s SSE wiring reacts to how the `streamEvents(...)`
    promise settles: a clean resolve triggers nothing new (unchanged
    behavior); a rejection whose `name` is `'AbortError'` (unmount or
    `bookId` change calling `controller.abort()`) triggers nothing new
    either; any other rejection (e.g. the `ApiError` `streamEvents` throws on
    a non-2xx response, or a real network failure) is the only case that
    schedules a reconnect (Task 3) — `progress`/chapter state is left
    untouched in all three cases, never reset to `null`.
  - Files: src/components/ProgressView.tsx
  - Completed: 2026-09-25 — Wrapped the SSE lifecycle in a local `connect()`
    function so it can be re-invoked; its `.catch` checks `isAbortError(err)`
    (checks `err.name === 'AbortError'`) and an `isActive` flag before doing
    anything, so unmount/bookId-change never schedules a reconnect. `progress`
    state is never cleared anywhere in the new logic — only ever replaced by
    a newer value from `onProgress`.
- [x] Task 2: "Reconnecting..." indicator (P0)
  - Acceptance: while a reconnect is pending or in flight,
    `data-testid="progress-reconnecting"` renders — as the existing loading
    `StateMessage`'s text (replacing "Connecting...") if no `progress` has
    ever been received yet, or as a small banner above the current-node card
    once `progress` data exists, so the current-node card, chapter summary,
    and chapter list all keep rendering their last-known state unchanged; the
    indicator disappears the instant a new `progress` event arrives.
  - Files: src/components/ProgressView.tsx
  - Completed: 2026-09-25 — Added `isReconnecting` state, cleared to `false`
    inside the `onProgress` callback itself (so it clears the instant real
    data arrives, not on a separate effect). Two render paths share the
    testid: `StateMessage`'s `testId` prop when `!progress`, and a standalone
    banner div (reusing `bg-surface-container`/`text-on-surface-variant`,
    the same tokens `MyBooksScreen`'s inactive filter tabs and `ChapterRow`'s
    attempts badge already use) above the current-node card when `progress`
    already exists.
- [x] Task 3: Automatic retry loop (P0)
  - Acceptance: after a fixed `RECONNECT_DELAY_MS`, the stream is reopened
    automatically via a fresh `AbortController`; if that attempt also fails
    (per Task 1's rules), the cycle repeats with the indicator still showing;
    the retry loop stops immediately and cleanly on unmount or when `bookId`
    changes (no dangling timers, no reconnect attempt after cleanup).
  - Files: src/components/ProgressView.tsx
  - Completed: 2026-09-25 — `RECONNECT_DELAY_MS = 2000`. Cleanup sets
    `isActive = false`, aborts the current `controller`, and clears any
    pending `reconnectTimer` — all three read by the recursive `connect()`
    closure, so a reconnect already scheduled at unmount time never fires.
- [x] Task 4: E2E coverage for reconnect behavior (P0)
  - Acceptance: new `tests/e2e/progress-reconnect.spec.ts` covers (a) the
    `/events` route failing once (e.g. a 502) then succeeding on retry,
    asserting `progress-reconnecting` appears and then disappears once real
    progress renders, and (b) today's existing pattern — a mocked SSE body
    that ends cleanly with no terminal event — does NOT show
    `progress-reconnecting` and does NOT trigger a second request to
    `/events`; existing `progress-view.spec.ts`, `progress-chapters.spec.ts`,
    and `progress-chapters-summary.spec.ts` suites keep passing unmodified.
  - Files: tests/e2e/progress-reconnect.spec.ts
  - Completed: 2026-09-25 — 3 tests: (1) a 502-then-success reconnect cycle,
    including a test-assertion bug caught along the way (`toHaveText` on the
    `StateMessage` container failed because its icon renders as a ligature
    that's part of the element's text content — same caveat the component's
    own doc comment already warns about; fixed by switching to
    `toContainText`); (2) a genuine network-level failure via
    `route.abort('connectionreset')`, distinct from the first test's
    non-2xx `ApiError` path, proving both rejection shapes are treated the
    same way; (3) the existing "clean end, no terminal event" pattern proven
    inert — no `progress-reconnecting`, exactly one request observed after
    waiting past `RECONNECT_DELAY_MS`. All 9 pre-existing progress-related
    tests (`progress-view`, `progress-chapters`, `progress-chapters-summary`)
    re-verified passing unmodified, confirming the PRD's core
    backward-compatibility constraint held. Full e2e suite: 36/36 passed.
  - Known limitation (honest, not solved): a *mid-stream* drop — a
    connection that was already delivering live progress and then genuinely
    fails — isn't independently exercised by an E2E test. Playwright's
    `route.fulfill` can only serve a static body that always ends cleanly
    (never errors partway through), so every test that wants a genuine
    failure has to fail *before* delivering any data. The component's logic
    for that case (the banner rendering above already-visible progress,
    rather than replacing the `StateMessage`) is implemented and type-checks,
    reviewed against existing tokens (Task 5), but only verified by code
    review, not an automated screenshot or assertion.
- [x] Task 5: Style the reconnect indicator with existing design tokens (P1)
  - Acceptance: the indicator reuses the same surface/spacing/typography
    classes already used elsewhere in `ProgressView` (no new colors or
    one-off values); reviewed via a screenshot in `tests/screenshots/`;
    Task 1-4 tests still pass unmodified.
  - Files: src/components/ProgressView.tsx
  - Completed: 2026-09-25 — Screenshot review
    (`tests/screenshots/v7-task5-01-reconnecting-pre-progress.png`) confirmed
    the pre-first-progress state renders identically to the existing
    "Connecting..." state (same `StateMessage` component, just different
    text) — no fixes needed. The progress-already-visible banner path
    couldn't be screenshotted via the E2E harness (see Task 4's documented
    limitation) but was checked by reading the applied classes against their
    existing uses elsewhere in this file. Tasks 1-4 tests re-verified
    passing.
- [x] Task 6: Mobile responsiveness for the indicator at 375px (P2)
  - Acceptance: `tests/e2e/responsive.spec.ts`'s existing walk is extended so
    the mobile chapter-progress book also exercises a reconnect (route fails
    once, then succeeds), asserting no horizontal scroll and full viewport
    visibility for `progress-reconnecting` while it's shown; any overflow
    found is fixed in `ProgressView.tsx`'s Tailwind classes.
  - Files: tests/e2e/responsive.spec.ts, src/components/ProgressView.tsx
    (layout fixes as needed)
  - Completed: 2026-09-25 — Added a new mobile book/events mock that fails
    once (502) then succeeds, asserting `progress-reconnecting` is fully in
    viewport with no horizontal scroll before it clears. Passed on the first
    run — no overflow, no layout fixes needed. Screenshot:
    `tests/screenshots/v7-task6-01-reconnecting-mobile.png`. Full e2e suite:
    36/36 passed. `tsc --noEmit`: clean.
