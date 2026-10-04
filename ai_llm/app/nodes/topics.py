"""Topics node: extract per-chunk topics via the writer LLM.

Any primary provider error falls back to the secondary provider,
independently per call — see app/llm.py and root AGENTS.md LLM chain.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.llm import call_writer

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "topics.md"
_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")

# A reasoning model can spend its whole completion on chain-of-thought prose
# and never emit the array at all, despite topics.md telling it not to
# (observed against the real NVIDIA API). One retry with this stricter,
# explicit instruction is usually enough to get a clean array back.
_RETRY_SUFFIX = (
    "\n\nYour previous response did not contain a valid JSON array of topic "
    "strings. Respond again with ONLY the JSON array — no reasoning, no "
    "thinking out loud, no markdown code fences, nothing before or after it."
)

logger = logging.getLogger(__name__)


def _load_prompt(transcript: str) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(transcript=transcript)


def _parse_topics(raw_response: str) -> list[str] | None:
    """Extract a JSON array of topic strings from a response.

    Returns None (instead of raising) when the response never resolves to a
    JSON array, so run_topics can retry with a stricter prompt before giving
    up on this chunk.
    """
    text = raw_response.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[len("json") :]
        text = text.strip()

    try:
        topics = json.loads(text)
    except json.JSONDecodeError:
        # A reasoning model can prepend stray prose before/after the array
        # despite instructions not to; fall back to extracting the first
        # top-level [...] block from the full response.
        match = _JSON_ARRAY_RE.search(text)
        if match is None:
            return None
        try:
            topics = json.loads(match.group())
        except json.JSONDecodeError:
            return None

    if not isinstance(topics, list):
        return None
    return [str(topic) for topic in topics]


def topics_output_path(chunk: dict, output_dir: str | Path) -> Path:
    """The deterministic work/topics/<video_id>_<chunk_index>.json path for a chunk.

    Exposed so callers (e.g. graph.py's cache-aware node) can check whether a
    chunk's topics are already on disk without calling the LLM to find out.
    """
    return (
        Path(output_dir)
        / "work"
        / "topics"
        / f"{chunk['video_id']}_{chunk['chunk_index']:03d}.json"
    )


def run_topics(chunk_path: str | Path, output_dir: str | Path) -> Path:
    """Extract topics for one chunk JSON file, writing work/topics/<...>.json.

    If the response never yields a usable JSON array — even after one retry
    with a stricter prompt — this chunk degrades to an empty topics list
    instead of raising, so one bad chunk can't crash the whole book (root
    AGENTS.md crash safety: a run must never have to restart from zero).
    """
    chunk = json.loads(Path(chunk_path).read_text(encoding="utf-8"))

    prompt = _load_prompt(chunk["text"])
    topics = _parse_topics(call_writer(prompt))

    if topics is None:
        topics = _parse_topics(call_writer(prompt + _RETRY_SUFFIX))

    if topics is None:
        logger.warning(
            "topics extraction for %s chunk %s produced no usable JSON array "
            "after a retry; continuing with an empty topics list",
            chunk["video_id"],
            chunk["chunk_index"],
        )
        topics = []

    return write_topics(chunk, topics, output_dir)


def write_topics(chunk: dict, topics: list[str], output_dir: str | Path) -> Path:
    topics_path = topics_output_path(chunk, output_dir)
    topics_path.parent.mkdir(parents=True, exist_ok=True)
    topics_path.write_text(
        json.dumps(
            {
                "video_id": chunk["video_id"],
                "chunk_index": chunk["chunk_index"],
                "topics": topics,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return topics_path


# "1. ", "01 - ", "Part 2: " in front of a YouTube chapter title.
_CHAPTER_NUMBERING_RE = re.compile(r"^\s*(?:part\s*)?\d+\s*[.):\-–—]*\s*", re.IGNORECASE)
_FILLER_CHAPTER_RE = re.compile(
    r"^(?:intro|introduction|outro|ending|end screen|credits|sponsor|sponsors|sponsored|ad|ads|"
    r"advertisement|thanks|thank you|subscribe|bonus|bloopers|q ?& ?a)$",
    re.IGNORECASE,
)
_MIN_CHAPTER_TOPICS = 2


def topics_from_youtube_chapters(chunk: dict, chapters: list[dict]) -> list[str] | None:
    """The chunk's topics from the creator's own YouTube chapters, or None to
    ask the LLM instead.

    A creator's chapter list is the speaker's real structure, so for a video
    that has one the per-chunk topics LLM call is skipped. Used only when the
    chunk has at least two real (non-filler) chapter titles in Latin script:
    a single chapter says too little, and a Hindi or Russian title needs the
    LLM's translation into English.
    """
    start = chunk.get("start_seconds", 0.0)
    end = chunk.get("end_seconds", float("inf"))
    titles = []
    for chapter in chapters:
        if not start <= chapter["start_seconds"] < end:
            continue
        title = _CHAPTER_NUMBERING_RE.sub("", chapter["title"]).strip(" -–—:|")
        if not title or _FILLER_CHAPTER_RE.match(title):
            continue
        letters = [character for character in title if character.isalpha()]
        if not letters or sum(character.isascii() for character in letters) < 0.8 * len(letters):
            return None
        titles.append(title)
    return titles if len(titles) >= _MIN_CHAPTER_TOPICS else None
