# Sprint v4 — Tasks

## Status: Done

- [x] Task 1: Sort My Books newest-first by `created_at` (P0)
  - Acceptance: the fetched `books` array is sorted by `created_at` descending
    before rendering (a book with an empty/invalid `created_at`, e.g. the
    existing not-found fallback, sorts last rather than throwing or sorting
    first); row order in the DOM reflects this regardless of tracked-id
    fetch order.
  - Files: src/components/MyBooksScreen.tsx
  - Completed: 2026-09-25 — Added `sortByCreatedAtDesc()`, applied via
    `useMemo` before rendering. Invalid/empty dates (`Date.parse` → `NaN`)
    sort last rather than crashing or floating to the top; two invalid dates
    are left in their existing relative order (stable no-op comparison).
- [x] Task 2: Status filter tabs — All / In Progress / Done / Failed (P0)
  - Acceptance: a row of filter tabs renders above the book list
    (`data-testid="my-books-filter-all"`, `-in-progress`, `-done`, `-failed`),
    each showing a count of matching books; `All` is selected by default;
    clicking a tab shows only books whose status matches (`In Progress` =
    `queued`/`planning`/`outline_ready`/`rendering`, same grouping as
    `BookDetailScreen`'s cancel button); the active tab is visually distinct
    (`aria-pressed` or equivalent for a11y).
  - Files: src/components/MyBooksScreen.tsx
  - Completed: 2026-09-25 — Added a `FILTERS` config array (key/label/testId/
    emptyLabel) and `matchesFilter()`, reusing the exact `IN_PROGRESS_STATUSES`
    grouping `BookDetailScreen`'s `CANCELLABLE_STATUSES` already established
    in sprint v2. Active tab uses `aria-pressed` plus a filled
    `bg-primary-container` style; inactive tabs use the neutral
    `bg-surface-container` pill already used elsewhere in this screen.
- [x] Task 3: Filter-aware empty state (P0)
  - Acceptance: when a filter's matching set is empty but the user has
    tracked books overall, a distinct empty message renders
    (`data-testid="my-books-filter-empty"`, e.g. "No failed books") instead
    of the existing "no books at all" `my-books-empty` state, which stays
    reserved for zero tracked books.
  - Files: src/components/MyBooksScreen.tsx
  - Completed: 2026-09-25 — Reuses the existing `StateMessage` `empty` variant
    with a per-filter message driven by `FILTERS`' `emptyLabel`
    ("No failed books.", etc.); `all` never hits this path since `books.length
    === 0` is already handled earlier by the pre-existing `my-books-empty`
    check.
- [x] Task 4: E2E coverage for sort + filter (P0)
  - Acceptance: new `tests/e2e/my-books-filter.spec.ts` covers (a) three
    tracked books with out-of-order `created_at` values rendering newest-first,
    (b) each filter tab narrowing to the right subset with correct counts,
    and (c) the filter-empty state when a tab's subset is empty; existing
    `my-books.spec.ts`/`my-books-metadata.spec.ts` assertions keep passing
    unmodified.
  - Files: tests/e2e/my-books-filter.spec.ts
  - Completed: 2026-09-25 — 4 tests: newest-first sort order, invalid-date
    sorts last, all four filter tabs with count assertions plus row
    visibility per tab, and the filter-empty state (asserting
    `my-books-empty` stays absent so the two empty states are never
    confused). Full e2e suite: 28/28 passed, including pre-existing
    `my-books.spec.ts`/`my-books-metadata.spec.ts` unmodified.
- [x] Task 5: Style the filter tabs with existing design tokens (P1)
  - Acceptance: tabs reuse the same pill/badge and typography classes already
    used by `MyBooksScreen`'s own status badges and `OutlineEditor`'s toggle
    buttons (no new colors or one-off values); reviewed via a screenshot in
    `tests/screenshots/`; Task 1-4 tests still pass unmodified.
  - Files: src/components/MyBooksScreen.tsx
  - Completed: 2026-09-25 — Screenshot review
    (`tests/screenshots/v4-task4-01-filter-in-progress.png`,
    `v4-task4-02-filter-empty.png`) confirmed correct token reuse and spacing
    on the first pass — no invented classes, no fixes needed. Tasks 1-4 tests
    re-verified passing.
- [x] Task 6: Mobile responsiveness for the filter tabs at 375px (P2)
  - Acceptance: `tests/e2e/responsive.spec.ts`'s existing walk is extended to
    visit My Books with several tracked books and click through the filter
    tabs, asserting no horizontal scroll and full viewport visibility for
    each tab; any overflow found is fixed in `MyBooksScreen.tsx`'s Tailwind
    classes.
  - Files: tests/e2e/responsive.spec.ts, src/components/MyBooksScreen.tsx
    (layout fixes as needed)
  - Completed: 2026-09-25 — Found and fixed a real overflow: the filter row
    used `overflow-x-auto` (horizontal scroll within its own container), so
    the last tab's bounding box sat outside the 375px viewport even though
    the page itself never grew a scrollbar — `assertFullyInViewport` caught
    it, `assertNoHorizontalScroll` would not have. Switched to `flex-wrap`,
    which wraps the four tabs onto two rows on narrow screens instead.
    Verified via `tests/screenshots/v4-task6-01-my-books-filter-mobile.png`.
    Full e2e suite: 28/28 passed. `tsc --noEmit`: clean.
