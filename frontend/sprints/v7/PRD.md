# Sprint v7 — PRD: SSE Reconnect Indicator

## Overview
`ProgressView`'s `streamEvents()` call has a single `.catch(() => {})` around
its entire lifetime — a genuine network drop (Wi-Fi blip, proxy timeout,
backend restart) looks identical to a clean, intentional stream close. The
user sees nothing: the live current-node card and chapter list simply stop
updating, silently, with no indication anything went wrong. `BookDetailScreen`
already polls `GET /books/{id}` every 4 seconds as a correctness backstop, so
the book's status is never actually stale for long — but the *live* view
looks frozen with no explanation. This sprint adds a visible reconnect cycle:
a small "Reconnecting..." indicator, and an automatic retry, instead of
silence.

## Goals
- A genuine stream failure (a non-2xx response, a network error) shows a
  `progress-reconnecting` indicator and automatically retries the connection
  after a fixed delay — repeating until it succeeds or the component
  unmounts.
- The last-known progress (current-node card, chapter summary, chapter list)
  stays visible and unchanged while reconnecting — the view never resets to
  a blank "Connecting..." screen just because the stream blipped.
- An intentional stream end is never confused with a failure:
  - Unmounting (leaving the screen, or `bookId` changing) aborts the stream
    and must never trigger a reconnect attempt.
  - A clean stream close with no error (today's existing behavior, e.g. after
    the backend sends a terminal event and closes the response) must never
    trigger a reconnect attempt either — every sprint v1/v3/v5 test fixture
    that ends a mocked SSE body without an explicit terminal event relies on
    this staying inert, and must keep passing unmodified.
- Once a reconnect succeeds (a new `progress` event arrives), the indicator
  clears immediately.

## User Stories
- As a user watching a long render, I want to know when the live view has
  lost its connection, so a quiet stretch doesn't leave me guessing whether
  the book actually stalled or the stream just dropped.
- As a user, I don't want to lose my place — the chapters I've already seen
  finish shouldn't disappear just because the connection hiccuped.

## Technical Architecture
- **Frontend only** — no backend changes, no change to `streamEvents()`'s
  public signature in `src/lib/api.ts`. This sprint only changes how
  `ProgressView` reacts to that promise settling.
- The critical distinction lives entirely in how the `streamEvents(...)`
  promise settles:

```
streamEvents(bookId, onProgress, onTerminal, signal)
        |
        v
   settles how?
        |
        ├─ resolves cleanly (today's existing behavior: reader hits `done`,
        │  e.g. after a terminal event, or a test fixture's body simply
        │  ends) ──────────────────────────────► no reconnect (unchanged)
        │
        ├─ rejects with AbortError (unmount / bookId changed / component
        │  itself called controller.abort()) ──► no reconnect (unchanged)
        │
        └─ rejects with anything else (ApiError from a non-2xx response,
           a real network failure) ─────────────► NEW: schedule a reconnect
                                                   - progress-reconnecting
                                                     indicator shows
                                                   - last-known `progress`
                                                     state is kept as-is
                                                   - after RECONNECT_DELAY_MS,
                                                     reopen the stream
                                                   - repeats until success or
                                                     unmount
```

- No change to `BookDetailScreen`'s existing 4-second status poll — it
  remains the correctness backstop regardless of the SSE stream's state,
  unchanged from sprint v1.

## Out of Scope
- Exponential backoff or a retry cap — a single fixed delay, retried
  indefinitely while the component stays mounted (the parent's status poll
  is the ultimate fallback if reconnects never succeed).
- A user-facing "give up" or manual "retry now" control.
- Distinguishing *why* the stream failed (rate limit vs. network vs. server
  error) in the UI — the indicator is the same regardless of cause.
- A stream close that returns a 200 with no error but no terminal event
  either (a genuinely ambiguous case a mocked test can't really represent,
  and one the real backend's generator doesn't produce today) — treated the
  same as today: no reconnect. Documented as a known limitation, not solved
  here.

## Dependencies
- Sprint v1 shipped `streamEvents()` (`src/lib/api.ts`) and `ProgressView`'s
  SSE wiring, plus `BookDetailScreen`'s 4-second status poll this sprint
  continues to rely on as the backstop.
- Sprint v3/v5 shipped the chapter list and chapter summary that must keep
  rendering, unchanged, while a reconnect is in progress.
