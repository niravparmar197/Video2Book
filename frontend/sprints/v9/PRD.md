# Sprint v9 — PRD: My Books Text Search

## Overview
My Books has a status filter (v4, now persisted in v8) but no way to narrow
the list by anything about a *specific* book — once someone is tracking more
than a handful, finding "the one about transformers" means scrolling and
reading every title. This sprint adds a text box that narrows the
already-status-filtered list by a substring match against title, source URL,
or id.

## Goals
- A search input above the book list narrows the currently-filtered rows to
  those whose title, source URL, or id contains the typed text
  (case-insensitive).
- Search and the v4 status filter combine (AND, not OR) — typing a search
  term while `Done` is selected only searches within done books.
- An empty search box behaves exactly like today: no narrowing at all.
- A search with zero matches shows a distinct, search-specific empty message
  ("No books match…") — not the same "No {status} books." message v4 shows
  for an empty status filter, so a user can tell "your filter has nothing"
  apart from "your search found nothing."
- Filter tab counts (`All (4)`, `Done (1)`, etc.) stay based on status alone,
  unaffected by the search box — a deliberate simplification, not an
  oversight (see Out of Scope).

## User Stories
- As a user tracking a dozen books, I want to type part of a title and
  immediately see just that book, so I don't have to scroll and read every
  row.
- As a user who only remembers pasting a specific URL, I want searching by
  (part of) that URL to find the book, since the title might not have
  rendered yet.

## Technical Architecture
- **Frontend only** — no backend changes, no new endpoint. Every field this
  sprint searches (`bookTitle()`'s fallback chain, `book.url`, `book.id`) is
  already fetched and held in `MyBooksScreen`'s existing `books` state.
- Purely client-side, in-memory filtering — the same `useMemo` pattern v4
  already uses for `sortedBooks`/`filteredBooks`, just with one more `.filter()`
  step layered on top.

```
MyBooksScreen
  books: Book[]  (fetched, unchanged)
        |
        v  sort by created_at, newest first          (v4, unchanged)
        v  filter by selected status tab              (v4, unchanged)
        v  filter by search text (NEW)
           -- match against bookTitle(book) || book.url || book.id,
              case-insensitive substring
        |
        v
  [status filter tabs -- counts unaffected by search, v4/v8 unchanged]
  [search input]                                       <- NEW
  [rows, or a search-specific empty state if 0 matches with a non-empty query]
```

## Out of Scope
- Filter tab counts reflecting the search text too — kept simple and
  predictable (counts always mean "how many books have this status," full
  stop); revisit only if real usage shows the current behavior confusing.
- Debouncing or any async/network behavior — this is an in-memory array
  filter over a small, already-fetched list; there is nothing to debounce
  against.
- Fuzzy matching, ranking, or highlighting matched substrings — a plain
  case-insensitive substring match only.
- Persisting the search text across visits (unlike v8's filter tab, a typed
  search query is treated as transient, not a saved preference).

## Dependencies
- Sprint v4 shipped the status filter (`FILTERS`, `matchesFilter`,
  `sortedBooks`/`filteredBooks`) this sprint layers search on top of.
- Sprint v8 shipped `src/lib/myBooks.ts`'s persistence pattern, though this
  sprint deliberately does NOT persist the search text (see Out of Scope).
- Sprint v2 shipped `bookTitle()`'s fallback chain (`videos[0]?.title || url
  || id`) this sprint searches against as the row's effective title.
