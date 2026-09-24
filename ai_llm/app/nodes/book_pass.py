"""Book-pass node: preface, glossary, and subject-index terms (sprints/v6 PRD.md).

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

import json
import logging
import re
from pathlib import Path

from app.llm import call_writer

_GLOSSARY_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "glossary.md"
_INDEX_TERMS_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "index_terms.md"
_PREFACE_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "preface.md"

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


def run_glossary(chapters: list[dict], output_dir: str | Path) -> list[dict]:
    """Extract + merge a glossary across every chapter's final notes.

    `chapters` is a list of {"title", "notes"} (one per chapter, in any
    order) sent to the writer LLM in a single call. Terms are deduped
    case-insensitively (defensively, even though the prompt already asks
    the model to merge duplicates itself) -- the first occurrence's
    definition wins for a repeated term.
    """
    output_dir = Path(output_dir)
    prompt = _load_glossary_prompt(chapters)

    raw = _call_with_retry(prompt)
    if raw is None:
        logger.warning(
            "glossary extraction produced no usable JSON array after a retry; "
            "degrading to an empty glossary"
        )
        raw = []

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


def _load_index_terms_prompt(notes: str) -> str:
    template = _INDEX_TERMS_PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(notes=notes)


def run_index_terms(chapter_id: str, notes: str, output_dir: str | Path) -> list[str]:
    """Extract genuinely index-worthy terms from one chapter's notes.

    Degrades to an empty term list (rather than raising) if the response
    never yields a usable JSON array, even after a retry -- a chapter
    missing index terms must not block the book.
    """
    output_dir = Path(output_dir)
    prompt = _load_index_terms_prompt(notes)

    raw = _call_with_retry(prompt)
    if raw is None:
        logger.warning(
            "index term extraction for chapter %s produced no usable JSON array after a "
            "retry; degrading to an empty term list",
            chapter_id,
        )
        raw = []

    terms: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        term = str(entry).strip()
        key = term.lower()
        if not term or key in seen:
            continue
        seen.add(key)
        terms.append(term)

    path = index_terms_json_path(chapter_id, output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(terms, indent=2, ensure_ascii=False), encoding="utf-8")
    return terms


def preface_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "work" / "book_pass" / "preface.md"


def _load_preface_prompt(chapter_titles: list[str]) -> str:
    template = _PREFACE_PROMPT_PATH.read_text(encoding="utf-8")
    titles_list = "\n".join(f"- {title}" for title in chapter_titles)
    return template.format(chapter_titles=titles_list)


def run_preface(chapters: list[dict], output_dir: str | Path) -> Path:
    """Generate a short preface from the book's chapter/topic titles.

    `chapters` is a list of {"title": ...} in book order -- whole-book
    scope, not per-chapter notes, so the preface can only speak in general
    terms about what's covered (root AGENTS.md: never invent facts).
    """
    output_dir = Path(output_dir)
    titles = [chapter["title"] for chapter in chapters]
    prompt = _load_preface_prompt(titles)
    preface_text = call_writer(prompt).strip()

    path = preface_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(preface_text + "\n", encoding="utf-8")
    return path
