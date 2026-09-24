# Sprint v3 — PRD: Topic-Order Book Planning (BOOK_ORDER=topic)

## Overview

Implement the other half of Milestone 3, explicitly deferred from v2:
`BOOK_ORDER=topic`. Where v2 gives one chapter per video in playlist order,
v3 merges repeated topics across the whole playlist into single sections —
each written once from every video that covers it — and orders those
sections by prerequisite (`needs`) and difficulty (`level`), not by upload
order. This is the "10-video playlist with repeated topics gives a book with
no repeated sections" outcome the root `AGENTS.md` "Core is done" bar names
directly.

## Goals

- A new LLM call reviews every chunk's extracted topics across the entire
  playlist and merges the ones that are the same underlying topic, even
  when videos phrase it differently (e.g. "gradient descent" vs. "how
  neural nets learn")
- Every merged topic gets a `needs` list (prerequisite topics) and a
  `level` (1-5 difficulty); a topic never appears before a topic it needs,
  and easier topics come before harder ones
- Cycles in `needs` are broken automatically (weakest link removed, easier
  topic placed first) and logged to `order_log.txt` — never silently dropped
- Each merged topic becomes ONE section, written once from ALL of its
  source videos' relevant chunks — not duplicated per video
- `outline.json`/`outline.md` (from v2) now list topic-based chapters when
  `BOOK_ORDER=topic`, with the same stable-id, `skip`/`locked`, `--plan-only`
  review flow v2 already built — reused, not reinvented
- `BOOK_ORDER=video` (v2's existing behavior) keeps working unchanged;
  switching the `.env` setting is what selects the mode

## User Stories

- As the operator, I want a playlist where 3 different videos each cover
  "backpropagation" to produce ONE backpropagation section citing all 3, so
  the book isn't repetitive
- As the operator, I want prerequisite topics ordered before the topics
  that depend on them, so the book reads as a coherent course, not a
  shuffled video list
- As the operator, I want a circular dependency between topics to be
  resolved automatically and logged, so a weird edge case never crashes a
  30-hour run
- As the operator, I want `BOOK_ORDER=video` to keep behaving exactly like
  v2, so switching this sprint's work on doesn't regress the simpler mode

## Technical Architecture

**Stack**: unchanged — Python, LangGraph + SqliteSaver, LangChain (NVIDIA
NIM primary / Gemini fallback), Jinja2 + LuaLaTeX + latexmk, pytest.

```
        topics (unchanged, per chunk, v1)
                    │
                    ▼
         nodes/plan.py — run_plan_topics()
   LLM merges/clusters topics across the WHOLE
   playlist from {video_id, chunk_index, topics}
   only (no transcript text — cheap, fast) into
   [{title, needs: [...], level, sources: [...]}]
                    │
                    ▼
         nodes/order.py — order_topics()
   topological sort on needs, ties broken by
   level then earliest source appearance;
   cycles broken (weakest link) + order_log.txt
                    │
                    ▼
      nodes/outline.py — run_topic_outline()
   same stable chapter:<slug> id + skip/locked
   preservation as v2's run_outline(), now over
   ordered topics instead of ordered videos
                    │
       [--plan-only stops here, same as v2]
                    │
                    ▼
      nodes/write.py — run_write_topic()
   ONE section per topic, synthesized from every
   source chunk's transcript text across videos
   (new prompt: write_topic_notes.md)
                    │
                    ▼
   render (v2, unchanged) — render_chapter/render_book
   keyed by chapter id (topic slug instead of video_id)
```

**Data flow**: `work/topics/<video_id>_<chunk>.json` (v1, per chunk, all
videos) → `plan.json` (merged topics: title, needs, level, sources) →
`ordered_plan.json` + `order_log.txt` (topological order, cycle fixes
logged) → `outline.json`/`outline.md` (v2's format, chapter id =
`chapter:<topic-slug>`) → `work/notes/topic_<slug>.md` (one per merged
topic, multi-source) → `chapters/<slug>.tex` → `main.tex` (v2, unchanged) →
`book.pdf`.

`BOOK_ORDER` (already a config setting since v1, currently unused) selects
which node set `graph.py` builds: `video` uses v2's existing
outline/write path unchanged; `topic` uses the new plan/order/write_topic
path described above. Both converge on the same render step.

**Test playlist**: the v2 3-video test playlist doesn't share topics
between videos (each 3Blue1Brown chapter is distinct), so it can't exercise
a real merge. Picked for v3: 3Blue1Brown's "Essence of Linear Algebra"
playlist (`https://www.youtube.com/playlist?list=PLZHQObOWTQDPD3MizzM2xVFitgF8hE_ab`),
chapters 1-3 — `fNk_zzaMoSs` (Vectors), `k7RM-ot2NWY` (Linear combinations,
span, and basis vectors), `kYB8IZa5AuE` (Linear transformations and
matrices). Chapters 2 and 3 both substantively cover basis vectors / linear
transformations, so real chunk-level topic extraction is likely to produce
a genuine cross-video overlap for the merge step to collapse.
**Live verification blocked as of 2026-09-24**: YouTube's bot-detection
("Sign in to confirm you're not a bot") started rejecting all yt-dlp calls
from this session partway through v2/v3 work, including previously-working
v2 test videos — confirmed session-wide, not specific to this playlist.
Task 8's real end-to-end run should be attempted again once this clears;
until then, v3 tasks are verified via fully-mocked unit tests only, no real
YouTube fetch.

## Out of Scope (v4+)

- Screenshots, scene detection, diagrams, tables, charts (Milestone 4-5)
- Quality verify loop / judge scoring / refinement retries (Milestone 5)
- Glossary, subject/topic indexes, real front matter, volumes (Milestone 6)
- Transcript-aware topic clustering (the merge call sees topic labels only,
  not full transcript text, to stay cheap on a 30-hour playlist) — revisit
  if merge quality proves too coarse in practice
- Manual editing of `needs`/`level` in `outline.json` beyond the existing
  `skip`/`locked` fields (re-ordering by hand is not part of this sprint)
- Whisper transcription fallback (captions-only, unchanged)

## Dependencies

- v2 complete: playlist fetch, per-video chunk/topics, `outline.py`'s
  stable-id + skip/locked preservation, `render_book`/`main.tex.j2` TOC
  compile, `--plan-only`, playlist `--resume` (all done, sprints/v2)
- `BOOK_ORDER` config setting already exists (`app/config.py`, default
  `"topic"`) but is not yet read by `graph.py` — this sprint is what makes
  it do something
- A test playlist with at least one genuinely repeated topic across 2+
  videos, picked in Task 1
