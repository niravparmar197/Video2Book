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
import re
from pathlib import Path

from app.config import load_settings
from app.llm import call_writer
from app.nodes.genre import DEFAULT_GENRE, load_genre
from app.nodes.verify import (
    MIN_UNSUPPORTED_TO_ACT,
    VerifyResult,
    clean_notes,
    drop_unspoken_quotes,
    find_unsupported_terms,
    remove_unsupported_terms,
    run_verify,
    strip_ungrounded_visuals,
)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_PROMPT_PATH = _PROMPTS_DIR / "write_notes.md"
_TOPIC_PROMPT_PATH = _PROMPTS_DIR / "write_topic_notes.md"
_REVISE_PROMPT_PATH = _PROMPTS_DIR / "revise_notes.md"


def _style_rules(genre: str) -> str:
    """The rules for this kind of book: shared grounding, then the genre's own
    role/layout (study notes, podcast notes or comedy recap), then the shared
    output rules -- so a lecture, a podcast and a comedy show each read like
    the right kind of book, without three copies of the grounding rules."""
    parts = ("_grounding.md", f"_style_{genre}.md", "_output.md")
    return "\n\n".join((_PROMPTS_DIR / name).read_text(encoding="utf-8").strip() for name in parts)

logger = logging.getLogger(__name__)


def _write_and_refine(
    initial_prompt: str, transcript: str, genre: str = DEFAULT_GENRE
) -> tuple[str, int, int]:
    """Write, judge, and refine one section up to MAX_REFINE_ATTEMPTS times.

    Shared by both BOOK_ORDER modes (video-mode chunks, topic-mode
    sections) so the refine loop is implemented once. Always returns the
    last attempt's notes, even if it never reached PASS_SCORE -- a quality
    gate must never block the book. Also returns the kept attempt's judge
    score and how many attempts it took (sprints/v9: per-chapter progress
    sidecar), so callers can persist a real pass/fail signal instead of
    just "notes exist".
    """
    settings = load_settings()
    prompt = initial_prompt
    notes = ""
    score = 0

    best_notes, best_score = "", -1

    for attempt in range(1, settings.max_refine_attempts + 1):
        raw_notes = strip_ungrounded_visuals(call_writer(prompt), transcript)
        notes = drop_unspoken_quotes(clean_notes(raw_notes), transcript).strip()
        result = run_verify(transcript, notes)

        # The judge is the same small model as the writer and passed a book
        # full of invented names (9/10), so check in code too: names that never
        # occur in the transcript fail the section, with the names as feedback.
        unsupported = find_unsupported_terms(notes, transcript)
        if len(unsupported) >= MIN_UNSUPPORTED_TO_ACT and result.score >= settings.pass_score:
            result = VerifyResult(
                score=settings.pass_score - 1,
                feedback=(
                    "These names never appear in the transcript: "
                    + ", ".join(unsupported[:12])
                    + ". Delete every sentence, bullet, table row, diagram and example that "
                    "relies on them, and use only what the speaker actually said."
                ),
            )
        score = result.score

        if score >= settings.pass_score:
            return notes, score, attempt

        # A rewrite can score lower than the attempt before it; keep the best
        # (the later one on a tie), not simply the last.
        if score >= best_score:
            best_notes, best_score = notes, score

        if attempt < settings.max_refine_attempts:
            # Revise the attempt with the editor's feedback instead of writing
            # from scratch: a fresh rewrite lost the parts that were fine and
            # sometimes scored lower than the attempt it replaced (6 -> 5).
            prompt = _REVISE_PROMPT_PATH.read_text(encoding="utf-8").format(
                score=result.score,
                feedback=result.feedback or "(no details given)",
                rules=_style_rules(genre),
                notes=notes,
                transcript=transcript,
            )
        else:
            logger.warning(
                "section never reached PASS_SCORE (%s) after %s attempts (last score %s); "
                "keeping the best attempt (score %s)",
                settings.pass_score,
                settings.max_refine_attempts,
                result.score,
                best_score,
            )

    # Out of attempts: remove what is still invented rather than ship it.
    leftover = find_unsupported_terms(best_notes, transcript)
    if len(leftover) >= MIN_UNSUPPORTED_TO_ACT:
        logger.warning("removed content using names not in the transcript: %s", leftover)
        best_notes = remove_unsupported_terms(best_notes, leftover)
    return best_notes, best_score, settings.max_refine_attempts


def _load_prompt(transcript: str, topics: list[str], genre: str = DEFAULT_GENRE) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    topics_list = "\n".join(f"- {topic}" for topic in topics)
    return template.format(
        transcript=transcript,
        topics=topics_list,
        style_rules=_style_rules(genre),
    )


def _write_chunk_notes(
    chunk_path: Path, topics_path: Path, genre: str = DEFAULT_GENRE
) -> tuple[str, int, int]:
    chunk = json.loads(chunk_path.read_text(encoding="utf-8"))
    topics_payload = json.loads(topics_path.read_text(encoding="utf-8"))
    transcript = chunk["text"]
    prompt = _load_prompt(transcript, topics_payload["topics"], genre)
    return _write_and_refine(prompt, transcript, genre)


# Each genre's closing section and the callout lines it can be rebuilt from.
_CLOSING_SECTIONS = {
    "lecture": ("Key Takeaways", "key point"),
    "podcast": ("Key Takeaways", "key point"),
    "comedy": ("Best Moments", "quote"),
}
_MAX_CLOSING_BULLETS = 6


def ensure_closing_section(notes: str, genre: str) -> str:
    """Add the genre's closing section (Key Takeaways / Best Moments) when the
    writer left it out -- a real comedy recap simply ended without its Best
    Moments. Rebuilt with no LLM call from the chapter's own `> Key point:`
    (or `> Quote:`) lines, so it can only repeat what the chapter already
    says. Left alone when present, or when there is nothing to build it from.
    """
    heading, label = _CLOSING_SECTIONS.get(genre, _CLOSING_SECTIONS["lecture"])
    if re.search(rf"^##\s+{re.escape(heading)}\s*$", notes, re.IGNORECASE | re.MULTILINE):
        return notes
    callout = re.compile(rf"^>\s*\**{label}\**\s*:\s*\**\s*(.+)$", re.IGNORECASE | re.MULTILINE)
    points = [match.group(1).strip() for match in callout.finditer(notes)][:_MAX_CLOSING_BULLETS]
    if not points:
        return notes
    bullets = "\n".join(f"- {point}" for point in points)
    return f"{notes.rstrip()}\n\n## {heading}\n{bullets}"


def notes_output_path(video_id: str, output_dir: str | Path) -> Path:
    """The deterministic work/notes/<video_id>.md path for a video.

    Exposed so callers (e.g. graph.py's cache-aware node) can check whether a
    video's notes are already on disk without calling the LLM to find out.
    """
    return Path(output_dir) / "work" / "notes" / f"{video_id}.md"


def chapter_status_path(key: str, output_dir: str | Path) -> Path:
    """The deterministic work/notes/<key>.status.json path for a chapter --
    sibling of notes_output_path's .md, same <key> (sprints/v9: per-chapter
    progress). Written alongside the notes file once the chapter's
    write-and-verify loop finishes."""
    return Path(output_dir) / "work" / "notes" / f"{key}.status.json"


def _write_chapter_status(key: str, output_dir: str | Path, score: int, attempts: int) -> None:
    settings = load_settings()
    status_path = chapter_status_path(key, output_dir)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(
        json.dumps({"score": score, "attempts": attempts, "passed": score >= settings.pass_score}),
        encoding="utf-8",
    )


def run_write(video_id: str, output_dir: str | Path) -> Path:
    """Write one Markdown notes file for a video from its chunks + topics."""
    output_dir = Path(output_dir)
    chunks_dir = output_dir / "work" / "chunks"
    topics_dir = output_dir / "work" / "topics"

    chunk_paths = sorted(chunks_dir.glob(f"{video_id}_*.json"))
    if not chunk_paths:
        raise FileNotFoundError(f"no chunks found for video_id={video_id} in {chunks_dir}")

    sections = []
    scores = []
    attempts_list = []
    for chunk_path in chunk_paths:
        topics_path = topics_dir / chunk_path.name
        if not topics_path.exists():
            raise FileNotFoundError(f"missing topics file for chunk: {topics_path}")
        notes, score, attempts = _write_chunk_notes(chunk_path, topics_path, load_genre(output_dir))
        sections.append(notes)
        scores.append(score)
        attempts_list.append(attempts)

    notes_path = notes_output_path(video_id, output_dir)
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    notes = ensure_closing_section("\n\n".join(sections), load_genre(output_dir))
    notes_path.write_text(notes + "\n", encoding="utf-8")
    _write_chapter_status(video_id, output_dir, min(scores), max(attempts_list))
    return notes_path


def _load_topic_prompt(
    title: str, sources: list[dict], covers: list[str], genre: str = DEFAULT_GENRE
) -> str:
    template = _TOPIC_PROMPT_PATH.read_text(encoding="utf-8")
    excerpts = "\n\n".join(
        f"[Source: {source['video_id']}, chunk {source['chunk_index']}]\n{source['text']}"
        for source in sources
    )
    # A single-chunk book is one chapter spanning every topic found in it
    # (graph.py's _plan_node): list them so each gets its own `##` section.
    covers_text = (
        "Give each of these its own `##` section, in this order:\n"
        + "\n".join(f"- {point}" for point in covers)
        if covers
        else ""
    )
    return template.format(
        topic=title,
        covers=covers_text,
        excerpts=excerpts,
        style_rules=_style_rules(genre),
    )


def run_write_topic(topic: dict, output_dir: str | Path) -> Path:
    """Write ONE Markdown notes file for a merged-topic chapter, synthesized
    from every source chunk across however many videos cover it.

    `topic` is one chapter from app.nodes.outline.run_topic_outline's
    output: at least `slug`, `title`, and `sources` ([{video_id,
    chunk_index}, ...]); optionally `covers`, the sub-topics to give their
    own sections.
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

    prompt = _load_topic_prompt(
        topic["title"], sources, topic.get("covers", []), load_genre(output_dir)
    )
    transcript = "\n\n".join(source["text"] for source in sources)
    notes, score, attempts = _write_and_refine(prompt, transcript, load_genre(output_dir))
    notes = ensure_closing_section(notes, load_genre(output_dir))

    key = f"topic_{topic['slug']}"
    notes_path = notes_output_path(key, output_dir)
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    notes_path.write_text(notes + "\n", encoding="utf-8")
    _write_chapter_status(key, output_dir, score, attempts)
    return notes_path
