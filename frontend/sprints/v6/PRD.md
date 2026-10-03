# Sprint v6 — PRD: Confirm Before Cancel

## Overview
Sprint v2's cancel button calls `POST /books/{id}/cancel` the instant it's
clicked — one misclick on a phone, one accidental tap while scrolling, and an
in-flight book (possibly hours into a long playlist) is killed with no way
back. This sprint adds a lightweight, inline confirmation step so cancelling
is a deliberate two-tap action instead of a single accidental one.

## Goals
- Clicking `book-detail-cancel` no longer calls the API immediately — it
  reveals an inline "Cancel this book?" confirmation with a "Yes, cancel" and
  a "Never mind" action.
- "Never mind" dismisses the confirmation and returns to the plain Cancel
  button, with no API call made.
- "Yes, cancel" does exactly what today's single click does: calls
  `POST /books/{id}/cancel`, updates the book to its failed/cancelled state,
  and stops polling — unchanged backend contract, unchanged end result.
- No native browser `confirm()`/`alert()` dialog — an inline, styled affordance
  that's stylable, testable, and doesn't block the event loop the way a
  browser-native modal does.

## User Stories
- As a user who taps Cancel by mistake, I want a chance to back out before
  the book is actually cancelled, so a misclick doesn't cost me hours of
  rendering progress.
- As a user who genuinely wants to cancel, I want the confirmation to be a
  single extra tap, not a detour to a separate screen or dialog.

## Technical Architecture
- **Frontend only** — no backend changes. `POST /books/{id}/cancel`'s
  contract (sprint v2) is unchanged; this sprint only gates *when* the
  frontend calls it.
- Confirmation state lives entirely in `BookDetailScreen`'s existing
  component state (a new `isConfirmingCancel` boolean) — no new endpoint, no
  new persisted preference.

```
BookDetailScreen (in-flight book: queued/planning/outline_ready/rendering)

  [Cancel]                                   <- default state (unchanged testid)
     | click
     v
  "Cancel this book?"  [Yes, cancel]  [Never mind]     <- NEW inline confirm
     |                        |
     | click "Never mind"     | click "Yes, cancel"
     v                        v
  back to [Cancel]      POST /books/{id}/cancel   (unchanged from v2)
  (no API call)               |
                               v
                         failed / "Cancelled by user"  (unchanged from v2)
```

## Out of Scope
- A native `window.confirm()` dialog — deliberately avoided (untestable via
  Playwright's normal locator API, blocks the page, unstylable, and this
  project's own automation guidance already avoids triggering browser-native
  dialogs).
- A "don't ask me again" preference or any persisted setting.
- Confirmation on any other destructive-ish action (retry, download) — this
  sprint is scoped to cancel only, the one action with no undo.
- Any change to what happens after confirmation — the actual cancel flow
  (API call, resulting UI state) is sprint v2's, unchanged.

## Dependencies
- Sprint v2 shipped `cancelBook()` (`src/lib/api.ts`), the
  `book-detail-cancel` button, and `CANCELLABLE_STATUSES`
  (`src/components/BookDetailScreen.tsx`) this sprint builds the confirm
  step on top of.
