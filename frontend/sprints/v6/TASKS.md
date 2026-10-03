# Sprint v6 — Tasks

## Status: Done

- [x] Task 1: Cancel click reveals an inline confirmation instead of calling the API (P0)
  - Acceptance: clicking `book-detail-cancel` sets local state and swaps the
    button for a confirmation row (`data-testid="book-detail-cancel-confirm"`)
    containing "Yes, cancel" (`book-detail-cancel-confirm-yes`) and
    "Never mind" (`book-detail-cancel-confirm-no`) buttons; `cancelBook()` is
    NOT called on this click; the original `book-detail-cancel` button is not
    rendered while the confirmation is showing.
  - Files: src/components/BookDetailScreen.tsx
  - Completed: 2026-09-25 — Added `isConfirmingCancel` state; the plain
    Cancel button now only calls `setIsConfirmingCancel(true)`, and the
    confirmation row renders in its place via a ternary (never both at
    once).
- [x] Task 2: Wire "Yes, cancel" / "Never mind" (P0)
  - Acceptance: "Never mind" hides the confirmation and restores the plain
    `book-detail-cancel` button with no network call made; "Yes, cancel"
    calls `cancelBook()` (the same logic the old single-click handler ran),
    updates the book to its returned failed/cancelled state, and stops
    polling — identical end result to sprint v2's original one-click
    behavior.
  - Files: src/components/BookDetailScreen.tsx
  - Completed: 2026-09-25 — Renamed the old `handleCancel` to
    `handleCancelConfirm` (unchanged body, plus `setIsConfirmingCancel(false)`
    on success); "Never mind" is a plain inline
    `() => setIsConfirmingCancel(false)`, no API call.
- [x] Task 3: Update + extend E2E coverage for the confirm step (P0)
  - Acceptance: `tests/e2e/book-detail-cancel.spec.ts`'s existing
    "cancel button appears... and transitions to the failed state" test is
    updated to click through the confirm step (click Cancel, then
    "Yes, cancel") before asserting the failed state; a new test confirms
    clicking "Never mind" dismisses the confirmation, leaves the book
    untouched (no `POST /cancel` call observed), and the plain Cancel button
    is clickable again afterward.
  - Files: tests/e2e/book-detail-cancel.spec.ts
  - Completed: 2026-09-25 — Updated the existing test to assert the
    confirmation appears with no API call yet, *then* click "Yes, cancel"
    before asserting the failed state. Added a new "Never mind" test that
    also re-opens the confirmation afterward to prove the plain button still
    works post-dismissal. Full e2e suite: 33/33 passed.
- [x] Task 4: Style the confirm row with existing design tokens (P1)
  - Acceptance: the confirmation row reuses the same
    surface/spacing/typography/error-color classes already used by the
    Cancel button and the failed-state card (no new colors or one-off
    values); reviewed via a screenshot in `tests/screenshots/`; Task 1-3
    tests still pass unmodified.
  - Files: src/components/BookDetailScreen.tsx
  - Completed: 2026-09-25 — First draft used `bg-error` (a solid dark-red
    fill) paired with `text-on-error-container` (a dark-red text color meant
    to sit on the *light* `error-container` background) — caught before
    screenshotting by checking how `bg-error` is used elsewhere in this
    codebase (nowhere, as a text pairing) and finding the actual established
    convention (`bg-error-container` + `text-on-error-container`, used by
    `ProgressView`'s badges, `MyBooksScreen`'s status badge, and the
    original single-step Cancel button). Switched "Yes, cancel" to
    `bg-error-container hover:bg-error-container/70` (same pairing, just
    more solid than the original button's `/40` alpha) and "Never mind" to
    the neutral `bg-surface-container` already used by `OutlineEditor`'s
    toggle buttons. Screenshot:
    `tests/screenshots/v6-task4-01-cancel-confirm.png`. Tasks 1-3 tests
    re-verified passing.
- [x] Task 5: Mobile responsiveness for the confirm row at 375px (P2)
  - Acceptance: `tests/e2e/responsive.spec.ts`'s existing walk is extended so
    the mobile in-flight book also clicks Cancel to reveal the confirm row,
    asserting no horizontal scroll and full viewport visibility for both
    confirm buttons; any overflow found is fixed in
    `BookDetailScreen.tsx`'s Tailwind classes.
  - Files: tests/e2e/responsive.spec.ts, src/components/BookDetailScreen.tsx
    (layout fixes as needed)
  - Completed: 2026-09-25 — Extended the existing v2 book-detail-metadata
    mobile section: click Cancel, assert the confirm row and both buttons
    are fully in-viewport, screenshot, then "Never mind" to restore state
    before the walk continues. Passed on the first run — no overflow, no
    layout fixes needed (the row's existing `flex-wrap` handles it).
    Screenshot: `tests/screenshots/v6-task5-01-cancel-confirm-mobile.png`.
    Full e2e suite: 33/33 passed. `tsc --noEmit`: clean.
