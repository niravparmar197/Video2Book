# Sprint v9 — Tasks

## Status: Done

- [x] Task 1: Search input above the book list (P0)
  - Acceptance: a text input (`data-testid="my-books-search-input"`) renders
    below the status filter tabs and above the book rows; typing into it
    updates local component state on every keystroke (plain controlled
    input, no debounce per the PRD); an empty value is the default and
    changes nothing about which rows render.
  - Files: src/components/MyBooksScreen.tsx
  - Completed: 2026-09-25 — Added `searchQuery` state and a controlled
    `type="search"` input, styled identically to `NewBookScreen`'s URL input.
- [x] Task 2: Narrow the status-filtered list by search text (P0)
  - Acceptance: the rows rendered are `filteredBooks` (v4's status-filtered,
    sorted list) further narrowed to books where `bookTitle(book)`,
    `book.url`, or `book.id` contains the search text as a case-insensitive
    substring; search and the status filter combine with AND (e.g. typing a
    term while `Done` is selected only searches within done books); filter
    tab counts are computed from status alone and do not change as the
    search text changes.
  - Files: src/components/MyBooksScreen.tsx
  - Completed: 2026-09-25 — Split the old single `filteredBooks` memo into
    `statusFilteredBooks` (status only, feeds both the tab counts and the
    next step) and `filteredBooks` (status + search, feeds the rendered
    rows) — this is what keeps the tab counts search-independent by
    construction rather than by a separate carve-out. Added `matchesSearch()`
    doing a trimmed, lower-cased substring check against all three fields.
- [x] Task 3: Search-specific empty state (P0)
  - Acceptance: when the search text is non-empty and zero books match,
    a distinct empty message renders (`data-testid="my-books-search-empty"`,
    e.g. `No books match "transformers".`) instead of v4's
    `my-books-filter-empty` message; v4's filter-empty state is still used
    when the search box is empty but the status filter alone has zero
    matches.
  - Files: src/components/MyBooksScreen.tsx
  - Completed: 2026-09-25 — Three-way branch: search-empty (when
    `searchQuery.trim()` is non-empty and `filteredBooks` is empty),
    filter-empty (v4's existing message, unchanged), or the row list.
- [x] Task 4: E2E coverage for search (P0)
  - Acceptance: new `tests/e2e/my-books-search.spec.ts` covers (a) typing a
    substring that matches a title narrows to just that row, (b) typing a
    substring that matches a URL or an id (not the title) still finds the
    book, (c) search combined with a status filter tab narrows to the
    intersection, and (d) a search with zero matches shows
    `my-books-search-empty` with the typed text in the message; existing
    `my-books-filter.spec.ts`/`my-books-filter-persistence.spec.ts`
    assertions keep passing unmodified.
  - Files: tests/e2e/my-books-search.spec.ts
  - Completed: 2026-09-25 — 4 tests, all passing on the first run, including
    an explicit assertion that filter tab counts stay unchanged
    ("All (2)"/"Done (1)") while a search narrows the visible rows. Full e2e
    suite: 43/43 passed, including pre-existing `my-books-filter.spec.ts`/
    `my-books-filter-persistence.spec.ts` unmodified.
- [x] Task 5: Style the search input with existing design tokens (P1)
  - Acceptance: the input reuses the same border/spacing/typography classes
    already used by other text inputs in this app (e.g. `NewBookScreen`'s
    URL input) rather than inventing new ones; reviewed via a screenshot in
    `tests/screenshots/`; Task 1-4 tests still pass unmodified.
  - Files: src/components/MyBooksScreen.tsx
  - Completed: 2026-09-25 — Screenshot review
    (`tests/screenshots/v9-task5-01-search-narrowed.png`,
    `v9-task5-02-search-empty.png`) confirmed correct token reuse (identical
    input styling to `NewBookScreen`, shared `StateMessage` empty variant)
    on the first pass — no fixes needed. Tasks 1-4 tests re-verified
    passing.
- [x] Task 6: Mobile responsiveness for the search input at 375px (P2)
  - Acceptance: `tests/e2e/responsive.spec.ts`'s existing walk is extended so
    the My Books section also types into the search input, asserting no
    horizontal scroll and full viewport visibility for the input and the
    resulting rows; any overflow found is fixed in
    `MyBooksScreen.tsx`'s Tailwind classes.
  - Files: tests/e2e/responsive.spec.ts, src/components/MyBooksScreen.tsx
    (layout fixes as needed)
  - Completed: 2026-09-25 — Extended the walk to type a search query
    narrowing the two mobile filter-tab fixture books down to one, asserting
    full-viewport visibility and no horizontal scroll. Passed on the first
    run — no overflow, no layout fixes needed. Screenshot:
    `tests/screenshots/v9-task6-01-search-mobile.png`. Full e2e suite:
    43/43 passed. `tsc --noEmit`: clean.
