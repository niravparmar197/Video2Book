# frontend/ — Web App

Scope: built only after `backend/` exists. A thin client over the backend API — paste links, review/edit the outline, watch live progress, download the PDF, log in. See the root `AGENTS.md` for the cross-project decisions this builds on.

## Stack

| Part | Tool |
|---|---|
| Framework | React + Vite (TypeScript) |
| Styling | Tailwind CSS |

## Core flows (backed by `backend/`'s API — see `backend/AGENTS.md` for endpoints)

- Submit YouTube links or a playlist → `POST /books/youtube`
- Poll/stream `GET /books/{id}` and `GET /books/{id}/events` for live progress
- Outline review screen: fetch `GET /books/{id}/outline`, let the user reorder/lock/skip topics, save via `PUT /books/{id}/outline` — this mirrors the `--plan-only` / edit `outline.json` / `--resume` flow in `ai_llm/`, just through a UI instead of a text editor
- Download: `GET /books/{id}/pdf`
- Retry failed chapters: `POST /books/{id}/retry`
- Auth/login gates all of the above

## Testing

- UI/page tasks get Playwright E2E tests with screenshots at key steps (`tests/screenshots/taskN-stepN-description.png`) — before and after key interactions.
- Use `data-testid` attributes for Playwright selectors — never CSS classes.
- Never call the real backend/LLM chain from a test — hit a mocked/stubbed API.
