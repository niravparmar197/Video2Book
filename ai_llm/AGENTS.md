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
├── batch.py             # paid-tier Batches API: send, save, poll (optional)
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
│   └── book_pass.py         # index terms, glossary, cross-refs, preface
├── prompts/               # one .md file per prompt — never inline prompts in .py
└── latex/
    ├── tex.py
    └── templates/           # main, frontmatter, part, chapter, glossary, topic_index, sources
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
