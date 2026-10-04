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
        term = match.group(1).strip().rstrip(":.,;")
        if 1 <= len(term.split()) <= 4 and any(character.isalpha() for character in term):
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
