# Sprint v4 — PRD: Auth + Rate Limiting

## Overview

v1-v3 built the whole book pipeline with no notion of *who* is calling
it — `User` has existed as an unused table since v1's schema. This sprint
adds a minimal API-key auth scheme and per-user concurrent-book limits, so
one caller can no longer exhaust the shared free NVIDIA/Gemini quota for
everyone — the first item on `backend/AGENTS.md`'s production-readiness
checklist this project has actually closed.

## Goals

- `POST /users` creates a `User` and returns a generated API key exactly
  once (never stored or logged in plaintext — only its SHA-256 hash is
  persisted, the same pattern GitHub/Stripe use for PATs).
- Every book-scoped endpoint (`POST /books/youtube`, `GET /books/{id}`,
  `GET /books/{id}/outline`, `PUT /books/{id}/outline`,
  `POST /books/{id}/retry`, `GET /books/{id}/pdf`) requires a valid
  `X-API-Key` header; missing/invalid key → 401.
- A book belongs to the user who created it (`Book.user_id`); a request
  for another user's book id behaves exactly like an unknown id (404) —
  no existence leak.
- `POST /books/youtube` enforces `MAX_CONCURRENT_BOOKS_PER_USER` (default
  3): a user with that many books not yet `done`/`failed` gets 429
  instead of a new book silently queueing behind an already-saturated
  quota.
- `GET /health` stays unauthenticated — it's an operational probe, not a
  user-facing endpoint.

## User Stories

- As a new user, I want to get an API key by giving my email, so I can
  start using the API without a full account/password flow existing yet.
- As a user, I want my books kept private from other users, so someone
  else's API key can't read my book's status or download my PDF.
- As an operator, I want one user's runaway script to get 429s instead
  of silently starving everyone else's free-tier LLM quota.

## Technical Architecture

Builds on v1-v3's `api/` package. No new services — auth is a FastAPI
dependency, rate limiting is a DB count check at creation time.

```
 POST /users {email} ──▶ User row + random 256-bit token
                          (secrets.token_urlsafe(32))
                          DB stores sha256(token) only
                          response: {user_id, api_key}  <- shown once

 client ──X-API-Key: <token>──▶ get_current_user dependency
                                  sha256(token) ──▶ SELECT User WHERE
                                  api_key_hash = ?  (401 if no match)
                                        │
                                        ▼
 POST /books/youtube ──▶ count user's books WHERE status NOT IN
                          (done, failed) ──▶ >= MAX_CONCURRENT_BOOKS_PER_USER?
                          ──▶ 429 : else create Book(user_id=...), enqueue plan

 GET/PUT .../outline, GET .../pdf, POST .../retry
        ──▶ book = get(Book, id); book is None or book.user_id != user.id
            ──▶ 404 (not "403" -- no existence leak)

 GET /health ──▶ no auth dependency, unchanged from v2
```

**Why hash-and-compare instead of a JWT/session**: there's still no
frontend (root `AGENTS.md`: built after `backend/` is stable) and no
password — a long random token is the credential itself, so a bearer
API-key header compared against a stored hash is the right amount of
mechanism for this stage. A real login flow (password or OAuth) is a
`frontend/`-driven concern for a later sprint.

**Why SHA-256, not bcrypt/argon2**: those slow-hash schemes defend
low-entropy human-chosen passwords against offline brute force; a
256-bit random token already has far more entropy than a slow hash adds
protection for. Same reasoning GitHub/Stripe/AWS use for PAT-style keys.

## Out of Scope (v5+)

- Password-based login, JWT/session tokens, OAuth — all a `frontend/`
  concern once one exists.
- Per-key scopes/roles (every key can do everything its owning user
  could do) — no multi-tenant admin concept yet.
- Rate-limiting `POST /users` itself against signup abuse.
- A global (cross-user) daily spend/quota alert — this sprint only caps
  per-user concurrency, not aggregate spend (`backend/AGENTS.md`'s
  "Cost ceiling" checklist item stays open).
- Revoking/rotating an API key (no `DELETE`/`POST /users/{id}/rotate-key`
  endpoint yet) — a key is permanent once issued.
- Everything else already listed as deferred in v3's PRD (reordering,
  per-chapter status, `/events`, Postgres checkpointer, S3, and the rest
  of the production-readiness checklist).

## Dependencies

- Sprints v1-v3 complete: core loop, `/health` + logging + PDF download,
  outline review + retry, all tested against real Postgres/Redis.
- `docker-compose up -d` available locally, same as v1-v3.
