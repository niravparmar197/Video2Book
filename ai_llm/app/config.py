"""Configuration loading for the Video2Book core engine.

Settings are read from environment variables, optionally populated from a
.env file first. See root AGENTS.md for the full settings table and the
defaults each one falls back to when unset.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Anchored to this package's own directory rather than a bare relative
# ".env", so load_settings() finds the right file regardless of the
# caller's cwd -- ai_llm's own CLI runs from within ai_llm/, but backend/
# imports this module and calls load_settings() from its own cwd, where a
# relative ".env" would silently resolve to backend/.env (no LLM keys
# there) instead of ai_llm/.env.
_DEFAULT_DOTENV_PATH = str(Path(__file__).resolve().parent.parent / ".env")

# Shared across every book (and both the CLI and backend/), so the same
# video submitted twice reuses its Whisper transcript instead of
# re-transcribing it -- 2.5-6 minutes on a CPU-only machine.
_DEFAULT_TRANSCRIPT_CACHE_DIR = str(
    Path(__file__).resolve().parent.parent / "output" / "_transcript_cache"
)

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return int(raw)


def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return float(raw)


def _get_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    video_mode: str = "stream"
    chunk_minutes: int = 30
    # Videos up to this long are downloaded once (480p, video-only, deleted
    # after the scan) for screenshots instead of streamed: ffmpeg's direct
    # stream read is throttled and ~8x slower. 900 (15h) covers a ~13h video;
    # a 480p copy measured ~50MB/hour. 0 = always stream.
    frames_download_max_minutes: int = 900
    # Screenshots kept per chunk (evenly spread); a talking-head lecture had 153
    # in 27 minutes. 0 = no limit.
    max_screenshots_per_chunk: int = 12
    transcript_source: str = "auto"
    llm_provider: str = "nvidia"
    llm_fallback_provider: str = "gemini"
    book_order: str = "topic"
    # auto | lecture | podcast | comedy -- the kind of book to write (study
    # notes, podcast notes or a comedy recap); auto asks the LLM per video.
    video_genre: str = "auto"
    review_outline: bool = True
    pass_score: int = 7
    # Each refine is a full rewrite + re-judge (~80s), so 2 total attempts by
    # default; 3 is the documented ceiling (root AGENTS.md).
    max_refine_attempts: int = 2
    # LLM calls in flight at once (topics, chapter writes, judges, index terms).
    # NVIDIA's 40 RPM pacing in app/llm.py still caps throughput.
    llm_parallel_calls: int = 12
    max_book_hours: int = 30
    max_book_cost_usd: float = 50
    # One PDF up to this many hours of video (backend/ stores one PDF per book);
    # 15 keeps a ~13h video in a single file.
    volume_hours: float = 15
    transcript_cache_dir: str = _DEFAULT_TRANSCRIPT_CACHE_DIR
    # Your own YouTube login, for when YouTube asks to "sign in to confirm
    # you're not a bot": a cookies.txt path, or a browser name (firefox, edge).
    youtube_cookies_file: str = ""
    youtube_cookies_browser: str = ""
    nvidia_api_key: str = ""
    google_api_key: str = ""


def load_settings(dotenv_path: str | None = _DEFAULT_DOTENV_PATH) -> Settings:
    """Build a Settings instance from the process environment.

    Existing process environment variables always win over values in the
    .env file. Pass dotenv_path=None to skip reading any .env file (used by
    tests, so a real .env on disk never leaks into an assertion).
    """
    if dotenv_path is not None:
        load_dotenv(dotenv_path=dotenv_path, override=False)

    return Settings(
        video_mode=_get_str("VIDEO_MODE", "stream"),
        chunk_minutes=_get_int("CHUNK_MINUTES", 30),
        frames_download_max_minutes=_get_int("FRAMES_DOWNLOAD_MAX_MINUTES", 900),
        max_screenshots_per_chunk=_get_int("MAX_SCREENSHOTS_PER_CHUNK", 12),
        transcript_source=_get_str("TRANSCRIPT_SOURCE", "auto"),
        llm_provider=_get_str("LLM_PROVIDER", "nvidia"),
        llm_fallback_provider=_get_str("LLM_FALLBACK_PROVIDER", "gemini"),
        book_order=_get_str("BOOK_ORDER", "topic"),
        video_genre=_get_str("VIDEO_GENRE", "auto"),
        review_outline=_get_bool("REVIEW_OUTLINE", True),
        pass_score=_get_int("PASS_SCORE", 7),
        max_refine_attempts=_get_int("MAX_REFINE_ATTEMPTS", 2),
        llm_parallel_calls=_get_int("LLM_PARALLEL_CALLS", 12),
        max_book_hours=_get_int("MAX_BOOK_HOURS", 30),
        max_book_cost_usd=_get_float("MAX_BOOK_COST_USD", 50),
        volume_hours=_get_float("VOLUME_HOURS", 15),
        transcript_cache_dir=_get_str("TRANSCRIPT_CACHE_DIR", _DEFAULT_TRANSCRIPT_CACHE_DIR),
        youtube_cookies_file=_get_str("YOUTUBE_COOKIES_FILE", ""),
        youtube_cookies_browser=_get_str("YOUTUBE_COOKIES_BROWSER", ""),
        nvidia_api_key=_get_str("NVIDIA_API_KEY", ""),
        google_api_key=_get_str("GOOGLE_API_KEY", ""),
    )
