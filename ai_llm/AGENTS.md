# ai_llm/ — Core Engine (Video → PDF)

Scope: this is the whole product for now — CLI in, PDF out. No API layer, no database, no queue here; those live in `backend/` and later call into this package's `graph.py`. See the root `AGENTS.md` for the cross-project decisions everything here follows.

## Stack

| Part | Tool | Why |
|---|---|---|
| Language | Python | Best tools for video, audio, AI, and LaTeX |
| Workflow | LangGraph + SqliteSaver | Parallel steps, verify loop, resume after a crash |
| AI calls | LangChain + NVIDIA NIM (primary) + Gemini (fallback) | Free, see root `AGENTS.md` for the provider chain |
| AI monitoring | LangSmith | Traces, cost per book, quality scores |
| YouTube | yt-dlp + Deno | Video list, captions, stream links, audio |
| Video | ffmpeg | Scene scan on stream, frame grab, audio |
| Duplicate check | imagehash + Pillow | Remove repeated and blank images |
| Speech to text | faster-whisper | Fallback when there are no captions (GPU for long videos) |
| Diagrams | Graphviz | Safe to render |
| Charts | matplotlib | Only from real numbers |
| Book | Pandoc + Jinja2 + LuaLaTeX + latexmk | Clean LaTeX, TOC, index |
| Tests | pytest | Unit tests |

## Folder structure

```
app/
├── cli.py             # run, --estimate, --plan-only, --resume
├── config.py           # settings from .env
├── youtube.py           # video list, captions, stream links, audio
├── graph.py             # book graph + chapter graph
├── cache.py             # skip steps already saved
├── estimate.py           # cost + time estimate, budget check
├── nodes/
│   ├── fetch.py          # metadata + captions
│   ├── chunk.py           # split into 30-min chunks
│   ├── transcribe.py       # captions or Whisper
│   ├── topics.py           # topics per chunk
│   ├── frames.py           # stream scan + screenshots + dedupe
│   ├── outline.py          # merge topics, build the book plan
│   ├── order.py            # sort, checks, auto-fixes, manual edits
│   ├── write.py            # LLM writes sections
│   ├── render.py           # tables, diagrams, charts -> .tex
│   ├── verify.py           # compile check + judge
│   └── book_pass.py         # index terms + glossary
├── prompts/               # one .md file per prompt — never inline prompts in .py
│                          # writer rules = _grounding.md + _style_<lecture|podcast|comedy>.md + _output.md
└── latex/
    ├── tex.py
    └── templates/           # main (callout + highlight macros), chapter, glossary
tests/unit/
output/                     # one folder per book (git-ignored)
```

Split a file once it passes ~300 lines. One node file per pipeline step.

## Workflow (5 phases, each saves to disk so `--resume` never restarts from zero)

| Phase | What happens | Output |
|---|---|---|
| A. Understand | Per video, per 30-min chunk: transcript, topics, screenshots | `work/`, `assets/` |
| B. Plan | Merge the same topics, order them, group into parts/chapters | `outline.json`, `outline.md` |
| C. Write | Write each section from all its source videos, then verify | `chapters/*.tex` |
| D. Book pass | Clean index terms, glossary, cross-references, preface | `terms.json`, `glossary.json` |
| E. Compile | Front matter, parts, chapters, glossary, indexes | `book.pdf` or volumes |

CLI:

```
python -m app.cli "<playlist url>" --estimate    # cost + time only
python -m app.cli "<playlist url>" --plan-only   # stop after the outline
python -m app.cli "<playlist url>"              # make the book
python -m app.cli --resume output/<book>        # continue after a stop
```

## Kind of book (`genre.py`)

The topics step also decides the book's genre with one short LLM call per video (title + start of the transcript; a playlist takes its most common answer), saved to `work/genre.json`. `VIDEO_GENRE=lecture|podcast|comedy` forces it; `auto` is the default.

| Genre | Book | Writer style (`prompts/_style_<genre>.md`) |
|---|---|---|
| `lecture` | Study Notes | Key Point / Example / Watch Out boxes, simple-English explanations, diagrams + tables, Key Takeaways |
| `podcast` | Podcast Notes | Episode at a Glance, one section per discussion topic, who argued what (only when clear), exact `> Quote:` lines, Mentioned in This Episode, Key Takeaways |
| `comedy` | Comedy Recap | Show at a Glance, one section per bit (setup -> how it builds), punchlines as exact `> Quote:` lines, Best Moments; no glossary, index, diagrams or charts |

All three share `_grounding.md` (never invent facts, names or quotes; translate to English; skip garbled captions) and `_output.md`. The title page names the kind of book.

## Speed (a 5-minute video should take about 5 minutes end to end)

- **One chunk = one chapter.** A book whose whole source is a single chunk (one video ≤ `CHUNK_MINUTES`) skips the topic-merge LLM call; `plan.py`'s `run_single_chunk_plan` writes one chapter that covers every topic found, and `write.py` gives each its own `##` section. Merging only runs when there is something to merge.
- **Videos up to ~13-15h download for screenshots.** In `VIDEO_MODE=stream`, videos ≤ `FRAMES_DOWNLOAD_MAX_MINUTES` (900) are downloaded once at 480p video-only (measured ~50 MB/hour; a free-disk guard assumes 0.3 GB/hour × 3 and streams instead if there isn't room), scanned locally and deleted — ffmpeg's direct stream read is throttled (~8x slower). Longer videos still stream. `0` = always stream.
- **Long-video scale (~13h, 26 chunks).** A short final chunk (< 20% of `CHUNK_MINUTES`) is merged into the one before it, so a 30:40 video is one chunk, not two. In topic mode a chunk's hours are shared between the chapters that use it and its screenshots go to the first chapter using it, so a 13h book totals 13h (one PDF at `VOLUME_HOURS=15`; backend/ stores one PDF per book) and no screenshot repeats. The glossary is built from ~15k-token batches of chapters in parallel instead of one call over every chapter.
- **Target: an 8-hour video in ~15 minutes** (measured building blocks, 2026-10-04): writer calls run `LLM_PARALLEL_CALLS` (12) at a time -- 8 real calls in parallel took 63s vs 42s for one, and NVIDIA's 40 RPM pacing still applies; ffmpeg scans keyframes only (`-skip_frame nokey`, 4.7x faster, ~1 min for 8h); at most `MAX_SCREENSHOTS_PER_CHUNK` (12) screenshots per chunk; a 212-page / 200-image book compiles in 44s. Projection for 8h (16 chunks, ~40 chapters): ~11-13 min **if YouTube captions are available** -- Whisper on CPU runs ~5-7 min per 30 min of audio, so a caption-less 8h video needs a GPU.
- **Captions:** the requested language (`en`) is tried once; if it is missing or rate-limited (HTTP 429 -- the English track of a non-English video is YouTube's machine translation and is throttled hard), the video's own-language track (e.g. `hi-orig`) is used and the writer translates. Whisper is the last resort. The grounding checks (unspoken numbers, names not in the transcript) only run on English transcripts.
- **Book pass:** the glossary is the only LLM work (batched); each chapter's index terms are its glossary terms plus its **bold** terms, no LLM call (was one call per chapter -- 190s on a 4h book).
- **Refine = revise, not rewrite:** a section below `PASS_SCORE` goes back to the writer with its own notes + the judge's feedback (`prompts/revise_notes.md`), keeping what was fine; the best-scoring attempt is kept.
- **Closing section guaranteed:** if the writer drops Key Takeaways / Best Moments it is rebuilt from the chapter's own `> Key point:` / `> Quote:` lines (`write.ensure_closing_section`), no LLM call.
- **Whisper:** greedy decoding (`beam_size=1`), 1.4x faster than beam 5 with 93% of words identical on a real lecture.
- **YouTube "Sign in to confirm you're not a bot":** set `YOUTUBE_COOKIES_FILE` (exported cookies.txt; git-ignored) or `YOUTUBE_COOKIES_BROWSER`; every yt-dlp call uses it (`youtube._with_auth`).
- **Book type in the app:** `POST /books/youtube` takes `genre` (auto|lecture|podcast|comedy); a chosen genre is saved to `work/genre.json` before planning, so detection is skipped. The progress stream reports `book_kind` and `step_seconds`.
- **YouTube requests:** each video's metadata + transcript live in the shared cache (`<id>.meta.json`, `<id>.transcript.vtt`), so a video is fetched from YouTube once -- re-runs, retries, other books and the backend's estimate reuse it; yt-dlp pauses 0.5s between requests. A failed screenshot download is a warning, never a failed book.
- **YouTube chapters:** when a video has creator chapters, a chunk's topics are its (cleaned, non-filler, Latin-script) chapter titles -- no topics LLM call.
- **Section times (`align.py`):** each `##` section is matched to the ~45s caption window sharing the most rare words; screenshots go to the section whose time they fall in, and each timed section / screenshot links to that moment (`https://youtu.be/<id>?t=N`).
- **Test Yourself (study notes):** 3-5 Q/A pairs per chapter; questions stay in the chapter, answers go to "Answers to Test Yourself" at the back.
- **Exports:** `book.md` and `book.epub` are written next to `book.pdf` (`app/export.py`, no pandoc needed).
- **Eval gate:** `python -m app.eval` writes + judges every example in `eval/dataset.jsonl` (or the LangSmith dataset `EVAL_DATASET_NAME`) with the current prompts and compares with `eval/baseline.json`; a drop is BLOCKED when `EVAL_ON_RELEASE=true`. Baseline 2026-10-04: 6.0 (lecture 8/8/6, podcast 5, comedy 3) -- quotes in podcast/comedy books are the weakest point.
- **The judge is re-asked, not the writer.** An unparseable judge reply gets one short retry before any rewrite.
- **Every run records seconds per step** in `<book>/timings.json` and the CLI prints it — look there first when a run is slow. `MAX_REFINE_ATTEMPTS` (default 2, ceiling 3) is the biggest remaining knob: each refine is a full rewrite + re-judge (~80s). The kept notes are the best-scoring attempt, not just the last.

## Order management (`order.py` / `outline.py`)

- `BOOK_ORDER=topic` (needs → level → first appearance, merges repeated topics into one section with multiple sources) or `video` (video 1 → N, then timestamp — for clean single courses).
- A topic never appears before a topic it `needs`. Easier topics (`level` 1) come before harder ones (`level` 5). Ties break by original video order. Manual edits in `outline.json` (`locked: true`, `skip: true`) always win over the auto-sort.
- Loops in `needs` are broken automatically (weakest link removed, easier topic placed first) and logged to `order_log.txt`, never silently dropped.
- Stable `id`s per topic/section (e.g. `sec:gradient-descent`) so reordering never breaks cross-references; chapter/figure/table numbers are generated at compile time, not stored.
- Review flow: `--plan-only` stops after the plan → read `outline.md` → edit `outline.json` → `--resume`. The checker re-runs after edits, warns on problems, but never undoes a manual change.

## Rules for AI steps

- Use only facts from the transcript and screenshots. Never invent numbers.
- Never force a table, diagram, or chart when the source content doesn't call for one.
- The AI never writes raw LaTeX — it writes Markdown/JSON, templates render `.tex`.
- Prompts live in `app/prompts/*.md`, never as inline strings in Python.
- Never hardcode API keys or secrets — read from `.env` / environment variables.

## Testing

- Never call a real LLM or YouTube endpoint in a unit test — mock or stub the client.
- Keep the whole unit suite under ~30 seconds.
- Target ~80% coverage on `youtube.py`, `latex/`, `render.py`, and `order.py`.
- Run `bandit -r app/ -ll` and `pip-audit` before considering a task done.
- A prompt or model change ships only after the LangSmith eval set (`EVAL_DATASET_NAME`) runs without the average judge score dropping (`EVAL_ON_RELEASE=true`).
