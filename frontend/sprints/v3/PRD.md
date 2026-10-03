# Sprint v3 — PRD: Per-Chapter Progress

## Overview
`backend/`'s sprint v9 extended `GET /books/{id}/events`'s `progress` SSE event with a
`chapters` array — each source video's or merged topic's write-and-verify outcome
(`status`, `score`, `attempts`, `passed`), refreshed every poll tick straight from disk.
Today `ProgressView` only reads `current_node`/`completed_nodes` from that same payload
and ignores `chapters` entirely, so a book spending most of its wall-clock time inside
one long `write` node (writing and judging chapter after chapter) still looks frozen on
"Working on it..." even though the backend now has real, per-chapter signal to show.
This sprint surfaces that signal.

## Goals
- `ProgressEvent` (`src/types.ts`) gains a `chapters: ChapterProgress[]` field matching
  the backend's shape; `streamEvents` needs no change (it already passes the parsed
  JSON straight through).
- `ProgressView` renders a live per-chapter list under the existing current-node
  indicator once `chapters` is non-empty: each chapter shows its title, a
  done/pending status icon, and — once done — its pass/fail outcome and score.
- A chapter that needed more than one refine attempt to pass is visibly flagged (not
  just pass/fail), since that's the signal `backend/AGENTS.md`'s write-and-verify loop
  exists to surface.
- Before `chapters` has any entries (a book still in `plan`/`fetch`/`transcribe`, before
  `outline.json` exists), the screen looks exactly as it does today — no empty list, no
  layout shift.

## User Stories
- As a user watching a long playlist render, I want to see which chapters are already
  done and which are still being written, so a quiet stretch on one big `write` node
  doesn't look like the app has stalled.
- As a user, I want to see which chapters needed extra refine attempts or didn't pass
  clean, so I know which parts of the finished book are worth a closer read.

## Technical Architecture
- **Frontend only** — no backend changes. `backend/`'s sprint v9 already ships
  `chapters` on the wire; this sprint is purely a consumer.
- Same Vite + React + Tailwind app, same mocked-backend Playwright harness (SSE bodies
  mocked as static `page.route()` text, per the existing `progress-view.spec.ts`
  pattern — no real stream, no real backend).

```
GET /books/{id}/events  (SSE, unchanged wire format — v9 already ships this)
  event: progress
  data: { current_node, completed_nodes,
          chapters: [{ id, title, status: "pending"|"done",
                        score: number|null, attempts: number|null,
                        passed: boolean|null }] }
        |
        v
src/lib/api.ts: streamEvents()  -- unchanged, passes parsed JSON straight through
        |
        v
src/components/ProgressView.tsx
  "Working on it..." (unchanged)
  [current-node card]              (unchanged)
  [chapter list]                   (NEW -- only rendered once chapters.length > 0)
     ch-1  <status icon> Title            done, score 9, passed
     ch-2  <status icon> Title            done, score 6, passed, 3 attempts
     ch-3  <status icon> Title            pending
```

## Out of Scope
- Render/compile-phase chapter status — v9's `chapters` only reflects the
  write/verify phase (a chapter shows `"done"` once notes are finalized, not once the
  PDF page is rendered); this sprint surfaces exactly what the backend sends, no more.
- Section/chunk-level detail within a single video-mode chapter — the backend
  aggregates to one score/attempts pair per chapter (weakest section wins); this sprint
  doesn't ask for anything finer-grained.
- Any UI for reordering, skipping, or locking chapters mid-render — that's the
  existing outline-review screen's job, before rendering starts, not this one.
- Cross-browser/CI coverage (unchanged from v1/v2 — Chromium only via Playwright).

## Dependencies
- Backend sprint v9 shipped: `GET /books/{id}/events`'s `progress` event carries
  `chapters: [{id, title, status, score, attempts, passed}]`, recomputed from disk
  every poll tick, folded into the SSE dedup key so a chapter finishing produces a
  real event even when the book-wide node position hasn't moved.
- Sprint v1 shipped the Playwright/mock harness and `ProgressView`'s existing
  `current_node`/`completed_nodes` rendering, which this sprint extends rather than
  replaces.
