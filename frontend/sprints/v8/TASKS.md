# Sprint v8 — Tasks

## Status: Done

- [x] Task 1: Add filter persistence helpers to `src/lib/myBooks.ts` (P0)
  - Acceptance: `getSavedFilter(): FilterKey` reads a dedicated `localStorage`
    key and returns the stored value only if it's one of the four known
    filter keys (`'all' | 'in_progress' | 'done' | 'failed'`), otherwise
    `'all'`; `setSavedFilter(key: FilterKey): void` writes it; both wrapped
    in `try`/`catch` so a blocked/unavailable `localStorage` degrades to
    `'all'`/a no-op instead of throwing, matching this file's existing
    `getTrackedBookIds()`/`addTrackedBookId()` pattern.
  - Files: src/lib/myBooks.ts
  - Completed: 2026-09-25 — Added `FilterKey` (moved here from
    `MyBooksScreen.tsx`, now the single source of truth for the type),
    `getSavedFilter()`, and `setSavedFilter()` under a new
    `v2b_my_books_filter` key. Validation checks the raw stored string
    against `KNOWN_FILTER_KEYS` rather than trusting it, so a stale/garbage
    value can never leak into `matchesFilter()`'s status comparisons.
- [x] Task 2: Wire `MyBooksScreen` to read and write the saved filter (P0)
  - Acceptance: the `filter` state initializes from `getSavedFilter()`
    instead of a hardcoded `'all'`; every filter-tab click (the existing
    `onClick` handler) also calls `setSavedFilter(key)`; the tabs' testids,
    labels, and counts are unchanged from v4.
  - Files: src/components/MyBooksScreen.tsx
  - Completed: 2026-09-25 — `useState<FilterKey>(() => getSavedFilter())`
    (lazy initializer, so the `localStorage` read only happens once on
    mount, not every render); the tab `onClick` now calls both `setFilter`
    and `setSavedFilter`. Removed the local `FilterKey` type definition in
    favor of importing it from `myBooks.ts`. No changes to `FILTERS`,
    testids, labels, or count logic.
- [x] Task 3: E2E coverage for persistence and graceful fallback (P0)
  - Acceptance: new `tests/e2e/my-books-filter-persistence.spec.ts` covers
    (a) selecting a non-default filter, reloading the page, and seeing that
    filter still selected and its books shown, (b) a fresh session with
    nothing stored still defaults to `All`, and (c) a corrupted/unrecognized
    stored value (e.g. an arbitrary string written directly via
    `localStorage`) falls back to `All` without crashing the screen;
    existing `my-books-filter.spec.ts` assertions keep passing unmodified.
  - Files: tests/e2e/my-books-filter-persistence.spec.ts
  - Completed: 2026-09-25 — 3 tests, all passing on the first run: reload
    persistence (asserting both `aria-pressed` state and the actually
    filtered rows survive the reload), fresh-session default, and a
    directly-injected garbage `localStorage` value falling back cleanly.
    Full e2e suite: 39/39 passed, including pre-existing
    `my-books-filter.spec.ts`/`my-books.spec.ts` unmodified. `tsc --noEmit`:
    clean.
