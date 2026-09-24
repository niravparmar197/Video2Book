"""Cost/time estimate for a video — computed without calling any LLM.

Token counts here are a rough heuristic based on spoken-word rate, good
enough to gauge chunk count and rate-limit exposure before committing to a
real run. Both providers in the root AGENTS.md LLM chain (NVIDIA primary,
Gemini fallback) are free tiers right now, so the cost estimate is always
$0 — this exists to size the run, not to price it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.config import load_settings
from app.youtube import fetch_metadata, list_playlist_videos

# Rough spoken-word rate for narrated/lecture-style video.
WORDS_PER_MINUTE = 150
# Rough tokens-per-word ratio for English text.
TOKENS_PER_WORD = 1.3
# LLM calls that read the transcript, per chunk: topics extraction
# (topics.py) + chapter notes (write.py) + one judge pass (verify.py,
# sprints/v5). Most sections pass judging on the first attempt, so this
# assumes exactly one judge call per chunk, not MAX_REFINE_ATTEMPTS worst
# case -- an estimate, not a hard upper bound.
LLM_CALLS_PER_CHUNK = 3
# Rough output size per chunk: topics list + chapter notes + judge feedback.
OUTPUT_TOKENS_PER_CHUNK = 800


@dataclass(frozen=True)
class EstimateResult:
    video_id: str
    title: str
    duration_seconds: int
    chunk_count: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    estimated_cost_usd: float


def estimate_video(url: str, chunk_minutes: int | None = None) -> EstimateResult:
    """Estimate chunk count and token usage for one video. Never calls an LLM."""
    if chunk_minutes is None:
        chunk_minutes = load_settings().chunk_minutes

    metadata = fetch_metadata(url)

    duration_minutes = metadata.duration_seconds / 60
    chunk_count = max(1, math.ceil(duration_minutes / chunk_minutes))

    transcript_words = duration_minutes * WORDS_PER_MINUTE
    transcript_tokens = int(transcript_words * TOKENS_PER_WORD)

    estimated_input_tokens = transcript_tokens * LLM_CALLS_PER_CHUNK
    estimated_output_tokens = chunk_count * OUTPUT_TOKENS_PER_CHUNK
    estimated_total_tokens = estimated_input_tokens + estimated_output_tokens

    return EstimateResult(
        video_id=metadata.video_id,
        title=metadata.title,
        duration_seconds=metadata.duration_seconds,
        chunk_count=chunk_count,
        estimated_input_tokens=estimated_input_tokens,
        estimated_output_tokens=estimated_output_tokens,
        estimated_total_tokens=estimated_total_tokens,
        estimated_cost_usd=0.0,
    )


def estimate_playlist(url: str, chunk_minutes: int | None = None) -> list[EstimateResult]:
    """Estimate chunk count and token usage for every video in a playlist.

    A plain (non-playlist) video URL resolves to a list of 1, same as
    estimate_video but through the playlist-aware path. Never calls an LLM.
    """
    entries = list_playlist_videos(url)
    return [estimate_video(entry.url, chunk_minutes=chunk_minutes) for entry in entries]


def print_estimate(url: str) -> None:
    results = estimate_playlist(url)

    for result in results:
        minutes, seconds = divmod(result.duration_seconds, 60)
        print(f"Video:        {result.title} ({result.video_id})")
        print(f"Duration:     {minutes} min {seconds} sec")
        print(f"Chunks:       {result.chunk_count}")
        print(
            f"Est. tokens:  {result.estimated_total_tokens:,} "
            f"({result.estimated_input_tokens:,} in / "
            f"{result.estimated_output_tokens:,} out)"
        )
        print()

    total_chunks = sum(result.chunk_count for result in results)
    total_tokens = sum(result.estimated_total_tokens for result in results)
    total_cost = sum(result.estimated_cost_usd for result in results)

    if len(results) > 1:
        print(f"Total videos: {len(results)}")
    print(f"Total chunks: {total_chunks}")
    print(f"Total tokens: {total_tokens:,}")
    print(f"Total cost:   ${total_cost:.2f} (NVIDIA + Gemini free tiers)")

    settings = load_settings()
    total_hours = sum(result.duration_seconds for result in results) / 3600
    if total_hours > settings.max_book_hours:
        print(
            f"WARNING: total duration ({total_hours:.2f}h) exceeds MAX_BOOK_HOURS "
            f"({settings.max_book_hours}h) -- a plain run will refuse to start; "
            "pass --force to proceed anyway"
        )
    if total_cost > settings.max_book_cost_usd:
        print(
            f"WARNING: total estimated cost (${total_cost:.2f}) exceeds MAX_BOOK_COST_USD "
            f"(${settings.max_book_cost_usd:.2f}) -- a plain run will refuse to start; "
            "pass --force to proceed anyway"
        )

    video_mode = load_settings().video_mode
    if video_mode == "captions_only":
        print("Screenshots:  skipped (VIDEO_MODE=captions_only)")
    else:
        print(
            f"Screenshots:  will be taken (VIDEO_MODE={video_mode}) — one per scene "
            "change, not a fixed count"
        )
