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
Built the first Video2Book web flow: submit a link, watch live progress
across phases A-E, download the finished PDF, and retry a failed chapter.
Talks only to the existing backend/ FastAPI service, no new API code.

## Architecture Overview

┌─────────────────────────────────────────────────────┐
│ Browser                                              │
│                                                       │
│  / ──▶ /books/[id] ──▶ backend GET /books/{id}       │
│              │                                       │
│              ├─ StatusPanel (phase A-E)              │
│              ├─ ProgressFeed (GET .../events)        │
│              ├─ DownloadButton (GET .../pdf)         │
│              └─ RetryButton (POST .../retry)         │
└──────────────────────┬────────────────────────────────┘
                        │
                        ▼
              backend/ FastAPI service (see backend
              sprint v1 walkthrough for what's behind it)

## Files Created/Modified

### app/page.tsx
**Purpose**: Landing page with the submit form.

**Key Components**:
- `SubmitForm` — validates a YouTube URL client-side, POSTs to /books/youtube, redirects to /books/[id]

### app/books/[id]/page.tsx
**Purpose**: Status page for one book run.

**Key Components**:
- `StatusPanel` — polls GET /books/{id} every few seconds, shows the current phase
- `ProgressFeed` — subscribes to GET /books/{id}/events for per-chapter updates
- `DownloadButton` — appears once status is complete, links to GET /books/{id}/pdf

**How it works**:
The page polls status on an interval rather than holding a permanent
connection open, since a 30-hour run can span a browser restart. ProgressFeed
reconciles against the same book id so a page refresh mid-run picks up
exactly where the last view left off.

[... continues for each file ...]

## Data Flow

1. User pastes a link on / → SubmitForm POSTs to backend /books/youtube → redirect to /books/[id]
2. StatusPanel polls GET /books/{id} → shows current phase (A-E)
3. ProgressFeed reads GET /books/{id}/events → per-chapter status as chapters finish
4. Once status is "complete", DownloadButton enables → GET /books/{id}/pdf → browser downloads
5. If a chapter fails, RetryButton calls POST /books/{id}/retry → only that chapter re-runs

## Test Coverage
- Unit: 3 tests — URL validation, phase-label mapping, retry button enabled/disabled state
- Integration: 0 (backend is mocked at the fetch layer for these tests)
- E2E: 4 Playwright tests — submit → status page renders, progress feed updates on a mocked event stream, download link appears on complete, retry button re-triggers a failed chapter

## Known Limitations
- No login — anyone with a book's URL can view or retry it
- No outline review screen yet — order.json can't be edited from the UI
- No book history/dashboard — a book is only reachable by its direct link

## What's Next
v2 should add the outline review screen (backed by GET/PUT /books/{id}/outline)
and auth, once backend/ ships those endpoints.
```
