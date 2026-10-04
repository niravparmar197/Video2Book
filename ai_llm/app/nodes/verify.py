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

import difflib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.config import load_settings
from app.llm import call_writer

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "judge.md"
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")

# A judge that replies with prose instead of the JSON object is re-asked once.
_RETRY_SUFFIX = (
    "\n\nYour previous response was not the required JSON object. Respond again with "
    'ONLY {"score": <1-10>, "feedback": "<short feedback>"} -- no reasoning, no code fences.'
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerifyResult:
    score: int
    feedback: str


def _load_prompt(transcript: str, notes: str) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(transcript=transcript, notes=notes)


_SCORE_RE = re.compile(r'"?score"?\s*[:=]\s*"?(\d{1,2})\b', re.IGNORECASE)
_FEEDBACK_RE = re.compile(r'"?feedback"?\s*[:=]\s*"(.*)"\s*}?\s*$', re.IGNORECASE | re.DOTALL)


def _parse_broken_json(text: str) -> VerifyResult | None:
    """Read the score out of an almost-JSON reply. The usual failure is a
    double quote inside "feedback" ({"score": 6, "feedback": "say "fast" ..."}),
    which breaks json.loads although the score is plainly there -- that cost a
    retry and then a needless rewrite of the whole section."""
    score_match = _SCORE_RE.search(text)
    if score_match is None:
        return None
    score = int(score_match.group(1))
    if not 1 <= score <= 10:
        return None
    feedback_match = _FEEDBACK_RE.search(text)
    return VerifyResult(score=score, feedback=feedback_match.group(1) if feedback_match else "")


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
        try:
            payload = json.loads(match.group()) if match else None
        except json.JSONDecodeError:
            payload = None
        if payload is None:
            return _parse_broken_json(text)

    if not isinstance(payload, dict) or "score" not in payload:
        return None

    try:
        score = int(payload["score"])
    except (TypeError, ValueError):
        return None

    return VerifyResult(score=score, feedback=str(payload.get("feedback", "")))


def run_verify(transcript: str, notes: str) -> VerifyResult:
    """Judge a written section against its source transcript.

    Never raises. A malformed judge reply is re-asked ONCE (a short call)
    before anything else: previously it went straight to a borderline score,
    which forced a full rewrite + re-judge of the section just because the
    judge fumbled its JSON. Only if the retry is also unusable does it
    degrade to a borderline score (PASS_SCORE - 1, so it still triggers one
    refine attempt rather than silently passing unjudged output), with a
    logged warning.
    """
    prompt = _load_prompt(transcript, notes)
    result = _parse_verify_response(call_writer(prompt))

    if result is None:
        result = _parse_verify_response(call_writer(prompt + _RETRY_SUFFIX))

    if result is None:
        logger.warning(
            "judge response was unparseable after a retry; defaulting to a borderline "
            "score so the section gets one refine attempt"
        )
        borderline = load_settings().pass_score - 1
        return VerifyResult(score=borderline, feedback="judge response was unparseable")

    return result


# --- chart grounding ---------------------------------------------------

# A cell that is only a row index ("1", "2.") is numbering, not a claim.
_INDEX_CELL_RE = re.compile(r"\s*(?:[1-9]|10)[.)]?\s*")
_VISUAL_BLOCK_RE = re.compile(r"```(chart|table)[ \t]*\n(.*?)\n[ \t]*```", re.DOTALL)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_NUMBER_WORDS = {
    word: number
    for number, word in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen "
        "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
    )
}
_NUMBER_WORDS.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "hundred": 100})


def _is_english(transcript: str) -> bool:
    """True when the transcript is mostly Latin letters. The grounding checks
    compare the English notes with the transcript's own words; a Hindi or
    Russian caption track (the notes are translated) shares none of them, so
    every name would look "invented" and good content would be deleted."""
    letters = [character for character in transcript if character.isalpha()]
    return not letters or sum(character.isascii() for character in letters) / len(letters) >= 0.7


def _numbers_in(text: str) -> set[float]:
    numbers = {float(match) for match in _NUMBER_RE.findall(text)}
    numbers.update(
        float(_NUMBER_WORDS[word])
        for word in re.findall(r"[a-z]+", text.lower())
        if word in _NUMBER_WORDS
    )
    return numbers


def strip_ungrounded_visuals(notes: str, transcript: str) -> str:
    """Remove numbers the speaker never said from ```chart and ```table blocks.

    The writer prompt only allows numbers from the transcript, but a model
    still "completes" a visual with a derived one (a real book showed a chart
    "UML 15 min / Coding 30 min" and a table "Coding 25-35" when the speaker
    only said "10-15 minutes on UML"). That is checked in code, not left to
    the judge: a chart with any unspoken value is dropped; a table loses each
    row containing an unspoken number (and is dropped if no row is left).
    A block whose JSON can't be parsed is left alone -- render drops it with
    its own warning.
    """
    if not _is_english(transcript):
        return notes
    spoken = _numbers_in(transcript)

    def check(match: re.Match) -> str:
        kind, body = match.groups()
        try:
            data = json.loads(body)
            if kind == "chart":
                invented = [v for v in data.get("values", []) if float(v) not in spoken]
                if invented:
                    logger.warning("dropped a chart with unspoken values %s", invented)
                    return ""
                return match.group(0)

            rows = data.get("rows", [])
            kept = [
                row
                for row in rows
                if _numbers_in(
                    " ".join(str(cell) for cell in row if not _INDEX_CELL_RE.fullmatch(str(cell)))
                )
                <= spoken
            ]
        except (ValueError, TypeError, AttributeError):
            return match.group(0)
        if len(kept) == len(rows):
            return match.group(0)
        logger.warning("dropped %s table row(s) containing unspoken numbers", len(rows) - len(kept))
        if not kept:
            return ""
        return "```table\n" + json.dumps({**data, "rows": kept}, ensure_ascii=False) + "\n```"

    return _VISUAL_BLOCK_RE.sub(check, notes)


# --- unsupported names -------------------------------------------------

_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_LABEL_RE = re.compile(
    r"^>\s*\**(?:key point|remember|tip|note|example|watch out|warning|quote)\**\s*:\s*\**\s*",
    re.IGNORECASE,
)
_EMPHASIS_SPAN_RE = re.compile(r"\*\*(.+?)\*\*|(?<!\*)\*(?!\*)(.+?)\*|`([^`\n]+)`")
# Acronyms (HLD, UML) are skipped: the speaker says "high level design".
_CAPITALISED_RE = re.compile(r"^[A-Z][a-z]{2,}$")
# TwoWheeler -> Two Wheeler: the speaker says the words, not the identifier.
_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")
_SENTENCE_END_RE = re.compile(r"[.!?:]$")
_SUFFIXES = ("ing", "ed", "es", "s", "ly")
_HYPHENS_RE = re.compile(r"[-‐-―−]")
# One or two odd words can be a paraphrase; three or more names the speaker
# never said is a hallucinated list/example worth forcing a rewrite over.
MIN_UNSUPPORTED_TO_ACT = 3


def _vocabulary(transcript: str) -> set[str]:
    return set(re.findall(r"[a-z]+", transcript.lower()))


def _in_vocabulary(word: str, vocabulary: set[str]) -> bool:
    word = word.lower()
    if word in vocabulary or any(
        word.endswith(suffix) and word[: -len(suffix)] in vocabulary for suffix in _SUFFIXES
    ):
        return True
    # Auto-captions misspell technical names ("kubernates" for Kubernetes,
    # "graphql" heard where the notes say Graph): a close spelling counts as
    # spoken. Without this a real system-design book lost its Kubernetes lines.
    return len(word) >= 5 and bool(difflib.get_close_matches(word, vocabulary, n=1, cutoff=0.8))


def find_unsupported_terms(notes: str, transcript: str) -> list[str]:
    """Names and terms the notes put in emphasis (**bold**, *italic*, `code`)
    or capitalise mid-sentence that never occur anywhere in the transcript.

    A small writer model fills a list or example with plausible-looking names
    it knows from training (a real book listed Observer/Strategy/Command and
    invented Car/Spot/Ticket classes for a speaker who never said them), and
    a same-model judge scored that 9/10. The check is deliberately crude --
    "does this word occur in the transcript at all?" -- so it cannot be
    argued with. `Think of it like` analogies are skipped: they are allowed
    to bring in outside images. Returns the distinct offenders, in order.
    """
    if not _is_english(transcript):
        return []
    vocabulary = _vocabulary(transcript)
    found: dict[str, None] = {}

    for line in _FENCE_RE.sub("", notes).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "think of it like" in line.lower():
            continue
        line = _LABEL_RE.sub("", line)
        line = re.sub(r"^[-*•]\s+|^\d+[.)]\s+", "", line)
        line = _HYPHENS_RE.sub(" ", line)  # "Is-a" is two words, not "isa"

        words: list[str] = []
        for match in _EMPHASIS_SPAN_RE.finditer(line):
            is_code = match.group(3) is not None
            before = line[: match.start()].rstrip()
            if not is_code and (not before or _SENTENCE_END_RE.search(before)):
                # "- **Pick** one problem": a bolded first word is emphasis, not a name.
                continue
            span = _CAMEL_RE.sub(" ", next(group for group in match.groups() if group))
            # Names are capitalised; an emphasised everyday word ("**effort**",
            # "*rapid experiments*", `key`, `runtime`) is a paraphrase or a
            # technical term, not an invented name -- flagging those deleted
            # good lines from real podcast and system-design books.
            words.extend(word for word in re.findall(r"[A-Za-z]{3,}", span) if word[0].isupper())

        previous = ""
        # A bolded lead-in ("- **Embrace Tactics** that work") is a heading-like
        # emphasis, so its title-case words are not names either.
        plain = re.sub(r"^\*{1,2}[^*]+\*{1,2}:?", "", line)
        for index, token in enumerate(re.sub(r"\*+|`", "", plain).split()):
            word = re.sub(r"[^A-Za-z ]", "", _CAMEL_RE.sub(" ", token)).split(" ")[0]
            sentence_start = index == 0 or _SENTENCE_END_RE.search(previous)
            if not sentence_start and _CAPITALISED_RE.match(word):
                words.append(word)
            previous = token

        for word in words:
            if not word.isupper() and not _in_vocabulary(word, vocabulary):
                found.setdefault(word.lower(), None)

    return list(found)


def remove_unsupported_terms(notes: str, terms: list[str]) -> str:
    """Delete every line, and every ```diagram/```table/```chart block, that
    mentions one of `terms` as a whole word (headings are kept)."""
    if not terms:
        return notes
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(term) for term in terms) + r")\b", re.IGNORECASE)

    notes = _FENCE_RE.sub(lambda match: "" if pattern.search(match.group(0)) else match.group(0), notes)
    kept = [line for line in notes.splitlines() if line.lstrip().startswith("#") or not pattern.search(line)]
    return "\n".join(kept)


_EMPTY_CALLOUT_RE = re.compile(
    r"^>\s*\**(?:key point|remember|tip|note|example|watch out|warning|quote)\**\s*:\s*\**\s*"
    r"(?:none|n/?a|nothing|no\b.*|not (?:given|mentioned|stated).*)\.?\**\s*$",
    re.IGNORECASE,
)
_META_RE = re.compile(
    r"\b(?:in|from) (?:the )?(?:source|transcript)\b"
    r"|not (?:explicitly )?(?:listed|named|stated|mentioned|given)\b|\(repeated\b|\(no mention of\b",
    re.IGNORECASE,
)


# The model turns "add a visual aid" into a literal "### Visual" heading.
_STRAY_HEADING_RE = re.compile(r"^#{2,4}\s*(?:visual(?: aid)?|diagram|table|chart)\s*$", re.IGNORECASE)


_ANALOGY_LEAD_RE = re.compile(
    r"^>\s*\**think of it like\**\s*:\s*(?:\**think of it like\**\s*)?",
    re.IGNORECASE | re.MULTILINE,
)


_BULLET_QUOTE_RE = re.compile(r"^\s*(?:[-*]\s+)?\*\*quote:?\*\*:?\s*", re.IGNORECASE | re.MULTILINE)


def clean_notes(notes: str) -> str:
    """Drop callouts that only say "None"/"No ... given", lines that talk
    about the source ("not explicitly named in source") and stray "### Visual"
    headings -- the model leaks all three even when told not to. Also turns a
    "> Think of it like: **Think of it like** a ..." line into a proper
    Example callout instead of a doubled lead-in."""
    notes = _ANALOGY_LEAD_RE.sub("> Example: Think of it like ", notes)
    # "- **Quote:** "..."" written as a bullet belongs in the Quote box.
    notes = _BULLET_QUOTE_RE.sub("> Quote: ", notes)
    kept = [
        line
        for line in notes.splitlines()
        if not _EMPTY_CALLOUT_RE.match(line.strip())
        and not _META_RE.search(line)
        and not _STRAY_HEADING_RE.match(line.strip())
    ]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept))


# --- quotes --------------------------------------------------------------

_QUOTE_LINE_RE = re.compile(r"^>\s*\**quote\**\s*:\s*\**\s*(.+)$", re.IGNORECASE)
_QUOTED_TEXT_RE = re.compile(r"[\"\u201c\u201d](.+?)[\"\u201c\u201d]")
_QUOTE_WORD_RE = re.compile(r"[a-z0-9']+")
_MIN_QUOTE_WORDS = 4
# A Quote box claims the speaker's exact words: ~80% of them must be there.
_QUOTE_MATCH_SHARE = 0.8
# Quoted text inside a bullet below this is invented; between this and 0.8 it
# is a paraphrase or caption-corrected ("garlic naan" for "garlic nun").
_PARAPHRASE_SHARE = 0.5
# "\u2026" / "..." joins separate stretches of speech; each part is checked alone.
_ELLIPSIS_RE = re.compile(r"\u2026|\.\.\.")


def _quote_words(text: str) -> list[str]:
    return _QUOTE_WORD_RE.findall(text.lower().replace("\u2019", "'"))


def _part_share(words: list[str], transcript_words: list[str], positions: dict[str, list[int]]) -> float:
    """Best share of `words` found in order in one stretch of the transcript,
    anchored on the rarest word so it stays fast on long transcripts."""
    anchors = [word for word in words if word in positions]
    if not anchors:
        return 0.0
    anchor = min(anchors, key=lambda word: len(positions[word]))
    offset = words.index(anchor)
    span = len(words)
    best = 0.0
    for position in positions[anchor]:
        start = max(0, position - offset - span // 2)
        window = transcript_words[start : position - offset + span + span // 2]
        matcher = difflib.SequenceMatcher(None, words, window, autojunk=False)
        best = max(best, sum(block.size for block in matcher.get_matching_blocks()) / span)
    return best


def _spoken_share(quote: str, transcript_words: list[str], positions: dict[str, list[int]]) -> float:
    """How much of the quote the speaker actually said (1.0 = all of it), each
    "\u2026"-separated part checked on its own and weighted by length."""
    parts = [_quote_words(part) for part in _ELLIPSIS_RE.split(quote)]
    parts = [words for words in parts if words]
    total = sum(len(words) for words in parts)
    if total < _MIN_QUOTE_WORDS:
        return 1.0  # too short to judge ("Exactly.")
    return sum(len(words) * _part_share(words, transcript_words, positions) for words in parts) / total


def drop_unspoken_quotes(notes: str, transcript: str) -> str:
    """Remove `> Quote:` lines -- and quoted lines in a list, like a comedy
    recap's Best Moments -- whose words the speaker never said.

    The eval set's lowest scores (podcast 5/10, comedy 3/10) were reworded,
    invented or misattributed quotes, which the prompt alone does not stop.
    A `> Quote:` box is kept only when ~80% of its words appear in order in
    one place in the transcript (each "…" part on its own). Quoted text in a
    bullet is judged more loosely: clearly invented (<50%) drops the bullet;
    close but not exact (a paraphrase, or captions corrected to "garlic naan")
    keeps the bullet without the quote marks, so it no longer claims to be
    verbatim. Skipped for non-English transcripts, where every quote is a
    translation.
    """
    if not _is_english(transcript):
        return notes
    transcript_words = _quote_words(transcript)
    positions: dict[str, list[int]] = {}
    for index, word in enumerate(transcript_words):
        positions.setdefault(word, []).append(index)

    def share(text: str) -> float:
        return _spoken_share(text, transcript_words, positions)

    kept, dropped, unquoted = [], 0, 0
    for line in notes.splitlines():
        stripped = line.strip()
        quote_match = _QUOTE_LINE_RE.match(stripped)
        if quote_match:
            if share(quote_match.group(1)) < _QUOTE_MATCH_SHARE:
                dropped += 1
                continue
        elif stripped.startswith(("- ", "* ")):
            quoted = _QUOTED_TEXT_RE.findall(stripped)
            if any(share(text) < _PARAPHRASE_SHARE for text in quoted):
                dropped += 1
                continue
            for text in quoted:
                if share(text) < _QUOTE_MATCH_SHARE:
                    line = re.sub(r"[\"“”]" + re.escape(text) + r"[\"“”]", text, line)
                    unquoted += 1
        kept.append(line)
    if dropped or unquoted:
        logger.warning(
            "quotes: dropped %s not found in the transcript, unquoted %s paraphrased", dropped, unquoted
        )
    return "\n".join(kept)
