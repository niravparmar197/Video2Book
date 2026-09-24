# Sprint v2 — PRD: Book Metadata + Cancel

## Overview
Sprint v1 hardened the core flow but left every book looking like a bare UUID with a
status badge — no title, no source link, no cost, no way to back out of a run you
started by mistake. This sprint surfaces metadata the backend already captures but
never exposes (`Book.url`/`created_at`/`estimated_cost_usd`, `Video.title`), and adds
the ability to cancel a book that hasn't finished yet.

## Goals
- `GET /books/{id}` (and the create/retry responses) return `url`, `created_at`,
  `estimated_cost_usd`, and each source video's `title`/`duration_seconds`.
- My Books and the book detail screen show a real title (falling back to the source
  URL, then the book id, in that order) instead of a raw id.
- The book detail screen shows source link, estimated cost, and created date.
- A user can cancel a book that's queued, planning, outline-ready, or rendering.

## User Stories
- As a user with several books in flight, I want to see their real titles in My
  Books, so I can tell them apart without opening each one.
- As a user, I want to see what a book has cost so far, so I can watch it against
  `MAX_BOOK_COST_USD` myself.
- As a user who pasted the wrong link, I want to cancel a book immediately, so I'm
  not stuck waiting for a run I don't want.

## Technical Architecture
- **Frontend**: same Vite + React + Tailwind app from Sprint v1, same mocked-backend
  Playwright harness.
- **Backend touch** (two small, additive changes, same shape as v1 Task 2's CORS
  middleware — no pipeline logic, no new tables):
  - `BookResponse` (`backend/api/schemas.py`) gains `url`, `created_at`,
    `estimated_cost_usd`, `videos: list[VideoOut]` (`video_id`, `title`,
    `duration_seconds`) — all already columns on `Book`/`Video`
    (`backend/api/models.py`), just never serialized.
  - New `POST /books/{id}/cancel`: valid only from `queued`/`planning`/
    `outline_ready`/`rendering` (409 otherwise, same pattern as `/retry`'s 409 check);
    sets `status="failed"`, `error_message="Cancelled by user"`; best-effort removes
    the BullMQ job (`jobId = book_id`) so queued-but-not-yet-started work never
    starts. **Honest limit, not glossed over**: a job the worker has already picked
    up keeps running to its next checkpoint — this sprint does not add mid-step
    worker interruption. That's real future work, not something to fake here.

```
MyBooksScreen / BookDetailScreen
   |
   |  GET /books/{id}  ->  { id, status, pdf_path, error_message,
   |                         url, created_at, estimated_cost_usd,
   |                         videos: [{ video_id, title, duration_seconds }] }
   v
title = videos[0]?.title ?? url ?? id   (client-side fallback chain)

BookDetailScreen "Cancel" button (visible while in-flight)
   |
   v
POST /books/{id}/cancel  ->  { status: "failed", error_message: "Cancelled by user" }
   |
   v
Existing failed-state UI (Task 7, v1) renders as-is -- no new UI state needed
```

## Out of Scope
- Guaranteed mid-run interruption of a job the worker has already started (see
  above) — this sprint only prevents not-yet-started and queued work from running.
- Chapter reordering — still blocked on `ChapterEdit` having no `order` field
  (unchanged from v1's PRD).
- Editing a book's title (it's derived, read-only, from `Video.title`).
- Cross-browser/CI coverage (a separate direction the user didn't pick this round).

## Dependencies
- Sprint v1 shipped: the full screen set, the Playwright/mock harness, CORS.
- `backend/api/models.py` already has every column this sprint needs (`Book.url`,
  `Book.created_at`, `Book.estimated_cost_usd`, `Video.title`,
  `Video.duration_seconds`) — confirmed by reading the model before writing this PRD.
  No migration required, only schema/router changes.
