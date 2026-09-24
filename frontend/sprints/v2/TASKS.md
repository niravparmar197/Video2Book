# Sprint v2 — Tasks

## Status: In Progress

- [ ] Task 1: Backend — expose book metadata via `BookResponse` (P0)
  - Acceptance: `GET /books/{id}` (and the `POST /books/youtube` /
    `POST /books/{id}/retry` responses, since they share `BookResponse`) include
    `url: str`, `created_at: str` (ISO 8601), `estimated_cost_usd: float`, and
    `videos: list[{video_id: str, title: str | None, duration_seconds: int | None}]`;
    a new integration test asserts the shape on a book with 2 videos; full existing
    backend suite (107+ tests) still passes.
  - Files: backend/api/schemas.py, backend/api/routers/books.py,
    backend/tests/integration/test_books_status.py
- [ ] Task 2: Backend — `POST /books/{id}/cancel` (P0)
  - Acceptance: cancelling a book in `queued`/`planning`/`outline_ready`/`rendering`
    sets `status="failed"`, `error_message="Cancelled by user"`, and returns 202;
    cancelling a `done` or already-`failed` book returns 409 (same pattern as
    `/retry`'s check); the BullMQ job for that `book_id` is removed if still queued
    (best-effort — a job already picked up by the worker is left to finish its
    current step, not force-killed); new integration tests cover both paths.
  - Files: backend/api/routers/books.py, backend/tests/integration/test_books_cancel.py
- [ ] Task 3: Frontend — extend `Book` type and `api.ts` for the new fields (P0)
  - Acceptance: `Book` in `src/types.ts` gains `url`, `created_at`,
    `estimated_cost_usd`, `videos: Video[]` (new `Video` type: `video_id`, `title`,
    `duration_seconds`); `src/lib/api.ts` exports `cancelBook(bookId): Promise<Book>`
    calling `POST /books/{id}/cancel`; `tsc --noEmit` clean.
  - Files: src/types.ts, src/lib/api.ts
- [ ] Task 4: My Books list shows real titles (P0)
  - Acceptance: each row's primary text is `videos[0]?.title ?? url ?? id` (in that
    fallback order), with the raw id demoted to small secondary text (not removed --
    existing `my-books-row-{id}`/`my-books-status-{id}` testids and Task 5's E2E
    assertions on them keep passing unmodified); a new E2E test covers all three
    fallback tiers (has a title, has only a url, has neither).
  - Files: src/components/MyBooksScreen.tsx, tests/e2e/my-books-metadata.spec.ts
- [ ] Task 5: Book detail screen shows a metadata card (P0)
  - Acceptance: a card above the status-specific content shows the title (same
    fallback chain as Task 4), the source `url` as a real link
    (`target="_blank" rel="noopener noreferrer"`), `estimated_cost_usd` formatted as
    `"$0.00"`-style currency, and `created_at` formatted as a readable date;
    `data-testid`s on each field; E2E test asserts all four render from mocked data.
  - Files: src/components/BookDetailScreen.tsx, tests/e2e/book-detail-metadata.spec.ts
- [ ] Task 6: Cancel button for in-flight books (P0)
  - Acceptance: `data-testid="book-detail-cancel"` button renders only when status is
    `queued`/`planning`/`outline_ready`/`rendering` (not `done`/`failed`); clicking it
    calls the mocked `POST /books/{id}/cancel` and the screen transitions to the
    existing failed-state UI showing "Cancelled by user"; E2E test covers the click
    and the resulting UI state.
  - Files: src/components/BookDetailScreen.tsx, tests/e2e/book-detail-cancel.spec.ts
- [ ] Task 7: Style the metadata card with the existing design tokens (P1)
  - Acceptance: the Task 5 card uses the same surface/spacing/typography classes as
    the rest of the app (no new colors or one-off values); reviewed via a screenshot
    in `tests/screenshots/`; all Task 4-6 tests still pass unmodified.
  - Files: src/components/BookDetailScreen.tsx
- [ ] Task 8: Mobile responsiveness for the new elements at 375px (P2)
  - Acceptance: `tests/e2e/responsive.spec.ts`'s existing walk is extended to include
    the book detail metadata card and the cancel button, asserting no horizontal
    scroll and full viewport visibility for each; any overflow found is fixed in the
    relevant component's Tailwind classes.
  - Files: tests/e2e/responsive.spec.ts, src/components/*.tsx (layout fixes as needed)
