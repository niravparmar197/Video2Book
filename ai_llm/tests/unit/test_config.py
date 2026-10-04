"""Unit tests for app.config settings loading.

No network or LLM calls here — this only exercises environment-variable parsing.
"""
import os

import pytest

from app.config import Settings, load_settings

ENV_KEYS = [
    "VIDEO_MODE",
    "CHUNK_MINUTES",
    "TRANSCRIPT_SOURCE",
    "LLM_PROVIDER",
    "LLM_FALLBACK_PROVIDER",
    "BOOK_ORDER",
    "REVIEW_OUTLINE",
    "PASS_SCORE",
    "MAX_REFINE_ATTEMPTS",
    "MAX_BOOK_HOURS",
    "MAX_BOOK_COST_USD",
    "VOLUME_HOURS",
    "NVIDIA_API_KEY",
    "GOOGLE_API_KEY",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Ensure no host environment values leak into the default-value tests."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_match_agents_md_table(monkeypatch):
    settings = load_settings(dotenv_path=None)

    assert settings.video_mode == "stream"
    assert settings.chunk_minutes == 30
    assert settings.transcript_source == "auto"
    assert settings.llm_provider == "nvidia"
    assert settings.llm_fallback_provider == "gemini"
    assert settings.book_order == "topic"
    assert settings.review_outline is True
    assert settings.pass_score == 7
    assert settings.max_refine_attempts == 2
    assert settings.max_book_hours == 30
    assert settings.max_book_cost_usd == 50
    assert settings.volume_hours == 15
    assert settings.nvidia_api_key == ""
    assert settings.google_api_key == ""


def test_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("VIDEO_MODE", "captions_only")
    monkeypatch.setenv("CHUNK_MINUTES", "15")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("REVIEW_OUTLINE", "false")
    monkeypatch.setenv("PASS_SCORE", "9")
    monkeypatch.setenv("VOLUME_HOURS", "5")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")

    settings = load_settings(dotenv_path=None)

    assert settings.video_mode == "captions_only"
    assert settings.chunk_minutes == 15
    assert settings.llm_provider == "gemini"
    assert settings.review_outline is False
    assert settings.pass_score == 9
    assert settings.volume_hours == 5
    assert settings.nvidia_api_key == "test-nvidia-key"
    assert settings.google_api_key == "test-google-key"


def test_settings_is_frozen_dataclass():
    settings = Settings()
    with pytest.raises(Exception):
        settings.video_mode = "download"  # type: ignore[misc]
