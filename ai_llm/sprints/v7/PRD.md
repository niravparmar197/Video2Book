# Sprint v7 — PRD: Scale Test (Milestone 7, Core Final Validation)

## Overview

Implement Milestone 7, the core engine's final bar: proactive rate-limit
pacing so a long playlist doesn't burn through the free-tier fallback's
daily cap, `MAX_BOOK_HOURS`/`MAX_BOOK_COST_USD` actually enforced (currently
loaded into `Settings` but never checked anywhere), and real measurement —
not a guess — of whether a 30-hour playlist can plausibly finish overnight.
This is a validation-heavy sprint: most of its value is in what gets
measured and documented, not new user-facing features.

## Goals

- `call_writer` proactively paces requests to stay under NVIDIA's ~40 RPM
  and Gemini's ~10 RPM (root `AGENTS.md`'s LLM chain numbers), instead of
  only reacting to a 429 after the fact — a long run must not exhaust
  Gemini's daily cap through avoidable fallback traffic
- `--estimate` (and a real run) respect `MAX_BOOK_HOURS`: a playlist over
  the limit is refused unless explicitly overridden, instead of silently
  attempting a run nobody sized for
- `MAX_BOOK_COST_USD` gets the same enforcement, future-proofed for when a
  paid tier is added (a no-op today since both providers are free)
- A real, timed, small-scale end-to-end run (~2 hours of source video —
  Milestone 7's first checkpoint) produces a clean PDF with zero manual
  fixes, with wall-clock time and disk usage actually measured, not assumed
- Real per-chunk timing from that run is used to produce an honest,
  documented projection for the 8h/15h/30h checkpoints — stating plainly
  whether "overnight" is achievable and what would need to change if not

## User Stories

- As the operator, I want a long run to pace itself under the free tiers'
  rate limits, so a 30-hour playlist doesn't get throttled into failing
  chunks partway through
- As the operator, I want to be warned (and asked to confirm) before
  starting a run that exceeds my configured `MAX_BOOK_HOURS`, so I don't
  discover the scale problem 20 hours into an overnight run
- As the operator, I want real numbers — not a guess — on whether a
  30-hour playlist actually finishes overnight, so I know whether to trust
  the core engine at the scale root `AGENTS.md` describes as "done"

## Technical Architecture

**Stack**: no new external dependencies — this sprint adds pacing logic to
`app/llm.py` and enforcement to `app/estimate.py`/`app/cli.py`, plus real
measurement runs against the existing pipeline.

```
        app/llm.py call_writer() (extended)
   a simple token-bucket / min-interval sleep
   per provider (NVIDIA ~40 RPM, Gemini ~10 RPM)
   applied BEFORE each call, not just on 429 retry
                    │
                    ▼
        app/estimate.py / app/cli.py (extended)
   --estimate's existing chunk/token estimate now
   also checks total duration against
   MAX_BOOK_HOURS and (once non-zero) cost against
   MAX_BOOK_COST_USD; a plain run refuses to start
   over the limit unless --force is passed
                    │
                    ▼
        Real measurement run (~2h playlist)
   real wall-clock per chunk, real disk usage,
   confirms a clean PDF -- feeds the 8h/15h/30h
   projection, documented honestly (not a real
   30-hour run within this session's constraints)
```

**Data flow**: unchanged from v1-v6 — this sprint doesn't add new pipeline
stages, only paces the existing LLM calls and gates the existing `run_book`
entry point on the existing `MAX_BOOK_HOURS`/`MAX_BOOK_COST_USD` settings.

## Out of Scope (v8+)

- Actually running a real, full 30-hour playlist end to end within this
  sprint — infeasible in real wall-clock time and free-tier quota inside
  a single working session; the 30h figure is a documented projection
  from real 2h measurements, not a real 30h run
- A persistent/distributed rate limiter (this sprint's pacing is
  in-process, per `call_writer` call — fine for the CLI's single-process
  model; a queue-based limiter is backend/'s concern, not core's)
- Automatic playlist splitting to fit under `MAX_BOOK_HOURS` (the
  enforcement this sprint adds refuses or requires `--force`; it doesn't
  auto-trim the playlist)
- Whisper transcription fallback, multi-language, or any feature work
  unrelated to scale/budget validation

## Dependencies

- v1-v6 complete: the full pipeline (fetch → chunk → frames → topics →
  plan/order → outline → write+verify → book_pass → render), both
  `BOOK_ORDER` modes, `MAX_BOOK_HOURS`/`MAX_BOOK_COST_USD` settings already
  loaded by `config.py` since v1 but never enforced until this sprint
- A real playlist totaling roughly 2 hours of source video, picked in
  Task 4, for the real timed measurement run
