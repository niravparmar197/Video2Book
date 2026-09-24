"""Write node: chapter notes (Markdown) from chunk transcript + topics.

Facts only from the transcript — never invent numbers. See root AGENTS.md
rules for AI-writing steps. `run_write` (BOOK_ORDER=video, v1/v2): one
Markdown notes file per video, generated per chunk then concatenated in
chunk order. `run_write_topic` (BOOK_ORDER=topic, v3): one Markdown notes
file per merged topic, synthesized in a single LLM call from every source
chunk across however many videos cover that topic — not one file per video,
so a topic covered by 3 videos becomes one section, not three.

Every write (per chunk, video mode; per topic, topic mode) is judged and
refined via `_write_and_refine` (sprints/v5 PRD.md): a section scoring
below PASS_SCORE is rewritten with the judge's feedback appended, up to
MAX_REFINE_ATTEMPTS total attempts, then kept as-is regardless of the
final score — root AGENTS.md: "Every chapter is verified; only weak
sections are refined, max 3 tries" and crash safety (a quality gate must
never block the run).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import load_settings
from app.llm import call_writer
from app.nodes.verify import run_verify

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "write_notes.md"
_TOPIC_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "write_topic_notes.md"

logger = logging.getLogger(__name__)


def _write_and_refine(initial_prompt: str, transcript: str) -> str:
    """Write, judge, and refine one section up to MAX_REFINE_ATTEMPTS times.

    Shared by both BOOK_ORDER modes (video-mode chunks, topic-mode
    sections) so the refine loop is implemented once. Always returns the
    last attempt's notes, even if it never reached PASS_SCORE -- a quality
    gate must never block the book.
    """
    settings = load_settings()
    prompt = initial_prompt
    notes = ""

    for attempt in range(1, settings.max_refine_attempts + 1):
        notes = call_writer(prompt).strip()
        result = run_verify(transcript, notes)

        if result.score >= settings.pass_score:
            return notes

        if attempt < settings.max_refine_attempts:
            prompt = (
                f"{initial_prompt}\n\n"
                f"Your previous attempt scored {result.score}/10 from an editor: "
                f"{result.feedback}\nWrite a new, improved version addressing this feedback."
            )
        else:
            logger.warning(
                "section never reached PASS_SCORE (%s) after %s attempts (last score %s); "
                "keeping the last attempt",
                settings.pass_score,
                settings.max_refine_attempts,
                result.score,
            )

    return notes


def _load_prompt(transcript: str, topics: list[str]) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    topics_list = "\n".join(f"- {topic}" for topic in topics)
    return template.format(transcript=transcript, topics=topics_list)


def _write_chunk_notes(chunk_path: Path, topics_path: Path) -> str:
    chunk = json.loads(chunk_path.read_text(encoding="utf-8"))
    topics_payload = json.loads(topics_path.read_text(encoding="utf-8"))
    transcript = chunk["text"]
    prompt = _load_prompt(transcript, topics_payload["topics"])
    return _write_and_refine(prompt, transcript)


def notes_output_path(video_id: str, output_dir: str | Path) -> Path:
    """The deterministic work/notes/<video_id>.md path for a video.

    Exposed so callers (e.g. graph.py's cache-aware node) can check whether a
    video's notes are already on disk without calling the LLM to find out.
    """
    return Path(output_dir) / "work" / "notes" / f"{video_id}.md"


def run_write(video_id: str, output_dir: str | Path) -> Path:
    """Write one Markdown notes file for a video from its chunks + topics."""
    output_dir = Path(output_dir)
    chunks_dir = output_dir / "work" / "chunks"
    topics_dir = output_dir / "work" / "topics"

    chunk_paths = sorted(chunks_dir.glob(f"{video_id}_*.json"))
    if not chunk_paths:
        raise FileNotFoundError(f"no chunks found for video_id={video_id} in {chunks_dir}")

    sections = []
    for chunk_path in chunk_paths:
        topics_path = topics_dir / chunk_path.name
        if not topics_path.exists():
            raise FileNotFoundError(f"missing topics file for chunk: {topics_path}")
        sections.append(_write_chunk_notes(chunk_path, topics_path))

    notes_path = notes_output_path(video_id, output_dir)
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    notes_path.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    return notes_path


def _load_topic_prompt(title: str, sources: list[dict]) -> str:
    template = _TOPIC_PROMPT_PATH.read_text(encoding="utf-8")
    excerpts = "\n\n".join(
        f"[Source: {source['video_id']}, chunk {source['chunk_index']}]\n{source['text']}"
        for source in sources
    )
    return template.format(topic=title, excerpts=excerpts)


def run_write_topic(topic: dict, output_dir: str | Path) -> Path:
    """Write ONE Markdown notes file for a merged-topic chapter, synthesized
    from every source chunk across however many videos cover it.

    `topic` is one chapter from app.nodes.outline.run_topic_outline's
    output: at least `slug`, `title`, and `sources` ([{video_id,
    chunk_index}, ...]).
    """
    output_dir = Path(output_dir)
    chunks_dir = output_dir / "work" / "chunks"

    sources = []
    for source in topic["sources"]:
        chunk_path = chunks_dir / f"{source['video_id']}_{source['chunk_index']:03d}.json"
        if not chunk_path.exists():
            raise FileNotFoundError(f"missing chunk file for topic source: {chunk_path}")
        chunk = json.loads(chunk_path.read_text(encoding="utf-8"))
        sources.append(
            {"video_id": source["video_id"], "chunk_index": source["chunk_index"], "text": chunk["text"]}
        )

    prompt = _load_topic_prompt(topic["title"], sources)
    transcript = "\n\n".join(source["text"] for source in sources)
    notes = _write_and_refine(prompt, transcript)

    notes_path = notes_output_path(f"topic_{topic['slug']}", output_dir)
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    notes_path.write_text(notes + "\n", encoding="utf-8")
    return notes_path
