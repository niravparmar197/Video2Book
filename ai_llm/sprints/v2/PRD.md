# Sprint v2 — PRD: Playlist Support + Book Plan (video order)

## Overview

Extend the v1 single-video pipeline to a full playlist: fetch every video in
order, run chunk/topics/write per video, then introduce `outline.py` to turn
the per-video notes into a reviewable book plan (`--plan-only`) and compile
all chapters into one multi-chapter `book.pdf` with a table of contents. This
sprint targets `BOOK_ORDER=video` only — chapters stay in original playlist
order, one chapter per video. Merging repeated topics across videos
(`BOOK_ORDER=topic`, `needs`/`level` sorting, cycle-breaking) is explicitly
deferred to a later sprint. This is the rest of Milestone 3 from the root
`AGENTS.md` roadmap, scoped down to the simpler ordering mode.

## Goals

- A playlist URL resolves to an ordered list of videos; a single video URL
  still works (list of 1), so v1 behavior isn't broken
- Every video in the playlist runs through fetch → chunk → topics → write,
  producing per-video notes exactly as v1 did for one video
- `outline.py` builds `outline.json` (stable `chapter:<video_id>` ids, video
  order, title, `skip`/`locked` flags) and a human-readable `outline.md`
- `python -m app.cli <playlist url> --plan-only` stops after the outline is
  written — no writing beyond notes, no render, no compile
- Manual edits to `outline.json` (`skip: true`) are respected on the next run
  without needing to redo any cached fetch/chunk/topics/notes work
- `book.pdf` contains one chapter per non-skipped video, in playlist order,
  with a table of contents
- `--resume` continues a playlist run that was interrupted partway through,
  without re-processing videos that already finished
- `--estimate` reports a per-video and total cost/time estimate for the whole
  playlist, not just one video

## User Stories

- As the operator, I want to point the CLI at a playlist URL and get one PDF
  book, so I don't have to run the tool once per video and stitch PDFs myself
- As the operator, I want `--plan-only` to show me the chapter order before
  any writing happens, so I can drop a video I don't want in the book
- As the operator, I want to edit `outline.json` to skip one video and re-run,
  so I don't have to re-fetch or re-write videos I'm keeping
- As the operator, I want `--estimate` to total the whole playlist, so I know
  the cost/time commitment before running a 10-video playlist
- As the operator, I want `--resume` to work across a whole playlist, so an
  interruption on video 7 of 10 doesn't waste the first 6

## Technical Architecture

**Stack**: unchanged from v1 — Python, LangGraph + SqliteSaver, LangChain
(NVIDIA NIM primary / Gemini fallback), yt-dlp, Pandoc + Jinja2 + LuaLaTeX +
latexmk, pytest.

```
                 ┌─────────────┐
 playlist URL ─▶ │   cli.py    │  --estimate | --plan-only | --resume
                 └──────┬──────┘
                        ▼
                 ┌─────────────┐
                 │  graph.py   │  LangGraph, SqliteSaver checkpoints
                 └──────┬──────┘
                        ▼
              per video in playlist order:
        fetch → chunk → topics → write   (v1 nodes, looped)
                        │
                        ▼
                 nodes/outline.py   (video order, stable chapter ids,
                                      outline.json + outline.md)
                        │
                 [--plan-only stops here; user edits outline.json]
                        │
                        ▼
                 render (per non-skipped chapter) → latex/tex.py
                        │
                        ▼
              main.tex.j2 (TOC + \input each chapter) → latexmk → book.pdf
```

**Data flow**: `videos.json` (now a list, one entry per playlist video) →
per-video `work/chunks/`, `work/topics/`, `work/notes/<video_id>.md` (v1
pipeline, unchanged, just looped) → `outline.json` / `outline.md` (chapter
order + skip/locked flags) → `chapters/<video_id>.tex` (one per non-skipped
chapter) → `main.tex` (Jinja2, includes chapters in outline order, generates
a TOC) → `book.pdf` (latexmk). Everything still lands under
`output/<book>/` so `cache.py` and the SqliteSaver checkpoint keep working
exactly as in v1, just iterated per video.

**Test playlist** for acceptance criteria: the first 3 videos of 3Blue1Brown's
"Neural Networks" playlist
(`https://www.youtube.com/playlist?list=PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi`) —
`aircAruvnKk` (chapter 1, the v1 test video), `IHZwWFHWa-w` (chapter 2),
`Ilg3gGewQ5U` (chapter 3). All three confirmed to have English captions
(Task 1). Later end-to-end tasks (5, 6, 8) restrict to these first 3 videos
via yt-dlp's `playlist_items` / `playlistend` option, not the full playlist.

## Out of Scope (v3+)

- `BOOK_ORDER=topic`: merging repeated topics across videos, `needs`/`level`
  sorting, cycle-breaking and `order_log.txt` (Milestone 3 continuation)
- `order.py`'s auto-fixes beyond the simple `skip` flag (no reordering logic,
  no `locked` conflict resolution beyond "manual edits win")
- Screenshots, scene detection, diagrams, tables, charts (Milestone 4-5)
- Quality verify loop / judge scoring / refinement retries (Milestone 5)
- Glossary, subject/topic indexes, real front matter, volumes (Milestone 6)
- Whisper transcription fallback (captions-only, same as v1)
- Parallelizing per-video processing (sequential loop is fine at this scale)

## Dependencies

- v1 complete: fetch/chunk/topics/write/render nodes, `graph.py`, `cache.py`,
  `--resume` all working for a single video (done, sprints/v1)
- `NVIDIA_API_KEY` / `GOOGLE_API_KEY` already configured from v1
- LuaLaTeX + latexmk already installed (MiKTeX, from v1 Task 7)
- A 2-3 video test playlist with captions on every video, confirmed in Task 1
