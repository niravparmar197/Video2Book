# Sprint v1 — PRD: Harden the Core Flow

## Overview
Earlier work this cycle replaced the AI-Studio mock prototype with real screens wired to
`backend/`'s actual API (login/register, submit a book, live progress, outline review,
download, retry). This sprint doesn't add new user-facing features — it makes that flow
trustworthy: Playwright E2E coverage against a mocked backend (required by
`frontend/AGENTS.md`), `data-testid` selectors on every interactive element, consistent
loading/empty/error states, mobile-width layout, and the one real infrastructure gap
(missing CORS) that currently stops the frontend and backend from talking to each other
in a browser at all.

## Goals
- Every screen (login, new book, my books, outline review, progress, done, failed) has
  a Playwright E2E test with `data-testid` selectors, hitting a mocked API — never the
  real backend or LLM chain.
- `localhost:3000` can call `localhost:8000` in dev without a CORS error.
- Loading, empty, and error states are visually consistent across screens instead of
  ad-hoc plain-text messages.
- The app is usable at 375px width (iPhone SE) with no horizontal scroll or clipped
  controls.

## User Stories
- As a developer, I want E2E tests with screenshots at key steps, so a regression in
  the submit → outline → download flow is caught before it ships.
- As a user on a slow connection, I want a visible loading state instead of a blank
  screen, so I know the app is working.
- As a user, I want the same look-and-feel whether a request is loading, empty, or
  failed, so the app feels finished rather than half-wired.
- As a developer running the frontend locally against a local backend, I want the
  request to actually reach the API instead of being blocked by the browser, so I can
  test the real integration.

## Technical Architecture
- **Frontend**: Vite + React + Tailwind (`frontend/`, as decided this cycle — not
  Next.js; `frontend/AGENTS.md`'s stack line is superseded for this project by that
  decision).
- **E2E**: Playwright (`@playwright/test`), run against `vite preview` with all backend
  calls intercepted via `page.route()` — no real network egress to `backend/` or any
  LLM provider, per the root `AGENTS.md` testing rule.
- **Backend touch**: one task adds `CORSMiddleware` to `backend/api/main.py`, scoped to
  the frontend dev origin via an env var, following the existing `Settings` dataclass
  pattern in `backend/api/config.py`.

```
Playwright test
   |
   |  page.route('**/books/**', mock)   <-- no real network call
   v
Vite preview server (dist/)
   |
   v
React app  ->  src/lib/api.ts  ->  fetch(VITE_API_BASE_URL + ...)   [intercepted in tests]
                                          |
                                          v (real dev use only, not tests)
                                    backend/ FastAPI (needs CORS, Task 2)
```

## Out of Scope
- New user-facing features (multi-book comparison, book previews, notifications, etc.)
- Chapter reordering in the outline editor — `backend/api/schemas.py`'s `ChapterEdit`
  has no `order` field, so there is nothing to persist; out of scope until the backend
  supports it.
- Real cross-browser/device testing — Playwright runs Chromium only this sprint.
- Any change to `ai_llm/` or pipeline logic.

## Dependencies
- `backend/` already exposes `POST /users`, `POST /books/youtube`, `GET /books/{id}`,
  `GET /books/{id}/events`, `GET /books/{id}/outline`, `PUT /books/{id}/outline`,
  `GET /books/{id}/pdf`, `POST /books/{id}/retry` — all consumed by the current
  frontend code in `src/lib/api.ts`.
- The frontend screens themselves (`src/components/*`, `src/lib/*`) already exist and
  are not being rewritten this sprint, only instrumented and polished.
