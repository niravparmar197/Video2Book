# Video2Book — Project Reference

Video2Book turns YouTube videos (single links or a playlist, up to 30 hours) into a well-organized PDF book: notes, screenshots, tables, diagrams, charts, TOC, glossary, and two indexes.

This file is the shared source of truth. Each subproject also has its own `AGENTS.md` with stack-specific rules that build on this one.

## Build order — do not skip ahead

1. **Core engine** (`ai_llm/`) — video in, PDF out, run from the command line. No web app, no database, no queue. Get PDF quality right before building a product around it.
2. **Backend** (`backend/`) — FastAPI + PostgreSQL + BullMQ, wraps the core engine's `graph.py` behind an API and a job queue.
3. **Frontend** (`frontend/`) — Next.js web app on top of the backend API.

Do not add API, database, or queue code into `ai_llm/` — it must keep working standalone from the CLI. `backend/` must not reimplement pipeline logic — it imports and calls the core engine.

## Repo layout

```
Video2Book/
├── ai_llm/     # Core Python engine: LangGraph pipeline, yt-dlp, ffmpeg, LLM calls, LaTeX -> PDF
├── backend/    # FastAPI + PostgreSQL + BullMQ, wraps ai_llm's graph.py (built after the core works)
├── frontend/   # Next.js + Tailwind web app (built after the backend exists)
```

## Non-negotiable decisions

| Area | Decision | Why |
|---|---|---|
| Video input | Stream mode by default, no video file saved; download only as a fallback | A 30h video would need 15-45GB to store |
| Screenshots | One per scene change, not on a timer | A timer gives ~720 near-duplicate images/hour |
| Transcript | YouTube captions first, then Whisper on audio only | Captions are free and instant |
| Long videos | Everything runs in 30-minute chunks | One design works for 10 minutes and 30 hours |
| Book planning | Plan the whole book before writing any chapter | Merges repeated topics and orders them correctly |
| Book order | `topic` mode (needs-based) or `video` mode (original order) | Mixed playlists need topic order; clean courses keep video order |
| LaTeX | AI writes Markdown/JSON only; templates build the LaTeX | Prevents most compile errors |
| Quality | Every chapter is verified; only weak sections are refined, max 3 tries | Better quality at lower cost |
| Crash safety | Every step saves to disk; `--resume` continues | Long jobs must never restart from zero |
| Cost | NVIDIA Nemotron (primary, free) + Gemini (fallback, free); Claude has no runtime API key | The core costs $0 to run |
| Tests | Unit tests from the start | Catch bugs before burning rate limits, not to save money — the LLM calls are free |

"Core is done" means: a 10-video playlist becomes a clean PDF with no manual fixes; a playlist with repeated topics gives a book with no repeated sections; a 30-hour playlist finishes overnight within budget.

## LLM provider chain

- **Primary — NVIDIA NIM**: `nvidia/nemotron-3-super-120b-a12b` for writing/judging, `nvidia/nemotron-3-nano-omni` for vision. Free, 40 RPM, no published daily cap.
- **Fallback — Google Gemini**: `gemini-3.8-flash` for the same jobs. Free, ~10 RPM, daily cap resets midnight Pacific.
- Any primary error (rate limit, timeout, 5xx) retries the same request on the fallback, independently per call type (writer / judge / vision). If both fail, retry with backoff, then mark the step failed and let `--resume` pick it up.
- Claude is **not** a runtime option right now — no API key is available. `LLM_PROVIDER` / `LLM_FALLBACK_PROVIDER` can point at `claude` later if a key is added. Claude Code is used only to write this app's own code, never called from inside the app.
- Both free tiers may use traffic to improve their models — fine for public videos; use a paid tier before ever processing private content.

## Rules for every AI-writing step

- Facts only from the transcript and screenshots — never invent numbers.
- Never force a table, diagram, or chart into a section that doesn't need one.
- The AI never writes raw LaTeX — it writes Markdown/JSON; templates render `.tex`.
- Judge score must be ≥ `PASS_SCORE` (7) or the section is refined, up to `MAX_REFINE_ATTEMPTS` (3) tries.

## Testing rules (all subprojects)

- Never call a real LLM, YouTube, or paid API from a unit test — mock or stub it.
- A prompt or model change is not done until it has run against the LangSmith eval set (`EVAL_DATASET_NAME`) without the average judge score dropping — `EVAL_ON_RELEASE=true` blocks a release otherwise.

## Settings (`.env`), abridged — see `ai_llm/AGENTS.md` for the full list

```
VIDEO_MODE=stream             # stream | download | captions_only
CHUNK_MINUTES=30
TRANSCRIPT_SOURCE=auto        # auto | captions | whisper
LLM_PROVIDER=nvidia
LLM_FALLBACK_PROVIDER=gemini  # claude | gemini | nvidia — claude needs a key you don't have yet
BOOK_ORDER=topic              # topic | video
REVIEW_OUTLINE=true
PASS_SCORE=7
MAX_REFINE_ATTEMPTS=3
MAX_BOOK_HOURS=30
MAX_BOOK_COST_USD=50
```

## Milestones (core, ~7 weeks)

1. Setup + CLI (`--estimate`, `videos.json`)
2. Text-only PDF (`captions_only` mode)
3. Better writing + book plan (`outline.py`, `--plan-only`, repeated topics merged)
4. Screenshots (stream mode, dedupe)
5. Diagrams / tables / charts + verify loop
6. Full book (glossary, subject + topic index, volumes) — 10-video playlist → clean PDF
7. Scale test: 2h → 8h → 15h → 30h playlist, overnight, within budget

## Production readiness

Before `backend/`/`frontend/` go live with real users, every item in the checklist in `backend/AGENTS.md` must hold. It is a gate, not a suggestion.
