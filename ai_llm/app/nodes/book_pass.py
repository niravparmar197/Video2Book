"""Book-pass node: glossary and subject-index terms (sprints/v6 PRD.md).

Grounded in the book's own written content, never invented -- root
AGENTS.md rules for AI-writing steps apply here too. Runs after write
(both BOOK_ORDER modes) once all chapters' final notes are on disk. Reuses
the parse/retry/degrade-gracefully pattern established in topics.py/plan.py
(v1 Task 11, v3 Task 1): a reasoning model can emit chain-of-thought prose
instead of the requested JSON array, so one retry with a stricter prompt
runs before degrading to an empty result -- never raises, never blocks the
book.
"""
from __future__ import annotations

import contextvars
import difflib
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.llm import call_writer

_GLOSSARY_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "glossary.md"

_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")

_RETRY_SUFFIX = (
    "\n\nYour previous response did not contain a valid JSON array. Respond "
    "again with ONLY the JSON array — no reasoning, no thinking out loud, "
    "no markdown code fences, nothing before or after it."
)

logger = logging.getLogger(__name__)


def _parse_json_array(raw_response: str) -> list | None:
    text = raw_response.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[len("json") :]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_ARRAY_RE.search(text)
        if match is None:
            return None
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return None

    if not isinstance(data, list):
        return None
    return data


def _call_with_retry(prompt: str) -> list | None:
    result = _parse_json_array(call_writer(prompt))
    if result is None:
        result = _parse_json_array(call_writer(prompt + _RETRY_SUFFIX))
    return result


def glossary_json_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "work" / "book_pass" / "glossary.json"


def _load_glossary_prompt(chapters: list[dict]) -> str:
    template = _GLOSSARY_PROMPT_PATH.read_text(encoding="utf-8")
    chapters_text = "\n\n".join(
        f"=== Chapter: {chapter['title']} ===\n{chapter['notes']}" for chapter in chapters
    )
    return template.format(chapters=chapters_text)


# One glossary call over every chapter's notes is fine for a 10-minute video
# but at ~13 hours (40+ chapters) it is tens of thousands of tokens: slow, and
# a real risk of hitting the request timeout. Chapters are sent in batches
# (about 15k tokens each) in parallel and the terms merged.
_GLOSSARY_BATCH_CHARS = 60_000
_GLOSSARY_PARALLEL_CALLS = 3


def _glossary_batches(chapters: list[dict]) -> list[list[dict]]:
    """Group chapters, in order, into batches of at most ~_GLOSSARY_BATCH_CHARS
    of notes (a single oversized chapter gets a batch of its own)."""
    batches: list[list[dict]] = []
    current: list[dict] = []
    size = 0
    for chapter in chapters:
        chapter_size = len(chapter["notes"]) + len(chapter["title"])
        if current and size + chapter_size > _GLOSSARY_BATCH_CHARS:
            batches.append(current)
            current, size = [], 0
        current.append(chapter)
        size += chapter_size
    if current:
        batches.append(current)
    return batches or [[]]


def run_glossary(chapters: list[dict], output_dir: str | Path) -> list[dict]:
    """Extract + merge a glossary across every chapter's final notes.

    `chapters` is a list of {"title", "notes"} (one per chapter, in any
    order) sent to the writer LLM in a single call. Terms are deduped
    case-insensitively (defensively, even though the prompt already asks
    the model to merge duplicates itself) -- the first occurrence's
    definition wins for a repeated term.
    """
    output_dir = Path(output_dir)

    batches = _glossary_batches(chapters)
    with ThreadPoolExecutor(max_workers=min(len(batches), _GLOSSARY_PARALLEL_CALLS)) as pool:
        # Each call runs in a copy of this thread's context so per-run context
        # (which book's warnings file to write to) follows it onto pool threads.
        futures = [
            pool.submit(contextvars.copy_context().run, _call_with_retry, _load_glossary_prompt(batch))
            for batch in batches
        ]
        batch_results = [future.result() for future in futures]

    raw: list = []
    for batch_index, batch_result in enumerate(batch_results, start=1):
        if batch_result is None:
            logger.warning(
                "glossary extraction for chapter batch %s of %s produced no usable JSON "
                "array after a retry; that batch contributes no terms",
                batch_index,
                len(batches),
            )
        else:
            raw.extend(batch_result)

    seen: set[str] = set()
    glossary: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict) or "term" not in entry or "definition" not in entry:
            continue
        key = str(entry["term"]).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        glossary.append(
            {"term": str(entry["term"]).strip(), "definition": str(entry["definition"]).strip()}
        )

    glossary.sort(key=lambda item: item["term"].lower())

    path = glossary_json_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(glossary, indent=2, ensure_ascii=False), encoding="utf-8")
    return glossary


def index_terms_json_path(chapter_id: str, output_dir: str | Path) -> Path:
    return Path(output_dir) / "work" / "book_pass" / f"index_terms_{chapter_id}.json"


# **bold** spans of 1-4 words: the terms the writer marks where they are
# first defined (the style rules ask for exactly that).
_BOLD_TERM_RE = re.compile(r"\*\*([^*\n]{2,40})\*\*")
_MAX_INDEX_TERMS = 10


_EMPHASIS_WORDS = frozenset(
    "never always only must should cannot first last before after every both each "
    "also more most less least very same different important".split()
)


def index_terms_from_notes(notes: str, glossary_terms: list[str]) -> list[str]:
    """A chapter's subject-index terms with no LLM call: every glossary term
    the chapter mentions, then the terms it puts in **bold**, deduped
    case-insensitively, at most _MAX_INDEX_TERMS.

    This used to be one LLM call per chapter -- on a real 4-hour book the
    glossary + index step took 190s, most of it these calls -- for terms the
    glossary and the writer's own bold marks already name.
    """
    lowered = notes.lower()
    candidates = [term for term in glossary_terms if term.lower() in lowered]
    for match in _BOLD_TERM_RE.finditer(notes):
        raw = match.group(1).strip()
        # "Object storage (Amazon S3)" is the "Object storage" entry.
        term = re.sub(r"\s*\([^)]*\)", "", raw).rstrip(":.,;").strip()
        # "**1. Request entry**" / "**Step 2:**" are step labels, not terms;
        # they filled a real book's index with junk entries. So did words
        # bolded for emphasis ("Do **not** store ...": an index entry "not").
        if raw.endswith(":") or not term[:1].isalpha() or re.match(r"(?i)step\s*\d", term):
            continue
        if " " not in term and (
            (len(term) < 4 and not term.isupper()) or term.lower() in _EMPHASIS_WORDS
        ):
            continue
        if 1 <= len(term.split()) <= 4:
            candidates.append(term)

    terms: list[str] = []
    seen: set[str] = set()
    for term in candidates:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            terms.append(term)
    return terms[:_MAX_INDEX_TERMS]


def run_index_terms(
    chapter_id: str, notes: str, output_dir: str | Path, glossary_terms: list[str] | None = None
) -> list[str]:
    """Write work/book_pass/index_terms_<chapter_id>.json (see
    index_terms_from_notes) and return the terms."""
    terms = index_terms_from_notes(notes, glossary_terms or [])
    path = index_terms_json_path(chapter_id, output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(terms, indent=2, ensure_ascii=False), encoding="utf-8")
    return terms


# --- complete architecture ------------------------------------------------

_ARCHITECTURE_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "architecture.md"
_ARCHITECTURE_HEADING_RE = re.compile(r"^##\s+Complete Architecture\s*$", re.IGNORECASE | re.MULTILINE)
_ARCHITECTURE_MAX_CHARS = 60_000
_ARCHITECTURE_MAX_NODES = 16
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


def architecture_json_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "work" / "book_pass" / "architecture.json"


def wants_architecture(chapters: list[dict]) -> bool:
    """True when a chapter's writer added a `## Complete Architecture`
    section -- its sign that the talk builds one overall design."""
    return any(_ARCHITECTURE_HEADING_RE.search(chapter["notes"]) for chapter in chapters)


def _valid_diagram(data: object) -> dict | None:
    if not isinstance(data, dict) or data.get("none"):
        return None
    nodes = [str(node).strip() for node in data.get("nodes", []) if str(node).strip()]
    edges = [
        [str(part).strip() for part in edge[:3]]
        for edge in data.get("edges", [])
        if isinstance(edge, list) and len(edge) >= 2
    ]
    for edge in edges:  # an edge may name a node the list forgot
        for name in edge[:2]:
            if name not in nodes:
                nodes.append(name)
    if len(nodes) < 3 or not edges or len(nodes) > _ARCHITECTURE_MAX_NODES:
        return None
    return {"title": str(data.get("title") or "Complete Architecture"), "nodes": nodes, "edges": edges}


def run_architecture(chapters: list[dict], output_dir: str | Path) -> dict | None:
    """One diagram of the whole system, drawn from every chapter's notes.

    A chapter writer only sees its own part of the transcript, so the
    "Complete Architecture" it drew missed components explained elsewhere
    (a real system-design book lost Kafka and its reconciliation service).
    Saves {"diagram": {...} | null}; None when the notes describe no system
    or the reply is unusable -- the chapter's own diagram is then kept.
    """
    text = "\n\n".join(f"=== {chapter['title']} ===\n{chapter['notes']}" for chapter in chapters)
    prompt = _ARCHITECTURE_PROMPT_PATH.read_text(encoding="utf-8").format(
        chapters=text[:_ARCHITECTURE_MAX_CHARS]
    )
    diagram = None
    for attempt_prompt in (prompt, prompt + _RETRY_SUFFIX.replace("JSON array", "JSON object")):
        match = _JSON_OBJECT_RE.search(call_writer(attempt_prompt))
        try:
            diagram = _valid_diagram(json.loads(match.group())) if match else None
        except json.JSONDecodeError:
            diagram = None
        if diagram is not None:
            break
    if diagram is None:
        logger.warning("complete-architecture diagram was unusable; keeping the chapter's own diagram")
    path = architecture_json_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"diagram": diagram}, indent=2, ensure_ascii=False), encoding="utf-8")
    return diagram


def apply_architecture(notes: str, diagram: dict | None) -> str:
    """Replace the diagram in the notes' `## Complete Architecture` section
    with the book-wide one (or add it when the section has none)."""
    heading = _ARCHITECTURE_HEADING_RE.search(notes)
    if diagram is None or heading is None:
        return notes
    next_heading = re.search(r"^##\s", notes[heading.end():], re.MULTILINE)
    end = heading.end() + next_heading.start() if next_heading else len(notes)
    section = notes[heading.end():end]
    block = "```diagram\n" + json.dumps(diagram, ensure_ascii=False) + "\n```"
    fence = re.search(r"```diagram[ \t]*\n.*?\n[ \t]*```", section, re.DOTALL)
    section = (
        section[: fence.start()] + block + section[fence.end():] if fence else section.rstrip() + "\n\n" + block + "\n\n"
    )
    return notes[: heading.end()] + section + notes[end:]


def has_architecture_section(notes: str) -> bool:
    return _ARCHITECTURE_HEADING_RE.search(notes) is not None


def remove_architecture_section(notes: str) -> str:
    """Drop the notes' `## Complete Architecture` section. With one chapter
    per YouTube chapter, two chapters each wrote one and both got the same
    book-wide diagram; only the last chapter's is kept."""
    heading = _ARCHITECTURE_HEADING_RE.search(notes)
    if heading is None:
        return notes
    start = notes.rfind("\n", 0, heading.start()) + 1
    next_heading = re.search(r"^##\s", notes[heading.end():], re.MULTILINE)
    end = heading.end() + next_heading.start() if next_heading else len(notes)
    return notes[:start] + notes[end:]


_DIAGRAM_FENCE_RE =re.compile(r"\n?```diagram[ \t]*\n(.*?)\n[ \t]*```[ \t]*\n?", re.DOTALL)
_SAME_DIAGRAM_OVERLAP = 0.8


def drop_repeated_diagrams(notes: str, seen: list[set[str]]) -> str:
    """Remove a ```diagram whose boxes (80%+ the same) were already drawn
    earlier in the book; `seen` collects each kept diagram's node set and is
    shared across chapters, in book order. A reviewer found the same upload
    flow drawn as two figures in two chapters."""

    def replace(match: re.Match) -> str:
        try:
            nodes = {str(node).strip().lower() for node in json.loads(match.group(1)).get("nodes", [])}
        except (json.JSONDecodeError, AttributeError):
            return match.group(0)
        if len(nodes) >= 3:
            for earlier in seen:
                if len(nodes & earlier) / len(nodes | earlier) >= _SAME_DIAGRAM_OVERLAP:
                    return "\n"
            seen.append(nodes)
        return match.group(0)

    return _DIAGRAM_FENCE_RE.sub(replace, notes)


def ground_glossary(glossary: list[dict], transcript: str, notes: str) -> list[dict]:
    """Drop glossary terms the speaker never said, and merge near-duplicates.

    The glossary is built from the notes, so anything the writer added slips
    in: a real book listed "Redis" (never mentioned) and both "Item Potency
    Key" (a caption error) and "Idempotency Key". A term is kept when each of
    its words (4+ letters) was spoken -- a close caption spelling counts --
    and of two near-identical terms the one the notes use most is kept.
    Skipped for non-English transcripts.
    """
    from app.nodes.verify import _in_vocabulary, _is_english, _vocabulary

    if not _is_english(transcript):
        return glossary
    vocabulary = _vocabulary(transcript)
    # Captions split a term into two words ("item potency" for idempotency),
    # so adjacent spoken words joined together count as spoken too.
    words = re.findall(r"[a-z]+", transcript.lower())
    vocabulary |= {first + second for first, second in zip(words, words[1:])}
    spoken = [
        entry
        for entry in glossary
        if all(_in_vocabulary(word, vocabulary) for word in re.findall(r"[A-Za-z]{4,}", entry["term"]))
    ]

    lowered_notes = notes.lower()

    def squashed(term: str) -> str:
        return re.sub(r"[^a-z]", "", term.lower())

    kept: list[dict] = []
    for entry in sorted(spoken, key=lambda item: -lowered_notes.count(item["term"].lower())):
        if any(
            difflib.SequenceMatcher(None, squashed(entry["term"]), squashed(other["term"])).ratio() >= 0.85
            for other in kept
        ):
            continue
        kept.append(entry)
    dropped = len(glossary) - len(kept)
    if dropped:
        logger.warning("glossary: dropped %s unspoken or duplicate term(s)", dropped)
    return sorted(kept, key=lambda item: item["term"].lower())
