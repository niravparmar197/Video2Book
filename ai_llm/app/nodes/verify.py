"""Verify node: judge score for a written section (sprints/v5 PRD.md).

A second LLM call scores a written section against its source transcript;
a section scoring below PASS_SCORE is refined (app/nodes/write.py's
refine loop) up to MAX_REFINE_ATTEMPTS times. Uses the same writer-tier
model as write.py/topics.py/plan.py -- root AGENTS.md's LLM chain names one
model for both "writing/judging", not a separate judge model. See root
AGENTS.md: "Every chapter is verified; only weak sections are refined, max
3 tries."
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.config import load_settings
from app.llm import call_writer

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "judge.md"
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerifyResult:
    score: int
    feedback: str


def _load_prompt(transcript: str, notes: str) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(transcript=transcript, notes=notes)


def _parse_verify_response(raw_response: str) -> VerifyResult | None:
    text = raw_response.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[len("json") :]
        text = text.strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(text)
        if match is None:
            return None
        try:
            payload = json.loads(match.group())
        except json.JSONDecodeError:
            return None

    if not isinstance(payload, dict) or "score" not in payload:
        return None

    try:
        score = int(payload["score"])
    except (TypeError, ValueError):
        return None

    return VerifyResult(score=score, feedback=str(payload.get("feedback", "")))


def run_verify(transcript: str, notes: str) -> VerifyResult:
    """Judge a written section against its source transcript.

    Never raises: a malformed/unparseable judge response degrades to a
    borderline score (PASS_SCORE - 1, so it triggers one refine attempt
    rather than silently passing unjudged output) with a logged warning --
    one bad judge response must not crash the whole write+verify loop.
    """
    prompt = _load_prompt(transcript, notes)
    result = _parse_verify_response(call_writer(prompt))

    if result is None:
        logger.warning(
            "judge response was unparseable; defaulting to a borderline score "
            "so the section gets one refine attempt"
        )
        borderline = load_settings().pass_score - 1
        return VerifyResult(score=borderline, feedback="judge response was unparseable")

    return result
