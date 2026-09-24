# Sprint v4 — PRD: Screenshots (stream mode, scene-change dedupe)

## Overview

Implement Milestone 4: one screenshot per scene change (never on a timer),
captured by scanning the video stream directly with ffmpeg — no full video
file saved — with a chunk-scoped download fallback if the stream read
fails. Deduped screenshots (near-duplicate + blank-frame filtering via
imagehash/Pillow) are embedded as figures at the end of the chapter/section
that covers their time range, in both `BOOK_ORDER` modes from v2/v3.

## Goals

- `VIDEO_MODE=stream` scans each 30-minute chunk's time range directly
  against a stream URL extracted by yt-dlp — no video file is ever saved
  to disk for `stream` mode
- Screenshots are taken on scene changes (ffmpeg scene-detection filter),
  not on a fixed timer — a static 20-minute lecture slide produces ~1
  screenshot, not 40
- If the stream read fails for a chunk (network hiccup, extractor issue),
  that chunk's video falls back to a scoped download (only that chunk's
  time range, not the whole video) and scene detection retries against the
  local file
- Near-duplicate and blank/solid-color frames are dropped
  (imagehash perceptual hash + a blank-frame check) before anything is
  saved as an asset
- Every chapter (video-mode) or topic section (topic-mode, v3) gets its
  covering time range's deduped screenshots appended as figures after its
  text, in timestamp order
- The whole frames step is cache-skippable like every other step
  (`work/frames/<video_id>_<chunk>.json`): a crash or re-run never re-scans
  a chunk whose screenshots are already on disk

## User Stories

- As the operator, I want screenshots captured without ever downloading a
  30-hour video, so a long playlist doesn't need 15-45GB of local storage
- As the operator, I want one screenshot per real scene change, so a static
  slide doesn't flood the book with 40 near-identical images
- As the operator, I want a stream failure to degrade to a scoped download
  instead of failing the whole chunk, so a flaky network doesn't lose
  screenshots for an otherwise-fine video
- As the operator, I want screenshots to land in the right chapter/section,
  so the book's figures actually correspond to what that section discusses

## Technical Architecture

**Stack**: adds ffmpeg (scene detection, frame extraction) and
imagehash + Pillow (dedupe) to the existing stack — both already listed in
`ai_llm/AGENTS.md`'s table, unused until now.

```
     chunk.py (v1, unchanged: start/end seconds per chunk)
                    │
                    ▼
         nodes/frames.py — run_frames()
   per chunk: ffmpeg scene-detection filter against
   a yt-dlp stream URL for that time range (no
   download); on failure, falls back to a
   yt-dlp scoped download of just that time range,
   then re-runs scene detection against the local file
                    │
                    ▼
        dedupe_frames() — imagehash (near-duplicate)
        + blank-frame filter (low pixel variance)
                    │
                    ▼
   assets/<video_id>/<chunk>_<scene_index>.jpg (kept)
   work/frames/<video_id>_<chunk>.json (path + timestamp)
                    │
                    ▼
   render_chapter() (v1/v2, extended) — appends a
   chapter's/topic's covering screenshots as
   \includegraphics figures after its text
```

**Data flow**: `work/chunks/<video_id>_<chunk>.json` (start/end seconds,
v1) → `work/frames/<video_id>_<chunk>.json` (list of `{asset_path,
timestamp_seconds}`) → `assets/<video_id>/*.jpg` (the kept, deduped
images) → `chapters/<id>.tex` (figures appended, via an extended
`render_chapter()`). `VIDEO_MODE=captions_only` skips the frames step
entirely (screenshots off); `VIDEO_MODE=stream`/`download` runs it.

**Chapter/topic association**: video-mode chapters already map 1:1 to a
video, so a chapter gets every one of that video's chunks' screenshots.
Topic-mode chapters (v3) get every screenshot from every chunk listed in
that topic's `sources`. Placement is at the end of the chapter/section
text (append, not inline) — matches the scope agreed for this sprint;
LLM-driven inline figure placement is a later-sprint refinement (closer to
Milestone 5's judgment/quality work).

## Out of Scope (v5+)

- Diagrams (Graphviz), charts (matplotlib), tables — Milestone 5
- Quality verify loop / judge scoring / refinement retries — Milestone 5
- LLM-driven screenshot relevance filtering or inline placement within a
  section (this sprint always appends, in timestamp order)
- Whisper transcription fallback (unchanged, captions-only)
- OCR or captioning of screenshot content

## Dependencies

- v1-v3 complete: chunk boundaries (`work/chunks/*.json`), both
  `BOOK_ORDER` modes' chapter/outline pipeline, `render_chapter`/
  `render_book`/`compile_chapter` (all done)
- ffmpeg installed and on PATH (scene detection + frame extraction)
- `imagehash` + `Pillow` added as dependencies (dedupe)
- A real test video confirmed to have actual scene changes (not a single
  static slide the whole way through), picked in Task 1: reusing the v1/v2
  test video `https://www.youtube.com/watch?v=aircAruvnKk` ("But what is a
  neural network?", 3Blue1Brown) — an animated math video with frequent
  visual cuts, a good scene-detection candidate distinct from a static
  slide deck.
