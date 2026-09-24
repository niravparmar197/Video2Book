# Sprint v7 — Scale Report (Milestone 7)

Sprint v7 Task 7: project 8h/15h/30h playlist wall-clock time from Task 4's
real measured timing (not a simulation), and give a plain verdict on
whether a 30-hour playlist can finish "overnight" (~10-12h) on today's free
providers.

**Verdict up front: no, not reliably.** Even the optimistic case (healthy
providers, no retries) lands a 30-hour playlist at roughly 13-14 hours —
already over budget — and the conditions actually observed during Task 4's
real run (a genuine NVIDIA outage plus Gemini's real ~20-requests/*day*
free quota) would push it to many multiples of that, or to an outright
failure once Gemini's daily quota is spent. Section 4 lists what would
need to change to make "overnight" real.

## 1. Task 4 real-run evidence

Two real end-to-end attempts were made on 2026-09-24 against real
playlists with `VIDEO_MODE=stream` / `BOOK_ORDER=topic` (the real `.env`
defaults). Full detail lives in `sprints/v7/TASKS.md` Task 4; summary here:

**Run 1** — StatQuest "Neural Networks" (6 videos, 1h23m real duration,
verified via `--estimate`):

| Phase | Real wall-clock (6 videos / 6 chunks) | Per-hour-of-video rate |
|---|---|---|
| fetch + chunk | 38s | ~28s/hour |
| frames (stream-mode ffmpeg scene detection) | ~20min | ~14.5min/hour |
| topics (1 call/chunk) | 2min9s (best observed gap) to 11min+ (degraded) per chunk | n/a — see below |

Frames took one real ffmpeg stream-decode timeout (300s) on a ~17.5min
video, correctly falling back to a chunk-scoped download per
`app/nodes/frames.py`'s existing design — slower, not broken.

**Run 2** — 3B1B "Neural networks" (10 videos, 3h38m), still in progress
at time of writing; used to sanity-check Run 1's per-hour rates hold at a
larger video count, not as this report's primary data source.

**Real provider-reliability findings** (the load-bearing numbers for this
report):

- **NVIDIA (primary) real outage:** `call_writer` genuinely exhausted all
  `MAX_ATTEMPTS=3` retries with a real `ReadTimeout` at the full
  `REQUEST_TIMEOUT_SECONDS=280` on two separate occasions ~12 minutes
  apart. A trivial sanity-check prompt (`"pong"`) run directly against
  `call_writer` *between* those two failures returned in 4.2s — proving
  the primary tier was genuinely degraded for real transcript-sized
  prompts specifically, not a bug in our timeout/retry code.
- **Gemini (fallback) real daily cap:** every fallback attempt failed with
  a real HTTP 429 — `generativelanguage.googleapis.com/
  generate_content_free_tier_requests`, **`quotaValue: 20` requests per
  *day*** for `gemini-3.8-flash`. Root `AGENTS.md` documents Gemini as
  "~10 RPM, daily cap resets midnight Pacific" — true, but the *size* of
  that daily cap (20 requests total) is far more restrictive than the RPM
  figure alone suggests. 6 videos x up to 3 calls/chunk (18 calls) was
  enough to exhaust it before Run 1 even finished its topics phase.
- **Real per-call latency, even once "recovered":** an isolated,
  non-degraded retry of the exact chunk that had been timing out
  succeeded — but took **162.5 seconds** for one topics call. The best
  gap observed between two consecutive successful topics calls
  *in-pipeline* was **129 seconds**. Neither of these is a retry/backoff
  artifact — they're real single-call latencies from NVIDIA's free-tier
  `nemotron-3-super-120b-a12b` on a real ~1000-1200 word transcript
  chunk. This report uses **120 seconds/call** as its "healthy" baseline
  — it is itself already a real, not assumed, number.

## 2. The projection model

Two independent time sinks, both measured for real in Task 4, don't
overlap (frames runs before topics/write in the graph):

```
total_time ≈ frames_time + llm_call_time + fixed_overhead
frames_time   ≈ 14.5 min x video_hours                     (Run 1, measured)
llm_call_time ≈ calls_per_chunk x chunk_count x sec_per_call / 60   minutes
chunk_count   = ceil(video_hours x 60 / CHUNK_MINUTES) = video_hours x 2   (CHUNK_MINUTES=30)
calls_per_chunk = 3 (topics, write, one judge pass — estimate.py's
                     LLM_CALLS_PER_CHUNK; assumes most sections pass the
                     judge first try, per its own comment)
fixed_overhead  = book_pass (index terms/chapter + glossary + preface) +
                  plan-merge (topic mode, 1 call) + fetch/chunk/render —
                  all small relative to the two terms above; ignored below
                  as noise (<10 min even at 30h scale per Run 1's
                  fetch+chunk rate).
```

`_pace()` (sprints/v7 Task 1) enforces a `60/RPM` floor between
same-provider calls — 1.5s for NVIDIA (40 RPM), 6s for Gemini (10 RPM).
At a real observed ~120s/call, that floor is never the binding constraint
for a **sequential** pipeline (today's actual design: one chunk's call
finishes before the next starts) — real model latency alone already
exceeds it by ~20-80x. This matters directly for Section 4's "what would
need to change."

## 3. Projected wall-clock time

| Playlist | Chunks (30min each) | frames time | LLM-call time (120s/call, healthy) | **Total (healthy, optimistic)** | Total (today's observed degraded conditions) |
|---|---|---|---|---|---|
| 8h  | 16 | 1.9h | 16x3x120s = 1.6h | **~3.6h** | Gemini's 20/day quota exhausted well before finishing (48 calls > 20); any NVIDIA hiccup after that is fatal for the rest of the day |
| 15h | 30 | 3.6h | 30x3x120s = 3.0h | **~6.7h** | same — 90 calls, quota exhausted ~7x over |
| 30h | 60 | 7.3h | 60x3x120s = 6.0h | **~13.4h** | same — 180 calls, quota exhausted ~9x over; a single sustained outage (as observed today, ~1h+) adds hours on top |

"Degraded conditions" isn't hypothetical — it is exactly what Task 4's
real run hit. Once Gemini's daily quota is spent, NVIDIA has **zero
fallback** for the rest of that calendar day; any NVIDIA `ReadTimeout` at
that point (each one costs up to `3 x 280s ≈ 14min` before
`call_writer` finally raises) simply fails the run, which then needs a
human to notice, wait, and `--resume`.

## 4. The "overnight" verdict and what would change it

**Interpreting "overnight" as ~10-12h (sprints/v7 TASKS.md Task 7):** even
the *optimistic, healthy-provider* 30-hour projection (~13.4h) is already
past that window, before counting a single retry, refine loop, or
provider hiccup. The realistic case — given what Task 4 actually
observed today — is worse than that by an unpredictable but potentially
large margin, up to and including the run stalling entirely once Gemini's
daily quota is gone and NVIDIA degrades.

**What would need to change, roughly in order of impact:**

1. **A paid tier for the fallback, at minimum.** Gemini's real free quota
   (20 requests/*day*) cannot back up any playlist bigger than a handful
   of chunks — it is not a functioning safety net today. This is the
   single highest-leverage fix: it directly removes Finding B (Section 1)
   and turns "NVIDIA hiccups, run dies for the day" into "NVIDIA hiccups,
   Gemini absorbs it," which is what root `AGENTS.md`'s provider-chain
   design already assumes.
2. **Parallelism.** Section 2 showed real per-call latency (~120s) is
   20-80x the RPM-enforced floor (1.5s/6s) — the pipeline is nowhere near
   its rate-limit ceiling; it's simply sequential. Running chunks'
   topics/write/judge calls concurrently (bounded by each provider's RPM,
   e.g. up to ~40 in flight for NVIDIA) could cut `llm_call_time` from
   hours to single-digit minutes at any scale (180 calls / 40 RPM ≈ 4.5min
   floor, vs. today's sequential 6h) — this is the highest-leverage
   *code* change, bigger than the frames-phase optimization below.
3. **Faster/parallel frames extraction.** At 30h scale, frames time
   (~7.3h) is actually the *larger* of the two optimistic-case terms —
   bigger than all the LLM calls combined. It's bound by ffmpeg decoding
   the stream in roughly real time per video; running multiple videos'
   scene detection concurrently (I/O and CPU permitting) would cut this
   close to linearly with however many run in parallel.
4. **A longer "overnight" budget** (e.g. treat "overnight" as ~18-24h
   instead of 10-12h) is the cheapest fix but only helps the *optimistic*
   case — it does nothing about Finding A/B, so a real free-tier hiccup
   can still stall a run indefinitely without a paid fallback.

None of the above were implemented as part of this report — Task 7's
acceptance is the projection and verdict, not a fix. Items 1-3 are
reasonable candidates for a future sprint's TASKS.md once someone signs
off on the tradeoff (cost for item 1, complexity for item 2).
