---
name: walkthrough
description: Generate a comprehensive sprint review report documenting exactly what was built. Use when the user wants a walkthrough, sprint review, or documentation of completed work — including phrases like "generate the walkthrough", "document this sprint", "what did we build", or "/walkthrough".
---

# `/walkthrough` — Sprint Review Report

You are a technical writer generating a sprint review report. Your job is to read all code produced in the current sprint and create a comprehensive, human-readable walkthrough document.

## Process

### Step 1: Identify the Sprint

Find the latest `sprints/vN/` directory. Read:
- `PRD.md` — what was planned
- `TASKS.md` — what tasks were attempted

### Step 2: Inventory All Changes

Use git to find all files created or modified in this sprint:

```bash
# If tasks have commits tagged to this sprint
git log --oneline --name-only
```

Or read the `TASKS.md` completed entries for the file list.

### Step 3: Generate WALKTHROUGH.md

Write `sprints/vN/WALKTHROUGH.md` with this structure:

```markdown
# Sprint vN — Walkthrough

## Summary
[2-3 sentence summary of what this sprint accomplished]

## Architecture Overview
[ASCII diagram showing the main components and how they connect]

## Files Created/Modified

### [filename.ext]
**Purpose**: [What this file does in 1 sentence]

**Key Functions/Components**:
- `functionName()` — [What it does]
- `ComponentName` — [What it renders/handles]

**How it works**:
[2-3 paragraph plain English explanation. Include relevant code snippets
for the most important logic. Explain WHY, not just WHAT.]

[Repeat for each file]

## Data Flow
[Describe how data moves through the application. Example: "User submits
login form → API route validates credentials → NextAuth creates session
→ Redirect to dashboard → Dashboard fetches metrics from /api/metrics
→ Renders charts"]

## Test Coverage
[List all tests and what they verify]
- Unit: [N tests] — [what they cover]
- Integration: [N tests] — [what they cover]
- E2E: [N tests] — [what they cover]

## Security Measures
[List security features implemented in this sprint]

## Known Limitations
[Be honest about what's missing, hacky, or could be improved]

## What's Next
[Based on the limitations and PRD trajectory, suggest v(N+1) priorities]
```

## Rules

- Write for a developer who has NEVER seen this codebase.
- Include actual code snippets for complex logic (5-10 lines, not entire files).
- Every file gets its own section.
- Be honest about limitations — don't oversell.
- Use the same terminology as the PRD.
- Architecture diagram MUST be ASCII art (works everywhere).
- The walkthrough should be self-contained — reader shouldn't need to open source files.

## Example Output

### sprints/v1/WALKTHROUGH.md

```markdown
# Sprint v1 — Walkthrough

## Summary
Wrapped the ai_llm core pipeline behind a FastAPI service: POST /books/youtube
queues a run_book job on BullMQ + Redis, the job runs ai_llm's graph.py in a
worker thread, and Postgres tracks book/video/chapter status so GET /books/{id}
reflects live progress.

## Architecture Overview

┌─────────────────────────────────────────────────────┐
│ Client                                               │
│                                                       │
│  POST /books/youtube ──▶ Book row created            │
│                              │                        │
│                              ▼                        │
│                        BullMQ queue (Redis)           │
│                              │                        │
│                              ▼                        │
│                   run_book job (asyncio.to_thread)    │
│                              │                        │
│                              ▼                        │
│                   ai_llm.app.graph (LangGraph)         │
│                              │                        │
│                              ▼                        │
│               Postgres checkpointer + Book/Chapter rows│
└──────────────────────┬────────────────────────────────┘
                        │
                        ▼
              GET /books/{id} ── status from checkpoint

## Files Created/Modified

### app/models.py
**Purpose**: SQLAlchemy models for the API's own state, separate from ai_llm's JSON files.

**Models**:
- `Book` — id, source_url, status, cost_estimate, created_at
- `Video` — id, book_id, title, duration, order
- `Chapter` — id, book_id, video_id, status, score, attempts

### app/jobs/run_book.py
**Purpose**: BullMQ job handler that runs one book through the core pipeline.

**Key Functions**:
- `run_book(job)` — loads the Book row, calls `ai_llm.app.graph.run()` via `asyncio.to_thread()`, updates status on each phase transition

**How it works**:
The job never re-implements pipeline logic — it imports `graph.py` from
`ai_llm/` and drives it the same way the CLI does, just with a Postgres
checkpointer instead of SqliteSaver so status survives a worker restart.

[... continues for each file ...]

## Data Flow

1. Client calls POST /books/youtube with a playlist URL → Book row created, run_book job queued (jobId = book_id)
2. Worker picks up the job → calls ai_llm's graph.py in a background thread
3. Each LangGraph phase transition updates the Book/Chapter rows in Postgres
4. Client polls GET /books/{id} → current phase and per-chapter status returned
5. On failure, BullMQ retries up to 3 times with a 5-min lock before marking the job failed
6. POST /books/{id}/retry re-queues only the chapters that never passed verify

## Test Coverage
- Unit: 6 tests — model validation, job payload shape, retry-only-failed logic
- Integration: 3 tests — FastAPI TestClient against POST/GET /books, using a test-container Postgres (not mocked)
- E2E: 0 (planned once the frontend exists)

## Security Measures
- No API keys committed; NVIDIA/Gemini/LangSmith keys read from env
- bandit and pip-audit run clean on app/
- No auth yet — flagged as a known limitation, not deferred silently

## Known Limitations
- No auth/login — anyone with the URL can query any book
- No inbound rate limiting yet — one user could exhaust the shared LLM quota
- Outline review endpoints (GET/PUT /books/{id}/outline) not yet built
- No Sentry/error tracking wired up yet

## What's Next
v2 should add outline review endpoints, inbound rate limiting, and auth —
required before the frontend sprint can build the outline-review screen.
```
