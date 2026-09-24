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

## Eval Results
[Only if this sprint touched prompts (`app/prompts/*.md`) or model/provider config.
Report the LangSmith eval set (`EVAL_DATASET_NAME`) average judge score before and
after the change, and note whether `EVAL_ON_RELEASE=true` passed. Omit this section
entirely if no prompt or model change was made.]

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
- Include the "Eval Results" section whenever a task in this sprint touched `app/prompts/` or model config; omit it otherwise.
- Architecture diagram MUST be ASCII art (works everywhere).
- The walkthrough should be self-contained — reader shouldn't need to open source files.

## Example Output

### sprints/v1/WALKTHROUGH.md

```markdown
# Sprint v1 — Walkthrough

## Summary
Built the captions_only pipeline end to end: fetch video metadata + captions,
chunk into 30-minute segments, extract topics, write chapter notes, and
render a compiling .tex chapter. NVIDIA is primary, Gemini is the automatic
fallback on any writer/judge error.

## Architecture Overview

┌─────────────────────────────────────────────────────┐
│ CLI: python -m app.cli <url>                         │
│                                                       │
│  fetch.py ──▶ chunk.py ──▶ topics.py ──▶ write.py    │
│                                              │        │
│                                              ▼        │
│                                          render.py    │
│                                              │        │
│                                              ▼        │
│                                        latex/tex.py   │
└──────────────────────┬────────────────────────────────┘
                        │
           ┌────────────┴────────────┐
           ▼                         ▼
   ┌────────────────┐       ┌─────────────────┐
   │  NVIDIA NIM     │──────▶│  Gemini (fallback)│
   │  (writer/judge) │       │  on error/limit   │
   └────────────────┘       └─────────────────┘

## Files Created/Modified

### app/nodes/fetch.py
**Purpose**: Fetch video metadata and captions via yt-dlp, write videos.json.

**Key Functions**:
- `fetch_video(url)` — pulls title, duration, channel, caption track
- `write_videos_json(videos)` — persists the ordered video list

### app/nodes/chunk.py
**Purpose**: Split a transcript into 30-minute chunks with timestamps preserved.

**Key Functions**:
- `chunk_transcript(transcript, minutes=30)` — yields chunk dicts with start/end times

**How it works**:
The transcript's timestamped segments are walked in order and grouped once
the running duration crosses `CHUNK_MINUTES`. Each chunk is written to
`work/<video_id>/chunk_NN/transcript.json` so a later step (or --resume) can
pick up a single chunk without re-reading the whole transcript.

[... continues for each file ...]

## Data Flow

1. `python -m app.cli <url>` → fetch.py pulls metadata + captions → videos.json
2. chunk.py splits the transcript into 30-minute chunks under work/
3. topics.py calls the writer LLM per chunk (NVIDIA, falls back to Gemini on error) → topics saved per chunk
4. write.py turns topics + transcript into Markdown chapter notes
5. render.py + latex/tex.py render the notes into a compiling chapters/<video>.tex
6. cache.py marks each finished step so a re-run or --resume skips it

## Test Coverage
- Unit: 5 tests — chunk boundaries, videos.json shape, NVIDIA→Gemini fallback (mocked), cache skip logic
- Integration: 0 (planned for a later sprint, once outline.py exists)
- Compile test: 1 — fake chunk data always produces a compiling chapter

## Security Measures
- No API keys committed; NVIDIA_API_KEY/GOOGLE_API_KEY read from .env
- bandit and pip-audit run clean on app/

## Known Limitations
- No screenshots, diagrams, or charts yet (later sprint)
- No multi-video outline/merge — one chapter per video only
- Whisper fallback not wired up — captions-only videos required for this sprint

## What's Next
v2 should add outline.py/order.py to plan a whole book across multiple
videos and merge repeated topics, per the Week 3 milestone.
```
