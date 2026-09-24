"""Configuration loading for the Video2Book core engine.

Settings are read from environment variables, optionally populated from a
.env file first. See root AGENTS.md for the full settings table and the
defaults each one falls back to when unset.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

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
    transcript_source: str = "auto"
    llm_provider: str = "nvidia"
    llm_fallback_provider: str = "gemini"
    book_order: str = "topic"
    review_outline: bool = True
    pass_score: int = 7
    max_refine_attempts: int = 3
    max_book_hours: int = 30
    max_book_cost_usd: float = 50
    volume_hours: float = 10
    nvidia_api_key: str = ""
    google_api_key: str = ""


def load_settings(dotenv_path: str | None = ".env") -> Settings:
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
        transcript_source=_get_str("TRANSCRIPT_SOURCE", "auto"),
        llm_provider=_get_str("LLM_PROVIDER", "nvidia"),
        llm_fallback_provider=_get_str("LLM_FALLBACK_PROVIDER", "gemini"),
        book_order=_get_str("BOOK_ORDER", "topic"),
        review_outline=_get_bool("REVIEW_OUTLINE", True),
        pass_score=_get_int("PASS_SCORE", 7),
        max_refine_attempts=_get_int("MAX_REFINE_ATTEMPTS", 3),
        max_book_hours=_get_int("MAX_BOOK_HOURS", 30),
        max_book_cost_usd=_get_float("MAX_BOOK_COST_USD", 50),
        volume_hours=_get_float("VOLUME_HOURS", 10),
        nvidia_api_key=_get_str("NVIDIA_API_KEY", ""),
        google_api_key=_get_str("GOOGLE_API_KEY", ""),
    )
