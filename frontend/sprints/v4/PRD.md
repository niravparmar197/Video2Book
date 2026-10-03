# Sprint v4 — PRD: My Books Sort + Status Filter

## Overview
`MyBooksScreen` currently lists tracked books in whatever order
`getTrackedBookIds()` happens to return them (insertion order into
`localStorage`), with no way to tell in-flight books apart from finished ones
except by reading each row's status badge one at a time. Now that every book
carries a real `created_at` (sprint v2), this sprint sorts the list
newest-first and adds a status filter, so a user with several books in flight
can find the one they care about without scanning the whole list.

## Goals
- My Books always lists books newest-first by `created_at`, regardless of the
  order they were created/tracked in `localStorage`.
- A status filter (`All` / `In Progress` / `Done` / `Failed`) narrows the
  visible rows; `In Progress` bundles `queued`/`planning`/`outline_ready`/
  `rendering` (the same grouping `BookDetailScreen`'s cancel button already
  uses), matching how a user actually thinks about "is this one still going."
- `All` is the default filter on every visit — no filter choice persists
  across a reload, since this is a lightweight view control, not a saved
  preference.
- An empty filtered result (e.g. no `Failed` books) shows a filter-aware empty
  state, not the "no books at all" message that fires when nothing is
  tracked.

## User Stories
- As a user with several books in flight, I want the newest one at the top,
  so I don't have to hunt for the book I just started.
- As a user who only cares about a failed book right now, I want to filter
  down to just `Failed`, so I don't have to scan past everything that's fine.
- As a user, I want the count/order to make sense the moment I open My Books,
  so the screen doesn't feel like it's showing books in a random order.

## Technical Architecture
- **Frontend only** — no backend changes. Every field this sprint needs
  (`created_at`, `status`) is already returned by `GET /books/{id}` (sprint
  v2) and already fetched by `MyBooksScreen` for every tracked id.
- Sorting and filtering both happen client-side, in memory, after the
  existing `Promise.all(ids.map(getBook))` fetch — no new endpoint, no new
  query params.

```
MyBooksScreen
  useEffect: fetch every tracked book (unchanged, sprint v1/v2)
        |
        v
  books: Book[]  (fetch order, as today)
        |
        v  sort by created_at, newest first        <- NEW
        v  filter by selected tab (All/In Progress/Done/Failed)  <- NEW
        |
        v
  [filter tabs]  All (12)  In Progress (3)  Done (8)  Failed (1)   <- NEW
  [rows, unchanged row layout from v2]
```

## Out of Scope
- Persisting the selected filter across reloads or navigations (a plain
  in-memory `useState`, reset to `All` every time the screen mounts).
- Server-side pagination, sorting, or filtering — the tracked-books list is
  local and small; no `GET /books` list endpoint exists or is added.
- Sorting by anything other than `created_at` (no column-sort UI, no
  ascending/descending toggle).
- Any change to the row itself (title fallback, status badge) — that's
  sprint v2's shape, unchanged here.

## Dependencies
- Sprint v2 shipped `Book.created_at`/`Book.status` on every `GET /books/{id}`
  response and the `Video[]`-based title fallback `MyBooksScreen` already
  reads.
- Sprint v1 shipped the tracked-books `localStorage` index
  (`getTrackedBookIds()`) and the Playwright/mock harness this sprint's tests
  reuse.
