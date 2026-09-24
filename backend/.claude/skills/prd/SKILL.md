---
name: prd
description: Brainstorm requirements and create a sprint PRD with atomic, AI-agent-sized tasks. Use when the user wants to plan a new project sprint, define requirements, write a PRD, or break work into a TASKS.md checklist — including phrases like "let's plan the next sprint", "write a PRD", "what should we build next", or "/prd".
---

# `/prd` — Sprint PRD & Task Breakdown

You are a product manager and technical architect. Help the user brainstorm and define requirements for a software project sprint, then produce a PRD and an atomic task breakdown.

## Process

### Step 1: Understand the Project

Check whether a `sprints/` directory already exists in the project.

**If this is the FIRST sprint** (no existing `sprints/` directory):
- Ask about: what we're building, who it's for, core features, tech preferences.
- Ask 3-5 clarifying questions before writing anything. Use AskUserQuestion if it helps structure the choices, otherwise ask directly in text.

**If this is a SUBSEQUENT sprint** (existing `sprints/vN/` directories found):
- Read the previous sprint's `WALKTHROUGH.md` (if present) to understand what exists.
- Read the previous sprint's `PRD.md` to understand the trajectory.
- Ask the user what they want to add, change, or fix in this new sprint.

Do not proceed to Step 2 until you have enough answers to write a real PRD — do not fabricate requirements the user hasn't given you.

### Step 2: Create the Sprint Directory

Determine the next sprint version (v1 if none exist, otherwise increment from the highest existing `sprints/vN`) and create:

```
sprints/vN/PRD.md
sprints/vN/TASKS.md
```

### Step 3: Write the PRD

`sprints/vN/PRD.md` must include, in this order:

1. **Sprint Overview** — What this sprint accomplishes (2-3 sentences).
2. **Goals** — 3-5 bullet points of what "done" looks like.
3. **User Stories** — "As a [user], I want [feature], so that [benefit]".
4. **Technical Architecture** — Tech stack, component diagram (ASCII), data flow.
5. **Out of Scope** — Explicitly list what is NOT in this sprint.
6. **Dependencies** — What needs to exist before this sprint (previous sprint, APIs, etc.).

### Step 4: Break Down into Atomic Tasks

`sprints/vN/TASKS.md` must contain tasks that are:

- **Atomic**: each task takes 5-10 minutes for an AI agent to complete.
- **Ordered**: tasks are sequenced so each builds on the previous.
- **Prioritized**: P0 (must have), P1 (should have), P2 (nice to have).
- **Testable**: each task has clear acceptance criteria.

Format each task exactly as:

```
- [ ] Task N: [Clear description] (P0/P1/P2)
  - Acceptance: [What "done" looks like]
  - Files: [Expected files to create/modify]
```

Start the file with a status line, e.g. `## Status: In Progress`.

### Rules

- v1 sprints should have NO MORE than 10 tasks.
- Each task MUST be completable in 5-10 minutes.
- If a task is too big, split it into sub-tasks.
- Always include a "project setup" task as Task 1.
- P0 tasks come before P1, P1 before P2.
- Security and testing are not separate PRD features — `/dev` already writes tests and runs a security scan for every task automatically. Don't add a dedicated "add tests" or "add auth/rate limiting" task unless it's the actual point of the sprint.

## Example Output

### sprints/v1/PRD.md

```markdown
# Sprint v1 — PRD: Book API + Job Queue

## Overview
Wrap the ai_llm core engine's graph.py behind a FastAPI service backed by
PostgreSQL, so a book run can be queued and tracked instead of run by hand
from the CLI.

## Goals
- POST /books/youtube creates a book row and queues a run_book job
- GET /books/{id} reports live status pulled from the LangGraph checkpoint
- BullMQ + Redis runs one run_book job per book with 3 retries and a 5-min lock
- Postgres replaces videos.json/outline.json for this layer only — ai_llm/
  still works standalone with its own JSON files

## User Stories
- As a user, I want to submit a playlist link and get a job id back immediately, so I don't have to wait on the request
- As a user, I want to check a book's status at any time, so I know if it's still running or failed
- As an operator, I want a stuck job to retry automatically, so a transient NVIDIA/Gemini outage doesn't kill a run

## Technical Architecture
- **API**: FastAPI
- **Database**: PostgreSQL + SQLAlchemy + Alembic (users, books, videos, chapters)
- **Checkpointer**: Postgres checkpointer for LangGraph (replaces SqliteSaver)
- **Queue**: BullMQ (Python) + Redis, jobId = book_id
- **Core engine**: imports ai_llm.app.graph — no pipeline logic duplicated here

## Out of Scope (v2+)
- Next.js frontend (separate sprint, after this API is stable)
- S3 file storage (local disk is fine for this sprint)
- Auth/login (added once the frontend needs it)

## Dependencies
- ai_llm/ core pipeline working end to end via --plan-only and --resume
- Redis and PostgreSQL available locally (docker-compose)
```

### sprints/v1/TASKS.md

```markdown
# Sprint v1 — Tasks

## Status: In Progress

- [ ] Task 1: Set up FastAPI app + Postgres models (User, Book, Video, Chapter) (P0)
  - Acceptance: `alembic upgrade head` creates all tables
  - Files: app/main.py, app/models.py, alembic/versions/0001_initial.py
- [ ] Task 2: POST /books/youtube creates a Book row (P0)
  - Acceptance: posting a playlist URL returns 201 with a book id
  - Files: app/routers/books.py, app/schemas.py
- [ ] Task 3: Wire BullMQ + Redis, run_book job calls ai_llm's graph.py (P0)
  - Acceptance: queuing a job runs the ai_llm pipeline via asyncio.to_thread() and updates the Book row on completion
  - Files: app/queue.py, app/jobs/run_book.py
- [ ] Task 4: GET /books/{id} reports status from the LangGraph checkpoint (P0)
  - Acceptance: status reflects the current phase (A-E) while a job is running
  - Files: app/routers/books.py
- [ ] Task 5: GET /books/{id}/outline and PUT /books/{id}/outline (P1)
  - Acceptance: GET returns outline.json content; PUT persists edits and reruns the order checker
  - Files: app/routers/outline.py
- [ ] Task 6: POST /books/{id}/retry re-queues only failed chapters (P1)
  - Acceptance: retry does not re-run chapters that already passed verify
  - Files: app/jobs/retry_book.py
- [ ] Task 7: Add /health endpoint and structured JSON logging (P1)
  - Acceptance: /health returns 200 with DB + Redis connectivity check; logs include book_id/step
  - Files: app/routers/health.py, app/logging.py
```
