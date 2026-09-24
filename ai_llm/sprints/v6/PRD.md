# Sprint v6 — PRD: Full Book (Glossary, Indexes, Volumes)

## Overview

Implement Milestone 6, the last core milestone: a preface and title page,
a glossary merged and deduped across the whole book, a real page-numbered
subject index, a structural topic index, and automatic splitting into
multiple PDF volumes for a long playlist. This is what turns a pile of
chapters into an actual book — and completes the "core is done" bar from
root `AGENTS.md`.

## Goals

- `book_pass.py` (new) generates a short preface from the book's own
  outline/scope, and extracts + merges a glossary (term + definition) and
  a set of subject-index terms from every chapter's final notes — grounded
  in the book's own content, never invented
- A real subject index (LaTeX `imakeidx`, `\index{term}` markup, real page
  numbers via `makeindex`, which `latexmk` already runs automatically) is
  built from those extracted terms
- A topic index (a structural list of every chapter/topic title, built
  directly from `outline.json` — no LLM call, no `makeindex`) gives a
  second way to find content by subject matter covered, not just keyword
- A long playlist is automatically split into multiple volumes
  (`book_vol1.pdf`, `book_vol2.pdf`, ...) once total source video duration
  crosses a configurable threshold, instead of one giant PDF
- Every new step (preface, glossary, index terms) is cache-skippable and
  resume-safe, and both `BOOK_ORDER` modes get the same front/back matter

## User Stories

- As the operator, I want a preface that actually describes what the book
  covers, so the reader isn't dropped straight into chapter 1 with no context
- As the operator, I want a glossary of the book's actual terminology, so
  a reader can look up a term without re-reading a whole chapter
- As the operator, I want a real page-numbered index, so the book behaves
  like a real reference text, not just a linear PDF
- As the operator, I want a 30-hour playlist to produce a few reasonably
  sized volumes instead of one unwieldy PDF, so the book is actually usable

## Technical Architecture

**Stack**: adds `imakeidx` (LaTeX package, ships with any standard LaTeX
distribution already installed — MiKTeX) and `makeindex` (also ships with
MiKTeX; `latexmk` already auto-detects `\makeindex` and runs it as part of
its normal multi-pass compile, so `compile_chapter()`'s existing latexmk
invocation needs no changes).

```
   all chapters' final work/notes/*.md (v1-v5)
                    │
                    ▼
        nodes/book_pass.py (new)
   one LLM call per chapter/topic: preface
   context + glossary terms + subject-index
   terms, all grounded in that chapter's notes
                    │
                    ▼
   glossary.json (merged + deduped across
   chapters) + index_terms.json (per chapter)
   + preface.md (one call, whole-book scope)
                    │
                    ▼
   latex/tex.py (extended): \index{term}
   markup inserted at each term's first
   occurrence per chapter; glossary chapter
   + topic index (from outline.json, no LLM)
   rendered as back-matter sections
                    │
                    ▼
   main.tex.j2 (extended): title page, preface,
   TOC, chapters, glossary, \printindex
   (subject), topic index -- split into
   main_vol<N>.tex when total video duration
   crosses VOLUME_HOURS -> book_vol<N>.pdf
```

**Data flow**: `work/notes/*.md` (v1-v5) → `work/book_pass/glossary.json`,
`work/book_pass/index_terms_<id>.json`, `work/book_pass/preface.md` →
`chapters/<id>.tex` (now with `\index{}` markup) + `chapters/glossary.tex`
+ `chapters/topic_index.tex` → `chapters/main_vol<N>.tex` (one or more,
per the volume split) → `book_vol<N>.pdf` (or plain `book.pdf` if the
playlist doesn't cross the volume threshold — single-volume books keep
today's exact filename, no behavior change for the common case).

## Out of Scope (v7+)

- Cross-references between chapters ("see Chapter 3") — out of scope since
  v5 already deferred this for figures; still deferred here for prose
- A "further reading" or bibliography section
- Multi-language glossaries/indexes
- Manual editing of the glossary/index (unlike `outline.json`'s
  skip/locked review flow, glossary/index terms aren't reviewable this
  sprint)
- Custom volume splitting (e.g., "always split at chapter N") — only the
  automatic duration-threshold split is implemented

## Dependencies

- v1-v5 complete: chunk/topics/write/verify pipeline (both `BOOK_ORDER`
  modes), `render_chapter`/`render_book` (v2/v4/v5, table/diagram/chart +
  screenshot figures), `compile_chapter` (latexmk, already auto-runs
  makeindex when `\makeindex` is present — verified in Task 4)
- MiKTeX's `imakeidx`/`makeindex` (ships with the MiKTeX install from v1
  Task 7; MiKTeX auto-installs missing packages on first use, same as
  every other LaTeX package this project has needed so far)
- A new `VOLUME_HOURS` config setting (default 10) controlling the volume
  split threshold
- A real multi-video test playlist to verify glossary/index/preface
  rendering end to end — reusing the v2/v3 test playlists (both already
  confirmed to have real captions and multiple chapters)
