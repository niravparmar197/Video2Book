# Sprint v1 — Tasks

## Status: In Progress

- [x] Task 1: Playwright E2E harness with a mocked backend (P0)
  - Acceptance: `@playwright/test` installed; `playwright.config.ts` runs against
    `vite preview`; a `tests/e2e/mocks.ts` helper installs `page.route()` handlers for
    every `/users`, `/books/*` endpoint; a trivial smoke test (`tests/e2e/smoke.spec.ts`)
    loads the app and passes with zero real network requests. `npm run test:e2e` script
    added.
  - Files: package.json, playwright.config.ts, tests/e2e/mocks.ts, tests/e2e/smoke.spec.ts
  - Completed: 2026-09-25 — Installed `@playwright/test` + Chromium; added
    `playwright.config.ts` (builds + serves via `vite preview` on :4173, Chromium
    project); `tests/e2e/mocks.ts` installs a catch-all `page.route()` safety net over
    `API_BASE + '/**'` that fails loudly on any unmocked call (specific per-endpoint
    mocks get layered on top of it in Tasks 3-8, since Playwright resolves the
    most-recently-registered matching route first); `tests/e2e/smoke.spec.ts` asserts
    the login screen renders with zero real backend requests; `npm run test:e2e` script
    added. `tsc --noEmit`, `semgrep --config auto` (0 findings/227 rules), and
    `npm audit` (0 vulnerabilities) all clean. Not committed — this directory has no
    `.git` (confirmed via `git status`); ask the user before initializing one.

- [x] Task 2: Add CORS middleware to the backend for the frontend dev origin (P0)
  - Acceptance: `backend/api/main.py` adds `CORSMiddleware` allowing the origin from a
    new `FRONTEND_ORIGIN` setting (default `http://localhost:3000`) in
    `backend/api/config.py`; `curl -H "Origin: http://localhost:3000" -i
    http://localhost:8000/health` returns an `Access-Control-Allow-Origin` header;
    existing backend test suite still passes.
  - Files: backend/api/main.py, backend/api/config.py
  - Completed: 2026-09-25 — Added `Settings.frontend_origin` (env `FRONTEND_ORIGIN`,
    default `http://localhost:3000`) and wired `CORSMiddleware` into
    `backend/api/main.py`. New `backend/tests/integration/test_cors.py` (3 tests:
    preflight allowed, actual request echoes the header, an unlisted origin gets no
    CORS headers) plus the full existing suite (107 tests) pass. Verified live with
    the curl command from Acceptance -- returns
    `access-control-allow-origin: http://localhost:3000`. Documented `FRONTEND_ORIGIN`
    in `backend/.env.example`. `semgrep --config auto` on `backend/` clean (0
    findings/325 rules); `pip-audit` flags only the ambient `pip` tool itself (24.0,
    pre-existing, unrelated to this change) -- no findings on any project dependency.

- [x] Task 3: `data-testid`s + E2E test for the login screen (P0)
  - Acceptance: `data-testid` on the email input, register submit button, "I have a
    key" tab, paste-key input, paste-key submit, and the issued-key continue button;
    Playwright test covers both the register-then-continue path and the paste-key path,
    asserting `localStorage`'s `v2b_api_key` is set and the app renders the logged-in
    shell; screenshots at `tests/screenshots/task3-step1-login-empty.png` and
    `tests/screenshots/task3-step2-logged-in.png`.
  - Files: src/components/LoginScreen.tsx, tests/e2e/login.spec.ts
  - Completed: 2026-09-25 — Added `data-testid`s to every interactive element on
    `LoginScreen` (`login-email-input`, `login-register-submit`, `login-tab-register`,
    `login-tab-paste`, `login-paste-key-input`, `login-paste-submit`,
    `login-issued-key`, `login-continue-button`, `login-error`). Added a reusable
    `mockJson()` helper to `tests/e2e/mocks.ts` (used by this and future tasks) and
    `tests/e2e/login.spec.ts` (3 tests: register-then-continue, paste-key login, and a
    failed-registration error path), with screenshots at
    `tests/screenshots/task3-01-login-empty.png` and `task3-02-logged-in.png`. Full
    E2E suite (4 tests) + `tsc --noEmit` pass. `semgrep` clean (0/227 rules); `npm
    audit` clean.

- [x] Task 4: `data-testid`s + E2E test for submitting a new book (P0)
  - Acceptance: `data-testid` on the URL input and submit button; test mocks
    `POST /books/youtube` returning a `queued` book, submits a URL, and asserts the app
    navigates to that book's detail view; screenshots before and after submit.
  - Files: src/components/NewBookScreen.tsx, tests/e2e/new-book.spec.ts
  - Completed: 2026-09-25 — Added `data-testid`s (`new-book-url-input`,
    `new-book-submit`, `new-book-error`) and a `book-detail-id` testid on
    `BookDetailScreen` (needed to assert navigation landed on the right book).
    Added a `loginAs()` helper to `tests/e2e/mocks.ts` (seeds `localStorage`'s API key
    to skip the login screen -- reused by Tasks 5-8). `tests/e2e/new-book.spec.ts`: 2
    tests (successful submit navigates to book detail; a 429 in-flight-limit error
    renders). Full E2E suite (6 tests) + `tsc --noEmit` pass. `semgrep` clean (0/227
    rules, verified new file is actually scanned via a direct single-file run); `npm
    audit` clean.

- [x] Task 5: `data-testid`s + E2E test for the My Books list (P0)
  - Acceptance: `data-testid` on each book row and its status badge; test covers the
    empty state (no tracked ids) and a populated state (mocked tracked ids + mocked
    `GET /books/{id}` per id) showing correct status labels; screenshots for both states.
  - Files: src/components/MyBooksScreen.tsx, tests/e2e/my-books.spec.ts
  - Completed: 2026-09-25 — Added `my-books-empty`, `my-books-row-{id}`, and
    `my-books-status-{id}` testids; also added `nav-tab-{new,books}` to `BottomNav`
    (needed to switch tabs from a test). Added `seedTrackedBooks()` to
    `tests/e2e/mocks.ts`. `tests/e2e/my-books.spec.ts`: 2 tests (empty state, populated
    state with two books' live statuses). Full E2E suite (8 tests) + `tsc --noEmit`
    pass. `semgrep` clean (0/227 rules); `npm audit` clean.

- [ ] Task 6: `data-testid`s + E2E test for the outline editor (P0)
  - Acceptance: `data-testid` on each chapter card, its lock toggle, its skip toggle,
    and the save button; test mocks `GET /books/{id}/outline` with 2+ chapters, toggles
    skip on one and locked on another, saves, and asserts the mocked
    `PUT /books/{id}/outline` received the correct `ChapterEdit[]` payload; screenshots
    before and after toggling.
  - Files: src/components/OutlineEditor.tsx, tests/e2e/outline-editor.spec.ts

- [ ] Task 7: `data-testid`s + E2E test for done/failed terminal states (P0)
  - Acceptance: `data-testid` on the download button, the retry button, and the error
    message container; one test mocks a `done` book + `GET /books/{id}/pdf` and asserts
    clicking Download triggers a file save; another mocks a `failed` book with an
    `error_message` and asserts it renders, then asserts clicking Retry calls the mocked
    `POST /books/{id}/retry`; screenshots for both states.
  - Files: src/components/BookDetailScreen.tsx, tests/e2e/book-detail-terminal.spec.ts

- [ ] Task 8: `data-testid`s + E2E test for the live progress view (P1)
  - Acceptance: `data-testid` on the current-step label and the completed-steps list;
    test mocks the `GET /books/{id}/events` SSE stream (a fake `text/event-stream`
    response with two `progress` events then a `done` event) and asserts the UI updates
    from each event without a page reload.
  - Files: src/components/ProgressView.tsx, tests/e2e/progress-view.spec.ts

- [ ] Task 9: Shared loading/empty/error state components (P1)
  - Acceptance: a single `src/components/StateMessage.tsx` (or equivalent) used by
    every screen for its loading spinner, empty state, and error banner, replacing the
    current ad-hoc plain-`<p>` messages; no visual layout shift when a screen moves
    from loading to loaded; existing E2E tests from Tasks 3-8 still pass unmodified.
  - Files: src/components/StateMessage.tsx, src/components/*.tsx (loading/error call
    sites)

- [ ] Task 10: Mobile responsiveness pass at 375px width (P2)
  - Acceptance: a Playwright test sets a 375x667 viewport and walks login → new book →
    my books → outline editor, asserting no horizontal scroll (`document.body
    .scrollWidth <= 375`) and that every button/input is fully visible in the viewport;
    any clipped element found is fixed in the corresponding component's Tailwind
    classes.
  - Files: tests/e2e/responsive.spec.ts, src/components/*.tsx (layout fixes as needed)
