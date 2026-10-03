# Sprint v5 — PRD: Chapter Progress Summary

## Overview
Sprint v3 surfaced each chapter's write/verify outcome as a per-chapter list
in `ProgressView`, but a book with a dozen-plus chapters gives no sense of
overall completion — a user has to scroll and count `check_circle` icons
themselves to know "am I nearly done, or barely started?" This sprint adds a
one-glance summary (a count and a progress bar) above that list, computed
entirely from data `ProgressView` already receives.

## Goals
- `ProgressView` shows an "N of M chapters done" count and a visual progress
  bar whenever `progress.chapters` is non-empty, positioned between the
  current-node card and the per-chapter list.
- If any finished chapter didn't pass verification (`passed === false`), the
  summary also surfaces a "needs review" count, so a user scanning the
  summary alone still learns something needs a second look — not just
  "12 of 12 done" masking a chapter that failed its judge score.
- Before `chapters` has any entries (same pre-outline condition as v3), the
  screen looks exactly as it does today — no summary row, no layout shift.
- The summary updates live as the SSE stream delivers new chapter states,
  same as the existing per-chapter list.

## User Stories
- As a user watching a 20-chapter playlist render, I want a single number
  telling me how far along it is, so I don't have to count checkmarks myself.
- As a user, I want to know at a glance if anything needs review once the
  book finishes rendering, so a clean-looking "all done" summary doesn't
  quietly hide a chapter that needed a closer look.

## Technical Architecture
- **Frontend only** — no backend changes. `chapters` (sprint v3) already
  carries every field this sprint needs (`status`, `passed`).
- Purely a derived-data addition inside `ProgressView`: no new fetch, no new
  type field, no change to `streamEvents` or `ProgressEvent`.

```
progress.chapters: ChapterProgress[]   (unchanged wire shape, sprint v3)
        |
        v
ProgressView (derived, in-render, no new state)
  done   = chapters.filter(c => c.status === 'done').length
  total  = chapters.length
  needsReview = chapters.filter(c => c.status === 'done' && c.passed === false).length
        |
        v
[current-node card]                    (unchanged, v1)
[chapter summary]                      NEW -- "7 of 12 chapters done"
                                             progress bar (done/total)
                                             "2 need review" (only if > 0)
[chapter list]                         (unchanged, v3)
```

## Out of Scope
- Any change to the `chapters` wire shape or `ChapterProgress` type — this
  sprint only derives numbers from data that already exists client-side.
- An overall book-level percentage that blends the plan/fetch/transcribe
  phases with chapter completion — the summary only covers chapters, the
  same scope v3's per-chapter list already established.
- Render/compile-phase completion (same known limitation v3 documented:
  "done" means notes finalized, not PDF-rendered).
- Persisting or exporting the summary anywhere outside `ProgressView`.

## Dependencies
- Sprint v3 shipped `progress.chapters: ChapterProgress[]`
  (`{id, title, status, score, attempts, passed}`) and the `ChapterRow`
  list this sprint's summary sits above.
- Sprint v1 shipped `ProgressView`'s SSE wiring (`streamEvents`) and the
  Playwright/mock harness this sprint's tests reuse.
