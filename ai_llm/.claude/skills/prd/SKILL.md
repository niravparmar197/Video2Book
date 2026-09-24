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
# Sprint v1 — PRD: Text-Only PDF (captions_only)

## Overview
Turn one short YouTube video into a readable text-only PDF chapter using
VIDEO_MODE=captions_only — no screenshots, diagrams, or multi-video planning yet.

## Goals
- Video metadata + captions fetched and saved to videos.json
- Transcript chunked into 30-minute segments
- Topics extracted per chunk by the writer LLM
- One .tex chapter written per video and compiled with latexmk
- LLM calls fall back from NVIDIA to Gemini automatically on error

## User Stories
- As the operator, I want one command to turn a video URL into a PDF, so I can check book quality
- As the operator, I want the fallback provider to kick in automatically, so a rate limit doesn't stall a run
- As the operator, I want every finished chunk cached to disk, so a crash doesn't waste API calls

## Technical Architecture
- **Language**: Python
- **Orchestration**: LangGraph + SqliteSaver
- **AI calls**: LangChain, NVIDIA NIM primary (nemotron writer/judge), Gemini fallback
- **YouTube**: yt-dlp, captions_only mode (no video download)
- **Book build**: Pandoc + Jinja2 + LuaLaTeX + latexmk

## Out of Scope (v2+)
- Screenshots, diagrams, charts
- Multi-video book planning / outline merge (order.py, outline.py)
- Whisper transcription (captions only for now)

## Dependencies
- NVIDIA_API_KEY and GOOGLE_API_KEY set in .env
- 5 test videos picked (Week 1 setup)
```

### sprints/v1/TASKS.md

```markdown
# Sprint v1 — Tasks

## Status: In Progress

- [ ] Task 1: Set up captions_only fetch + videos.json (P0)
  - Acceptance: running the CLI on one video URL writes videos.json with title, duration, captions path
  - Files: app/nodes/fetch.py, app/youtube.py
- [ ] Task 2: Chunk transcript into 30-minute segments (P0)
  - Acceptance: a 90-minute transcript produces 3 chunk files under work/
  - Files: app/nodes/chunk.py
- [ ] Task 3: Extract topics per chunk via the writer LLM (P0)
  - Acceptance: each chunk gets a topics list; a simulated NVIDIA rate-limit error falls back to Gemini
  - Files: app/nodes/topics.py, app/prompts/topics.md
- [ ] Task 4: Write chapter notes from chunk topics (P0)
  - Acceptance: one Markdown notes file per video, facts only from the transcript
  - Files: app/nodes/write.py, app/prompts/write_notes.md
- [ ] Task 5: Render notes to a compiling .tex chapter (P0)
  - Acceptance: latexmk compiles chapters/<video>.tex with no errors
  - Files: app/latex/tex.py, app/latex/templates/chapter.tex.j2
- [ ] Task 6: Wire cache.py so a re-run skips finished chunks (P1)
  - Acceptance: re-running the same video URL does not re-call the LLM for an already-cached chunk
  - Files: app/cache.py
- [ ] Task 7: Add --estimate cost/time output (P1)
  - Acceptance: `python -m app.cli <url> --estimate` prints a token/time estimate without calling the writer LLM
  - Files: app/estimate.py, app/cli.py
```
