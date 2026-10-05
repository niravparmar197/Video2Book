# Video2Book

Turn YouTube videos — a single link or a whole playlist, up to 30 hours — into a well-organized book: notes, screenshots, tables, diagrams, charts, a table of contents, a glossary and two indexes. Every book comes out as `book.pdf`, `book.epub` and `book.md`.

The default LLM chain is free: **NVIDIA NIM** (primary) with **Google Gemini** as fallback.

## How it works

```
YouTube URL ─▶ captions / Whisper ─▶ 30-min chunks ─▶ topics + screenshots
          ─▶ book plan (merge repeated topics, order them) ─▶ write each section
          ─▶ judge + refine weak sections ─▶ glossary + index ─▶ LaTeX ─▶ PDF
```

- **Captions first**, Whisper on the audio only when there are none.
- **One screenshot per scene change**, not on a timer; duplicates and blank frames removed, and a vision model drops speaker-only frames and captions the rest.
- **Plan before writing**: the whole book is outlined first, so a topic repeated across videos becomes one section with several sources. `BOOK_ORDER=topic` orders by prerequisites; `video` keeps the original order.
- **Three kinds of book**, detected per video: study notes (lectures), podcast notes, comedy recap.
- **Quality loop**: every section is scored by a judge model; anything below `PASS_SCORE` is revised (up to `MAX_REFINE_ATTEMPTS`).
- **The AI never writes LaTeX** — it writes Markdown/JSON, and templates build the `.tex`.
- **Crash-safe**: every step saves to disk, and `--resume` continues where a run stopped.

## Repo layout

| Folder | What it is |
|---|---|
| [`ai_llm/`](ai_llm/) | Core engine — LangGraph pipeline, yt-dlp, ffmpeg, LLM calls, LaTeX → PDF. Runs on its own from the command line. |
| [`backend/`](backend/) | FastAPI + PostgreSQL + BullMQ/Redis + S3 API that wraps the engine as a job queue. See [`backend/README.md`](backend/README.md). |
| [`frontend/`](frontend/) | React + Vite + Tailwind web app on top of the backend API. |

Project rules and design decisions live in [`AGENTS.md`](AGENTS.md), with one per subproject.

## Quick start (core engine)

### 1. Install the system tools

| Tool | Used for |
|---|---|
| Python 3.11+ | the engine |
| [ffmpeg](https://ffmpeg.org/) | scene detection, frame grabs, audio |
| [Deno](https://deno.com/) | yt-dlp's YouTube support |
| A TeX distribution with **LuaLaTeX** and **latexmk** (TeX Live or MiKTeX) | building the PDF |
| [Graphviz](https://graphviz.org/) (`dot`) | diagrams |

### 2. Install the Python packages

```bash
cd ai_llm
pip install -e ".[dev]"
pip install langgraph langgraph-checkpoint-sqlite langchain-nvidia-ai-endpoints \
            langchain-google-genai yt-dlp jinja2
```

### 3. Add your keys

```bash
cp .env.example .env
```

Then fill in:

- `NVIDIA_API_KEY` — free at <https://build.nvidia.com/>
- `GOOGLE_API_KEY` — free at <https://aistudio.google.com/apikey>
- `LANGSMITH_API_KEY` *(optional)* — tracing; also set `LANGSMITH_TRACING=true` and `LANGSMITH_PROJECT=video2book`

If YouTube answers "Sign in to confirm you're not a bot", set `YOUTUBE_COOKIES_FILE` (an exported `cookies.txt`) or `YOUTUBE_COOKIES_BROWSER`.

### 4. Make a book

```bash
python -m app.cli "<video or playlist url>" --estimate    # time + cost only
python -m app.cli "<video or playlist url>" --plan-only   # stop after the outline
python -m app.cli "<video or playlist url>"               # make the book
python -m app.cli --resume output/<book>                  # continue after a stop
```

The book lands in `ai_llm/output/<video-or-playlist-id>/`, as `book.pdf`, `book.epub` and `book.md`. `timings.json` there records the seconds spent in each step.

**Reviewing the plan:** run with `--plan-only`, read `outline.md`, edit `outline.json` (`skip: true` drops a section, `locked: true` pins its position), then `--resume`.

## Main settings (`ai_llm/.env`)

| Setting | Default | Meaning |
|---|---|---|
| `VIDEO_MODE` | `stream` | `stream` \| `download` \| `captions_only` (no screenshots) |
| `TRANSCRIPT_SOURCE` | `auto` | `auto` \| `captions` \| `whisper` |
| `VIDEO_GENRE` | `auto` | `auto` \| `lecture` \| `podcast` \| `comedy` |
| `BOOK_ORDER` | `topic` | `topic` (by prerequisites) \| `video` (original order) |
| `CHUNK_MINUTES` | `30` | chunk size for long videos |
| `PASS_SCORE` | `7` | minimum judge score for a section |
| `MAX_REFINE_ATTEMPTS` | `2` | revisions per weak section (max 3) |
| `SCREENSHOT_REVIEW` | `true` | vision model filters and captions screenshots |
| `MAX_BOOK_HOURS` / `MAX_BOOK_COST_USD` | `30` / `50` | refuse bigger jobs unless `--force` |

The full list, with comments, is in [`ai_llm/.env.example`](ai_llm/.env.example).

## Web app (backend + frontend)

```bash
# backend — needs Docker for Postgres, Redis and S3Mock
cd backend
cp .env.example .env
docker compose up -d
pip install -e ".[dev]"
alembic upgrade head
uvicorn api.main:app --reload      # API on :8000
python -m api.worker               # in a second terminal

# frontend
cd frontend
cp .env.example .env               # VITE_API_BASE_URL=http://localhost:8000
npm install
npm run dev                        # http://localhost:3000
```

The backend imports `ai_llm` directly, so install the engine's packages in the same environment. For auth, endpoints, retention, backups and live progress events, see [`backend/README.md`](backend/README.md).

## Tests

```bash
cd ai_llm   && python -m pytest tests/unit     # no real LLM or YouTube calls
cd backend  && pytest                          # needs docker compose up -d
cd frontend && npm run test:e2e                # Playwright, mocked API
```

**Eval gate:** `python -m app.eval` (in `ai_llm/`) writes and judges every example in `eval/dataset.jsonl` with the current prompts and compares the average with `eval/baseline.json`. A prompt or model change ships only if the score doesn't drop.

## Monitoring

With `LANGSMITH_TRACING=true`, each run appears in LangSmith as one trace, with a child run per pipeline step and every writer, judge and vision call underneath it, including token counts. Screenshot images and API keys are never sent to the trace.

## Note on privacy

Both free LLM tiers may use request data to improve their models. That's fine for public videos; use a paid tier before processing private content.
