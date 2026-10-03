# Sprint v8 — PRD: Persist My Books Filter

## Overview
Sprint v4 added My Books' status filter (`All`/`In Progress`/`Done`/`Failed`),
but it lives in plain `useState` and resets to `All` every time the screen
mounts — leaving one tab, switching to New Book, and coming back loses
whatever the user had selected. This sprint persists the choice the same way
this app already persists everything else client-side (the API key, the
tracked-books list): `localStorage`.

## Goals
- The selected filter tab survives navigating away and back, and a full page
  reload — a user who filters to `Failed` stays on `Failed` until they
  explicitly pick a different tab.
- A corrupted, stale, or otherwise unrecognized stored value never breaks the
  screen — it falls back to `All`, the same default as today.
- No behavior change for a first-time visitor with nothing stored yet: `All`
  is still what they see first.

## User Stories
- As a user who filters to `In Progress` to check on a running book, I don't
  want that filter forgotten the moment I switch to another tab and come
  back.
- As a user returning to the app after closing the tab, I want My Books to
  open showing what I was last looking at, not reset back to everything.

## Technical Architecture
- **Frontend only** — no backend changes, no new endpoint. Purely a
  `localStorage` read/write, following the exact pattern
  `src/lib/myBooks.ts`'s `getTrackedBookIds()`/`addTrackedBookId()` (v1) and
  `src/lib/api.ts`'s `getApiKey()`/`setApiKey()` (v1) already established:
  a dedicated key, wrapped in `try`/`catch` so a blocked or unavailable
  `localStorage` (private browsing, disabled storage) degrades to the
  existing default instead of throwing.

```
MyBooksScreen mount
        |
        v
  getSavedFilter()  (src/lib/myBooks.ts, NEW)
        |
        ├─ valid stored FilterKey  ──────► initial filter = that value
        └─ nothing stored / invalid ─────► initial filter = 'all'  (unchanged default)

User clicks a filter tab
        |
        v
  setFilter(key)  +  setSavedFilter(key)  (NEW: also writes to localStorage)
```

## Out of Scope
- Persisting anything else about the screen (scroll position, sort order --
  sort is always newest-first with no user control, per v4's PRD).
- A server-side or per-user-account preference — this is the same
  per-browser, per-device `localStorage` scope every other piece of client
  state in this app already uses.
- Any change to the filter tabs' UI, testids, or counts — v4's tabs are
  unchanged, only *which one starts selected* changes.

## Dependencies
- Sprint v4 shipped the filter tabs (`FILTERS`, `FilterKey`, `matchesFilter`)
  in `src/components/MyBooksScreen.tsx` this sprint persists.
- Sprint v1 shipped `src/lib/myBooks.ts` and its `localStorage`
  try/catch pattern this sprint's new helpers follow.
