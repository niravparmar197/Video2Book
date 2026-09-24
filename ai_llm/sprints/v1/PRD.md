# Sprint v1 — PRD: CLI Setup + Text-Only PDF (captions_only)

## Overview

Stand up the `ai_llm/` core engine skeleton and turn one short YouTube video into a
readable, text-only PDF chapter using `VIDEO_MODE=captions_only` — no screenshots,
diagrams, tables, or multi-video book planning yet. This is Milestones 1-2 from the
root `AGENTS.md` roadmap: get the CLI and the simplest possible video-to-PDF path
working end to end before adding visual richness or multi-video merging.

## Goals

- `python -m app.cli <url> --estimate` prints a cost/time estimate with no LLM calls
- Video metadata + captions fetched via yt-dlp and saved to `videos.json`
- Transcript chunked into 30-minute segments (`CHUNK_MINUTES=30`)
- Topics extracted per chunk by the writer LLM, with NVIDIA → Gemini fallback on error
- Chapter notes (Markdown, facts-only) written per video and rendered into a
  compiling `.tex` chapter via Jinja2 templates — the AI never writes raw LaTeX
- `python -m app.cli <url>` produces `output/<book>/book.pdf` for a single video
- Every finished step is cached to disk; `--resume` continues an interrupted run
  without re-calling the LLM for already-completed steps

## User Stories

- As the operator, I want `--estimate` to tell me the cost/time before committing,
  so I don't burn API calls or LaTeX compile time on a video I don't want to process
- As the operator, I want one command to turn a video URL into a PDF, so I can check
  book quality on a single video before trying a playlist
- As the operator, I want the fallback provider (Gemini) to kick in automatically
  when NVIDIA errors or rate-limits, so a transient failure doesn't stall a run
- As the operator, I want every finished chunk/topics/notes step cached to disk, so
  a crash or interruption doesn't waste already-completed LLM calls
- As the operator, I want `--resume` to pick up exactly where a run stopped, so long
  jobs never restart from zero

## Technical Architecture

**Stack**: Python, LangGraph + SqliteSaver, LangChain (NVIDIA NIM primary /
Gemini fallback), yt-dlp, Pandoc + Jinja2 + LuaLaTeX + latexmk, pytest.

```
                 ┌─────────────┐
  video URL ───▶ │   cli.py    │  --estimate | --plan-only | --resume
                 └──────┬──────┘
                        ▼
                 ┌─────────────┐
                 │  graph.py   │  LangGraph, SqliteSaver checkpoints
                 └──────┬──────┘
        ┌───────────────┼───────────────────────────────┐
        ▼               ▼               ▼               ▼
  nodes/fetch.py   nodes/chunk.py   nodes/topics.py  nodes/write.py
  (yt-dlp,          (30-min          (LLM: NVIDIA      (LLM: NVIDIA
   captions)         segments)        → Gemini)         → Gemini)
        │               │               │               │
        └───────────────┴───────────────┴───────┬───────┘
                                                  ▼
                                          latex/tex.py
                                     (Jinja2 → chapter.tex.j2)
                                                  │
                                                  ▼
                                      latexmk → book.pdf
```

**Data flow**: `videos.json` (metadata + captions path) → `work/chunks/*.json`
(30-min transcript segments) → `work/topics/*.json` (per-chunk topics) →
`work/notes/*.md` (per-video Markdown notes, facts-only) → `chapters/<id>.tex`
(Jinja2-rendered) → `book.pdf` (latexmk). Every stage writes to `output/<book>/`
so `cache.py` can skip finished steps and `--resume` can continue after a crash.

**Test video** for acceptance criteria: `https://www.youtube.com/watch?v=aircAruvnKk`
("But what is a neural network?", 3Blue1Brown, ~19 min, has captions) — under
`CHUNK_MINUTES=30` this yields exactly 1 chunk, keeping the pipeline simple to verify.

## Out of Scope (v2+)

- Playlists / multiple videos in one book (single video only this sprint)
- Screenshots, scene detection, diagrams, tables, charts (Milestones 4-5)
- Book planning / outline merge across repeated topics (`outline.py`, Milestone 3)
- `order.py` topic ordering, `needs`/`level` sorting, manual `outline.json` edits
- Quality verify loop / judge scoring / refinement retries (Milestone 5)
- Whisper transcription fallback (captions-only for now; `TRANSCRIPT_SOURCE=captions`)
- Glossary, indexes, front matter, volumes (Milestone 6)
- Batches API (`batch.py`) — synchronous LLM calls only this sprint

## Dependencies

- `NVIDIA_API_KEY` and `GOOGLE_API_KEY` (Gemini) — not yet set up; Task 1 creates
  `.env.example` documenting both, and the user adds real keys before Task 5 runs live
- yt-dlp + Deno installed and on PATH for caption/metadata fetch
- LuaLaTeX + latexmk installed for the compile step (Task 7 onward)
- Test video confirmed to have YouTube captions available:
  `https://www.youtube.com/watch?v=aircAruvnKk`
