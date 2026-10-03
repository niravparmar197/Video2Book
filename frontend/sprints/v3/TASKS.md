# Sprint v3 — Tasks

## Status: Done

- [x] Task 1: Extend `ProgressEvent` with a `chapters` field (P0)
  - Acceptance: `src/types.ts` gains a new `ChapterProgress` interface
    (`id: string`, `title: string`, `status: 'pending' | 'done'`,
    `score: number | null`, `attempts: number | null`, `passed: boolean | null`);
    `ProgressEvent` gains `chapters: ChapterProgress[]`; `tsc --noEmit` clean.
  - Files: src/types.ts
  - Completed: 2026-09-25 — Added `ChapterProgress` and the `chapters` field exactly
    per spec. `streamEvents()` in `src/lib/api.ts` needed no change, as expected (it
    already passes parsed JSON straight through). `tsc --noEmit`: clean.
- [x] Task 2: `ProgressView` renders a per-chapter status list (P0)
  - Acceptance: when `progress.chapters` is non-empty, a list renders below the
    existing current-node card, one row per chapter (`data-testid="progress-chapter-{id}"`)
    showing its title and a done/pending status icon; when `chapters` is empty or
    absent (book still in `plan`/`fetch`/`transcribe`), the screen renders exactly as
    it does today — no empty list container, no layout shift.
  - Files: src/components/ProgressView.tsx
  - Completed: 2026-09-25 — Added a `ChapterRow` component and a
    `data-testid="progress-chapters"` list, gated on `progress.chapters &&
    progress.chapters.length > 0` — guards against `chapters` being `undefined` at
    runtime too, since older/mocked SSE payloads (e.g. `progress-view.spec.ts`'s
    existing fixtures) omit the field entirely despite the now-required TS type.
    Status icon is `check_circle` (done, secondary color) vs.
    `radio_button_unchecked` (pending, on-surface-variant), matching
    `OutlineEditor`/`MyBooksScreen`'s existing icon conventions.
- [x] Task 3: Show pass/fail outcome and refine-attempt count for done chapters (P0)
  - Acceptance: a `done` chapter row shows its `score` and a pass/fail indicator
    (`data-testid="progress-chapter-outcome-{id}"`) driven by `passed`, plus a visibly
    distinct badge (`data-testid="progress-chapter-attempts-{id}"`) when
    `attempts > 1`; a `pending` chapter shows neither (score/attempts are `null` until
    the chapter finishes).
  - Files: src/components/ProgressView.tsx
  - Completed: 2026-09-25 — Outcome badge reuses the secondary-container
    (passed)/error-container (not passed) pill styling `MyBooksScreen` already uses
    for status badges; attempts badge only renders when `attempts !== null &&
    attempts > 1`, using the neutral `bg-surface-container` pill. Guarded on
    `chapter.score !== null` (not just `status === 'done'`) as defense against a
    theoretically inconsistent payload.
- [x] Task 4: E2E coverage for the chapter progress list (P0)
  - Acceptance: new `tests/e2e/progress-chapters.spec.ts` covers (a) a mixed set of
    pending/done-passed/done-passed-with-multiple-attempts chapters rendering
    correctly from a mocked SSE `progress` event, and (b) an early progress event with
    `chapters: []` (or the field omitted) rendering the pre-v3 layout with no chapter
    list and no crash; existing `progress-view.spec.ts` assertions
    (`progress-current-node`, `progress-completed-nodes`) keep passing unmodified.
  - Files: tests/e2e/progress-chapters.spec.ts
  - Completed: 2026-09-25 — 3 tests: mixed pending/passed/multi-attempt chapters;
    a done-but-not-passed chapter ("Needs review" outcome + attempts badge); and a
    pre-outline event with no `chapters` key at all (mirrors real early-phase
    payloads and `progress-view.spec.ts`'s existing fixtures) asserting
    `progress-chapters` stays hidden and nothing crashes. Full e2e suite: 24/24
    passed, including the pre-existing `progress-view.spec.ts` tests unmodified.
- [x] Task 5: Style the chapter list with existing design tokens (P1)
  - Acceptance: the chapter list reuses the same surface/spacing/typography/status-color
    classes already used by `OutlineEditor`'s chapter cards and `MyBooksScreen`'s status
    badges (no new colors or one-off values); reviewed via a screenshot in
    `tests/screenshots/`; Task 2-4 tests still pass unmodified.
  - Files: src/components/ProgressView.tsx
  - Completed: 2026-09-25 — Screenshot review of both the passed and needs-review
    states (`tests/screenshots/v3-task4-01-chapter-progress.png`,
    `v3-task5-01-chapter-needs-review.png`) confirmed correct spacing/tokens on the
    first pass this time (learned from sprint v2 Task 7's invented-class bug: only
    used classes already defined in `src/index.css` or real Tailwind defaults, e.g.
    `gap-1.5`, not a plausible-looking custom-token variant). No fixes needed;
    Tasks 2-4 tests re-verified passing.
- [x] Task 6: Mobile responsiveness for the chapter list at 375px (P2)
  - Acceptance: `tests/e2e/responsive.spec.ts`'s existing walk is extended to include a
    rendering-status book with several chapters (including a long title and a
    multi-attempt badge), asserting no horizontal scroll and full viewport visibility
    for the chapter list and its rows; any overflow found is fixed in
    `ProgressView.tsx`'s Tailwind classes.
  - Files: tests/e2e/responsive.spec.ts, src/components/ProgressView.tsx (layout fixes
    as needed)
  - Completed: 2026-09-25 — Extended the walk with a new book/SSE mock carrying a
    long chapter title, a passed+multi-attempt chapter, and a pending chapter;
    asserted no horizontal scroll and full-viewport visibility for
    `progress-chapters`/individual chapter rows/outcome/attempts badges. Passed on
    the first run — the existing `truncate`/`flex-wrap`/`shrink-0` classes from
    Tasks 2-3 already handled it, no layout fixes needed. Screenshot:
    `tests/screenshots/v3-task6-01-chapter-progress-mobile.png`. Full e2e suite:
    24/24 passed. `tsc --noEmit`: clean.
