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
# Sprint v1 — PRD: Submit + Track a Book

## Overview
Build the first Video2Book web screens: submit a YouTube link or playlist,
watch it run, and download the finished PDF — talking to the backend's
/books/youtube, /books/{id}, /books/{id}/events, and /books/{id}/pdf endpoints.

## Goals
- User can paste a link/playlist and start a book run
- Status page shows the current phase (A-E) and per-chapter progress live
- Finished book can be downloaded as a PDF
- Failed chapters can be retried from the status page

## User Stories
- As a user, I want to paste a playlist link and start a run, so I don't need the CLI
- As a user, I want to see live progress, so I know a 30-hour run hasn't stalled
- As a user, I want to download the PDF as soon as it's ready, so I can read it

## Technical Architecture
- **Frontend**: Next.js + Tailwind CSS
- **Backend**: calls the existing FastAPI service in `backend/` (no new API code here)
- **Live progress**: polls or streams GET /books/{id}/events

## Out of Scope (v2+)
- Outline review/reordering screen (needs PUT /books/{id}/outline, later sprint)
- Login/auth (backend auth not built yet)
- Multi-book dashboard / history view

## Dependencies
- backend/ sprint v1 shipped: POST /books/youtube, GET /books/{id}, GET /books/{id}/pdf, POST /books/{id}/retry
```

### sprints/v1/TASKS.md

```markdown
# Sprint v1 — Tasks

## Status: In Progress

- [ ] Task 1: Initialize Next.js project with Tailwind (P0)
  - Acceptance: `npm run dev` starts without errors, Tailwind classes render
  - Files: package.json, tailwind.config.ts, app/layout.tsx
- [ ] Task 2: Submit form — link/playlist input, calls POST /books/youtube (P0)
  - Acceptance: submitting a valid URL redirects to /books/[id] with a real book id
  - Files: app/page.tsx, components/submit-form.tsx
- [ ] Task 3: Status page polls GET /books/{id} and shows current phase (P0)
  - Acceptance: page shows phase A-E and updates without a manual refresh
  - Files: app/books/[id]/page.tsx, components/status-panel.tsx
- [ ] Task 4: Live progress via GET /books/{id}/events (P1)
  - Acceptance: per-chapter status updates as chapters finish, no full-page reload
  - Files: components/progress-feed.tsx
- [ ] Task 5: Download button — GET /books/{id}/pdf once status is complete (P0)
  - Acceptance: clicking Download saves a valid PDF file
  - Files: components/download-button.tsx
- [ ] Task 6: Retry button — POST /books/{id}/retry for failed chapters (P1)
  - Acceptance: clicking Retry on a failed chapter re-triggers only that chapter
  - Files: components/retry-button.tsx
- [ ] Task 7: Polish UI — loading states, empty states, responsive (P2)
  - Acceptance: no layout shifts, works on mobile, skeleton loaders while polling
  - Files: various component updates
```
