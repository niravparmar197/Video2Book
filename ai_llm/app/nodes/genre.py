"""Genre node: is the book a lecture, a podcast or a comedy show?

The writer uses a different style for each (study notes / podcast notes /
comedy recap), the book pass skips the glossary and index for comedy, and
the title page names the kind of book. VIDEO_GENRE forces a genre; the
default `auto` asks the writer LLM once per video, from its title and the
start of its first chunk -- a short call that runs alongside topics.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path

from app.config import load_settings
from app.llm import call_writer

GENRES = ("lecture", "podcast", "comedy")
DEFAULT_GENRE = "lecture"
BOOK_KINDS = {"lecture": "Study Notes", "podcast": "Podcast Notes", "comedy": "Comedy Recap"}

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "genre.md"
_TRANSCRIPT_SAMPLE_CHARS = 3000

logger = logging.getLogger(__name__)


def genre_json_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "work" / "genre.json"


def load_genre(output_dir: str | Path) -> str:
    """The book's genre, or the default if it hasn't been decided (yet)."""
    path = genre_json_path(output_dir)
    if not path.exists():
        return DEFAULT_GENRE
    genre = json.loads(path.read_text(encoding="utf-8")).get("genre")
    return genre if genre in GENRES else DEFAULT_GENRE


def _parse_genre(response: str) -> str | None:
    match = re.search(r"\b(lecture|podcast|comedy)\b", response.lower())
    return match.group(1) if match else None


def _classify_video(video: dict, output_dir: Path) -> str:
    first_chunk = output_dir / "work" / "chunks" / f"{video['video_id']}_000.json"
    sample = ""
    if first_chunk.exists():
        sample = json.loads(first_chunk.read_text(encoding="utf-8"))["text"][:_TRANSCRIPT_SAMPLE_CHARS]
    prompt = _PROMPT_PATH.read_text(encoding="utf-8").format(
        title=video["title"], channel=video.get("channel") or "unknown", transcript=sample
    )
    genre = _parse_genre(call_writer(prompt))
    if genre is None:
        logger.warning("genre for %s was unclear; using %s", video["video_id"], DEFAULT_GENRE)
        return DEFAULT_GENRE
    return genre


def decided_book_kind(output_dir: str | Path) -> str | None:
    """"Study Notes" / "Podcast Notes" / "Comedy Recap" once the book's genre
    is decided (or chosen), else None -- for progress displays."""
    if not genre_json_path(output_dir).exists():
        return None
    return BOOK_KINDS[load_genre(output_dir)]


def save_genre(output_dir: str | Path, genre: str) -> None:
    """Record a genre the user chose (e.g. in the web app) before the book
    runs; the topics step only decides the genre when none is saved yet."""
    if genre not in GENRES:
        raise ValueError(f"unknown genre {genre!r}; expected one of {GENRES}")
    path = genre_json_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"genre": genre, "chosen_by_user": True}, indent=2), encoding="utf-8")


def run_genre(videos: list[dict], output_dir: str | Path) -> str:
    """Decide the book's genre and write work/genre.json.

    A playlist gets its most common genre (ties go to the first video's), so
    one style runs through the whole book.
    """
    output_dir = Path(output_dir)
    forced = load_settings().video_genre
    if forced in GENRES:
        per_video = {video["video_id"]: forced for video in videos}
    else:
        per_video = {video["video_id"]: _classify_video(video, output_dir) for video in videos}

    counts = Counter(per_video.values())
    genre = max(per_video.values(), key=lambda g: counts[g]) if per_video else DEFAULT_GENRE

    path = genre_json_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"genre": genre, "per_video": per_video}, indent=2), encoding="utf-8")
    return genre
