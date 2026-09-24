# Sprint v5 — PRD: Diagrams/Tables/Charts + Verify Loop

## Overview

Implement Milestone 5: sections get a table, diagram, or chart only when
the transcript content actually calls for one — never forced, never
invented data — and every written section is judged by a second LLM call;
anything scoring below `PASS_SCORE` is rewritten with the judge's feedback,
up to `MAX_REFINE_ATTEMPTS` tries, before the book moves on.

## Goals

- The writer LLM (already producing a section's Markdown, v1-v4) can
  additionally emit a table, a diagram, or a chart as a structured JSON
  block alongside its prose — one call per section, no extra pass — and
  never invents one when the content doesn't call for it
- `render.py` turns a table block into a LaTeX `tabular`, a diagram block
  into a Graphviz-rendered figure, and a chart block into a
  matplotlib-rendered figure from real transcript numbers only
- A new judge LLM call scores every written section (video-mode chapters
  and topic-mode sections alike) against `PASS_SCORE` (7); a section that
  scores below it is rewritten with the judge's feedback, up to
  `MAX_REFINE_ATTEMPTS` (3) tries, then kept as-is rather than blocking the
  book
- The whole write+verify+refine loop is cache-skippable and resume-safe,
  matching every other step's crash-safety rule (root `AGENTS.md`)
- `BOOK_ORDER=video` and `BOOK_ORDER=topic` both get the same verify loop,
  sharing one `verify.py` node — no mode-specific quality gate

## User Stories

- As the operator, I want a section with real statistics to get a chart
  instead of a wall of numbers in prose, so the book is actually readable
- As the operator, I want a section with no tabular/structural/procedural
  content to stay plain prose, so the book isn't cluttered with pointless
  visual aids
- As the operator, I want a weak section to be caught and rewritten
  automatically, so I don't have to manually proofread every chapter
  before the book ships
- As the operator, I want the refine loop to give up after 3 tries and
  keep the best attempt rather than looping forever or crashing the run,
  so quality control never turns into a stuck job

## Technical Architecture

**Stack**: adds Graphviz (`dot`) and matplotlib to the existing stack —
both already listed in `ai_llm/AGENTS.md`'s table, unused until now.

```
        write.py / write_topic (v1/v3, extended)
   writer LLM emits Markdown + optional structured
   ```table/```diagram/```chart fenced JSON blocks
                    │
                    ▼
   latex/tex.py's markdown_notes_to_sections()
   (extended) parses fenced blocks into each
   Section's `visuals: list[Visual]`
                    │
                    ▼
        nodes/render.py (new)
   table  -> escaped LaTeX \begin{tabular}...
   diagram -> Graphviz DOT -> `dot -Tpng` -> figure
   chart   -> matplotlib PNG (real numbers only) -> figure
                    │
                    ▼
        nodes/verify.py (new) -- run_verify()
   judge LLM scores the written section against
   the source transcript; score < PASS_SCORE loops
   write -> verify again (feedback appended to the
   write prompt) up to MAX_REFINE_ATTEMPTS, then
   keeps the last attempt regardless
                    │
                    ▼
   render_chapter() (v1/v2/v4, extended) -- tables
   inline, diagrams/charts as figures (same
   \includegraphics mechanism v4 built for
   screenshots) -> chapters/<id>.tex -> book.pdf
```

**Data flow**: `work/chunks/*.json` (v1) → write LLM call → Markdown +
optional visual JSON blocks → judge LLM call → `work/verify/<id>.json`
(score, feedback, attempt count) → refine loop (re-write with feedback) →
final `work/notes/<id>.md` (unchanged path/format from v1-v3, visuals
embedded as fenced blocks within it) → `render.py` parses + renders visuals
→ `assets/<video_id>/diagram_*.png` / `chart_*.png` (new, alongside v4's
screenshot assets) → `chapters/<id>.tex` → `book.pdf`.

## Out of Scope (v6+)

- A failed LaTeX compile triggering an automatic content retry (this
  sprint's verify loop judges content quality only, not compile success —
  compile failure still raises and stops the run, as it always has)
- Glossary, subject/topic indexes, real front matter, volumes (Milestone 6)
- Cross-referencing a diagram/chart/table from chapter prose ("see Figure
  3") — figures are placed but not textually referenced this sprint
- Judge-driven re-ordering, re-outlining, or merging (the judge only
  scores/refines a single section's writing quality)
- Multiple visual aids in one section (the writer emits at most one
  table/diagram/chart per section this sprint)

## Dependencies

- v1-v4 complete: chunk/topics/write pipeline (both `BOOK_ORDER` modes),
  `render_chapter`/`render_book` figure mechanism (v4), `PASS_SCORE`/
  `MAX_REFINE_ATTEMPTS` config settings (already exist since v1, unused
  until now)
- Graphviz (`dot`) installed and on PATH
- `matplotlib` added as a dependency
- A real test video/topic with at least one genuinely chart-worthy passage
  (explicit numbers) and one genuinely diagram-worthy passage (a process
  or structure), picked in Task 1: reusing the v1-v4 test video
  `https://www.youtube.com/watch?v=aircAruvnKk` ("But what is a neural
  network?", 3Blue1Brown) — it states explicit layer sizes (784 input
  neurons, two hidden layers, 10 output neurons: chart-worthy) and
  describes the network's layer structure (input -> hidden -> hidden ->
  output: diagram-worthy).
