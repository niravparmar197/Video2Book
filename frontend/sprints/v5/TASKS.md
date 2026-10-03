# Sprint v5 — Tasks

## Status: Done

- [x] Task 1: Render an "N of M chapters done" count (P0)
  - Acceptance: when `progress.chapters` is non-empty, a summary element
    (`data-testid="progress-chapters-count"`) renders between the
    current-node card and the per-chapter list showing `"{done} of {total}
    chapters done"`, where `done` counts chapters with `status === 'done'`;
    absent/hidden when `chapters` is empty or missing, same guard as v3's
    chapter list.
  - Files: src/components/ProgressView.tsx
  - Completed: 2026-09-25 — Added a `ChapterSummary` component, gated on the
    same `progress.chapters && progress.chapters.length > 0` guard v3's
    chapter list already uses, so the pre-outline case needs no new
    condition to stay correct.
- [x] Task 2: Visual progress bar for chapter completion (P0)
  - Acceptance: a progress bar (`data-testid="progress-chapters-bar"`) renders
    next to/below the count, its filled width proportional to `done / total`
    (0% before any chapter finishes, 100% once every chapter is `done`); no
    division-by-zero or NaN width when `total` is 0 (can't happen once the
    non-empty guard from Task 1 applies, but the calculation itself is
    guarded defensively).
  - Files: src/components/ProgressView.tsx
  - Completed: 2026-09-25 — `percent = total > 0 ? Math.round((done / total)
    * 100) : 0` guards the div-by-zero case defensively even though the
    render guard already makes `total === 0` unreachable. Track/fill use
    `role="progressbar"` + `aria-valuenow`/`-min`/`-max` for a11y; fill width
    set via inline `style` on a dedicated `progress-chapters-bar-fill` node
    (kept separate from the `role="progressbar"` container itself, since
    `toHaveCSS('width', ...)` resolves to a computed pixel value, not the
    percentage — inline `style` attribute is the stable thing to assert on).
- [x] Task 3: "Needs review" count when a finished chapter didn't pass (P0)
  - Acceptance: when one or more chapters have `status === 'done' && passed
    === false`, a distinct callout (`data-testid="progress-chapters-needs-review"`)
    shows the count (e.g. "2 need review"); absent entirely when every
    finished chapter passed or none have finished yet.
  - Files: src/components/ProgressView.tsx
  - Completed: 2026-09-25 — Singular/plural handled ("1 needs review" vs.
    "2 need review"); reuses the same `bg-error-container`/
    `text-on-error-container` pill styling as `ChapterRow`'s own
    "Needs review" outcome badge (v3) and `MyBooksScreen`'s failed-status
    badge (v1/v2).
- [x] Task 4: E2E coverage for the chapter summary (P0)
  - Acceptance: new `tests/e2e/progress-chapters-summary.spec.ts` covers (a)
    a partially-done set showing the correct count and a partial-width bar,
    (b) an all-done, all-passed set showing 100% with no needs-review
    callout, (c) a set with a needs-review chapter showing the callout with
    the right count, and (d) the pre-outline case (no `chapters`) showing no
    summary at all; existing `progress-chapters.spec.ts` assertions keep
    passing unmodified.
  - Files: tests/e2e/progress-chapters-summary.spec.ts
  - Completed: 2026-09-25 — 4 tests, all passing. One test bug caught and
    fixed along the way: `toHaveCSS('width', /25/)` was asserting against
    Playwright's *computed* pixel width (e.g. "111.5px"), not the intended
    `25%` — switched to asserting the inline `style` attribute directly
    (`toHaveAttribute('style', /width:\s*25%/)`), which is what the
    component actually sets. Full e2e suite: 32/32 passed, including
    pre-existing `progress-chapters.spec.ts`/`progress-view.spec.ts`
    unmodified.
- [x] Task 5: Style the summary with existing design tokens (P1)
  - Acceptance: the count/bar/callout reuse the same surface/spacing/
    typography/status-color classes already used elsewhere in `ProgressView`
    and `MyBooksScreen` (no new colors or one-off values); reviewed via a
    screenshot in `tests/screenshots/`; Task 1-4 tests still pass unmodified.
  - Files: src/components/ProgressView.tsx
  - Completed: 2026-09-25 — Screenshot review
    (`tests/screenshots/v5-task1-01-partial-summary.png`,
    `v5-task3-01-needs-review-summary.png`) confirmed correct token reuse,
    spacing, and bar proportions on the first pass — no fixes needed. Tasks
    1-4 tests re-verified passing.
- [x] Task 6: Mobile responsiveness for the summary at 375px (P2)
  - Acceptance: `tests/e2e/responsive.spec.ts`'s existing walk is extended so
    the mobile chapter-progress book also exercises the summary (count, bar,
    and a needs-review callout), asserting no horizontal scroll and full
    viewport visibility for each; any overflow found is fixed in
    `ProgressView.tsx`'s Tailwind classes.
  - Files: tests/e2e/responsive.spec.ts, src/components/ProgressView.tsx
    (layout fixes as needed)
  - Completed: 2026-09-25 — Added a third (done, not-passed) chapter to the
    existing mobile chapter-progress fixture so the walk now exercises the
    needs-review callout too, and asserted full-viewport visibility for
    `progress-chapters-count`/`-bar`/`-needs-review`. Passed on the first
    run — no overflow, no layout fixes needed. Screenshot re-captured at
    `tests/screenshots/v3-task6-01-chapter-progress-mobile.png` (same path
    as v3's, now showing the summary above the chapter list). Full e2e
    suite: 32/32 passed. `tsc --noEmit`: clean.
