"""Plan node: merge repeated topics across the whole playlist (BOOK_ORDER=topic).

A single LLM call reviews every chunk's topic list from every video (topic
labels only, no transcript text -- cheap even on a 30-hour playlist) and
merges the ones that are the same underlying topic, assigning each a needs
list and a difficulty level. See root AGENTS.md book planning rule: "Plan
the whole book before writing any chapter -- merges repeated topics and
orders them correctly."
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.latex.tex import renderable_title
from app.llm import call_writer

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "plan_topics.md"
_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")

# Same rationale as app/nodes/topics.py: a reasoning model can spend its
# whole completion on chain-of-thought prose and never emit the array.
_RETRY_SUFFIX = (
    "\n\nYour previous response did not contain a valid JSON array of merged "
    "topics. Respond again with ONLY the JSON array — no reasoning, no "
    "thinking out loud, no markdown code fences, nothing before or after it."
)

logger = logging.getLogger(__name__)

# sprints/v7 TASKS.md Task 8: a real 6-video playlist run produced 147
# unmerged chapters, several outro/filler ("welcome to statquest", "links
# are in the description below") that topics.py extracted as if they were
# real topics -- the merge LLM would normally recognize and drop these, but
# the degrade-to-unmerged-plan fallback has no such judgment. Filtering
# obvious filler before it ever reaches the merge prompt both keeps that
# prompt cleaner and keeps the degrade fallback from shipping it as a
# first-class book chapter.
_NON_TOPICAL_RE = re.compile(
    r"welcome to|thanks? (you )?for watching|links? (are|is) in the description"
    r"|like( and|,)? subscribe|smash (that|the) like button|check out (the )?description"
    r"|follow (us|me) on|subscribe to (this|my|our) channel",
    re.IGNORECASE,
)

# A merge failure degrading straight to one chapter per raw (unmerged) topic
# string is fine for a handful of chunks, but unbounded it can produce a
# hundreds-of-chapters book that undermines BOOK_ORDER=topic's whole point
# (root AGENTS.md) -- and because LangGraph checkpoints the plan node as
# complete once it returns, a bad degraded plan was previously permanent:
# --resume could not recover it. Past this ceiling, run_plan_topics raises
# instead of writing plan.json, so the node never checkpoints as done and
# --resume gets a real second chance at the merge call.
_MIN_DEGRADED_CHAPTER_CEILING = 20
_MAX_DEGRADED_CHAPTERS_PER_CHUNK = 3


class PlanMergeFailedError(RuntimeError):
    """Raised when the topic-merge LLM call never yields a usable plan and
    the unmerged degrade fallback would exceed a sane chapter-count
    ceiling. Left unhandled so LangGraph does not checkpoint the plan node
    as complete -- see sprints/v7 TASKS.md Task 8.
    """


def _is_topical(topic: str) -> bool:
    topic = topic.strip()
    return bool(topic) and _NON_TOPICAL_RE.search(topic) is None


def _filter_non_topical(chunk_topics: list[dict]) -> list[dict]:
    """Drop filler/outro-shaped topic strings from every chunk's topic
    list, dropping a chunk entirely if nothing topical is left in it.
    """
    filtered = []
    for entry in chunk_topics:
        topics = [topic for topic in entry["topics"] if _is_topical(topic)]
        if topics:
            filtered.append({**entry, "topics": topics})
    return filtered


def _degraded_plan_ceiling(num_chunks: int) -> int:
    return max(_MIN_DEGRADED_CHAPTER_CEILING, _MAX_DEGRADED_CHAPTERS_PER_CHUNK * num_chunks)


def plan_json_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "plan.json"


def _load_all_chunk_topics(output_dir: Path) -> list[dict]:
    """Load every work/topics/<video_id>_<chunk>.json file, in filename order."""
    topics_dir = output_dir / "work" / "topics"
    entries = []
    for topics_path in sorted(topics_dir.glob("*.json")):
        payload = json.loads(topics_path.read_text(encoding="utf-8"))
        entries.append(
            {
                "video_id": payload["video_id"],
                "chunk_index": payload["chunk_index"],
                "topics": payload["topics"],
            }
        )
    return entries


def _load_prompt(topics_by_chunk: list[dict]) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(
        topics_by_chunk=json.dumps(topics_by_chunk, indent=2, ensure_ascii=False)
    )


def _parse_plan(raw_response: str) -> list[dict] | None:
    """Extract a JSON array of merged-topic objects from a response.

    Returns None (instead of raising) when the response never resolves to a
    usable JSON array, so run_plan_topics can retry with a stricter prompt
    before degrading to an unmerged plan.
    """
    text = raw_response.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[len("json") :]
        text = text.strip()

    try:
        plan = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_ARRAY_RE.search(text)
        if match is None:
            return None
        try:
            plan = json.loads(match.group())
        except json.JSONDecodeError:
            return None

    if not isinstance(plan, list):
        return None

    normalized = []
    for entry in plan:
        if not isinstance(entry, dict) or "title" not in entry:
            continue
        sources = [
            {"video_id": str(source["video_id"]), "chunk_index": int(source["chunk_index"])}
            for source in entry.get("sources", [])
            if isinstance(source, dict) and "video_id" in source and "chunk_index" in source
        ]
        normalized.append(
            {
                "title": str(entry["title"]),
                "level": int(entry.get("level", 1)),
                "needs": [str(need) for need in entry.get("needs", [])],
                "sources": sources,
            }
        )
    return normalized


def _degrade_to_unmerged_plan(chunk_topics: list[dict]) -> list[dict]:
    """One plan entry per chunk topic string, unmerged, no needs/level info.

    Used when the merge LLM call never yields a usable response even after
    a retry, so a planning failure degrades the book instead of crashing
    the whole run (root AGENTS.md crash safety).
    """
    return [
        {
            "title": topic,
            "level": 1,
            "needs": [],
            "sources": [{"video_id": entry["video_id"], "chunk_index": entry["chunk_index"]}],
        }
        for entry in chunk_topics
        for topic in entry["topics"]
    ]


def run_single_chunk_plan(output_dir: str | Path, title: str) -> list[dict] | None:
    """Plan a book whose whole source is ONE chunk (a single video of at
    most CHUNK_MINUTES): one chapter titled `title` that covers every topic
    in the chunk, with no LLM call.

    There is nothing to merge across videos, and splitting a short video
    into one chapter per topic cost one write + judge + index-terms call
    per chapter (a 5-minute video produced ~4 one-page chapters) for a
    worse book. The chunk's topics ride along as `covers` so the writer
    gives each its own `##` section. Returns None when the playlist has
    more than one chunk, so the caller runs the real merge instead.
    """
    output_dir = Path(output_dir)
    entries = _load_all_chunk_topics(output_dir)
    if len(entries) != 1:
        return None

    entry = entries[0]
    covers = [topic for topic in entry["topics"] if _is_topical(topic)]
    plan = [
        {
            # A non-Latin YouTube title (Hindi, Russian, ...) can't be printed
            # in the book's font; the topics are always English.
            "title": renderable_title(title, covers[0] if covers else "Video Notes"),
            "level": 1,
            "needs": [],
            "sources": [{"video_id": entry["video_id"], "chunk_index": entry["chunk_index"]}],
            "covers": covers,
        }
    ]
    plan_json_path(output_dir).write_text(
        json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return plan


def run_plan_topics(output_dir: str | Path) -> list[dict]:
    """Merge every chunk's topics across the whole playlist into plan.json.

    Reads work/topics/*.json (written by topics.py for every video/chunk,
    v1) and writes plan.json: one entry per merged topic with title, level,
    needs (other merged topics' titles), and sources (every
    {video_id, chunk_index} chunk that covers it).
    """
    output_dir = Path(output_dir)
    chunk_topics = _filter_non_topical(_load_all_chunk_topics(output_dir))

    prompt = _load_prompt(chunk_topics)
    plan = _parse_plan(call_writer(prompt))

    if plan is None:
        plan = _parse_plan(call_writer(prompt + _RETRY_SUFFIX))

    if plan is None:
        degraded = _degrade_to_unmerged_plan(chunk_topics)
        ceiling = _degraded_plan_ceiling(len(chunk_topics))
        if len(degraded) > ceiling:
            raise PlanMergeFailedError(
                f"topic plan merge failed after a retry, and the unmerged "
                f"fallback would produce {len(degraded)} chapters (ceiling "
                f"{ceiling} for {len(chunk_topics)} chunks) -- refusing to "
                f"write a broken plan.json; retry (e.g. --resume) once the "
                f"writer LLM is healthy"
            )
        logger.warning(
            "topic plan merge produced no usable JSON array after a retry; "
            "degrading to an unmerged plan (one entry per chunk topic)"
        )
        plan = degraded

    plan_json_path(output_dir).write_text(
        json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return plan
