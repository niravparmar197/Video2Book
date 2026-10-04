"""Align a chapter's sections with the moment in the video they come from.

The notes are written per topic, not per timestamp, so each `##` section's
words are matched against the timed captions of the chapter's source chunks:
the ~45-second window that shares the most (rare) words with the section is
where it is "spoken". That time is used to put each screenshot next to the
section it belongs to (instead of spreading screenshots evenly, which put
some beside unrelated text) and to link the section to that moment on
YouTube. No LLM call. A section with too little overlap -- e.g. English
notes from a Hindi caption track -- gets no time, and the renderer falls
back to the even spread.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from app.nodes.chunk import Cue, parse_vtt

_WINDOW_SECONDS = 45.0
_MIN_MATCHED_WORDS = 3
_WORD_RE = re.compile(r"[a-z]{4,}")
_STOPWORDS = frozenset(
    "that this with from have they will would there their what when which about into "
    "your just like then than them were been more some also only very much make made "
    "does dont each other these those because where while could should here over such "
    "point example notes section video speaker".split()
)

# Overview / summary sections cover the whole video, not one moment.
_SUMMARY_HEADING_RE = re.compile(
    r"^##\s+(?:episode at a glance|the show at a glance|key takeaways|best moments|"
    r"mentioned in this episode|test yourself|complete architecture)\b",
    re.IGNORECASE,
)

# (video_id, seconds) or None per `##` section, in order.
SectionTime = tuple[str, float] | None


def _words(text: str) -> set[str]:
    return {word for word in _WORD_RE.findall(text.lower()) if word not in _STOPWORDS}


def _sections(notes: str) -> list[str]:
    """The text of each `## ` section, in order (what the renderer turns into
    LaTeX sections; text before the first heading belongs to none)."""
    sections: list[str] = []
    for line in notes.splitlines():
        if line.strip().startswith("## "):
            sections.append(line)
        elif sections:
            sections[-1] += "\n" + line
    return sections


def _windows(timed_cues: list[tuple[str, Cue]]) -> list[tuple[str, float, set[str]]]:
    """Group consecutive cues of one video into ~45s windows: (video_id, start, words)."""
    windows: list[tuple[str, float, set[str]]] = []
    for video_id, cue in timed_cues:
        if (
            windows
            and windows[-1][0] == video_id
            and cue.start_seconds - windows[-1][1] < _WINDOW_SECONDS
        ):
            windows[-1][2].update(_words(cue.text))
        else:
            windows.append((video_id, cue.start_seconds, _words(cue.text)))
    return windows


def section_times(notes: str, timed_cues: list[tuple[str, Cue]]) -> list[SectionTime]:
    """Where in the video each `##` section of `notes` is spoken."""
    windows = _windows(timed_cues)
    if not windows:
        return [None for _ in _sections(notes)]

    # Rare words identify a moment; words said in every window do not.
    document_frequency = Counter(word for _, _, words in windows for word in words)
    total = len(windows)

    def weight(word: str) -> float:
        return math.log((total + 1) / (document_frequency[word] + 0.5))

    times: list[SectionTime] = []
    for section in _sections(notes):
        if _SUMMARY_HEADING_RE.match(section):
            times.append(None)  # sums up the whole video; no single moment
            continue
        section_words = _words(section)
        best, best_score = None, 0.0
        for video_id, start, words in windows:
            matched = section_words & words
            if len(matched) < _MIN_MATCHED_WORDS:
                continue
            score = sum(weight(word) for word in matched)
            if score > best_score:
                best, best_score = (video_id, start), score
        times.append(best)
    return times


def timed_cues_for_sources(sources: list[dict], output_dir: str | Path) -> list[tuple[str, Cue]]:
    """The timed caption cues of a chapter's source chunks, in source order."""
    output_dir = Path(output_dir)
    cues: list[tuple[str, Cue]] = []
    parsed: dict[str, list[Cue]] = {}
    for source in sources:
        video_id = source["video_id"]
        chunk_path = output_dir / "work" / "chunks" / f"{video_id}_{source['chunk_index']:03d}.json"
        if not chunk_path.exists():
            continue
        chunk = json.loads(chunk_path.read_text(encoding="utf-8"))
        if video_id not in parsed:
            captions = sorted((output_dir / "work" / "captions").glob(f"{video_id}.*vtt"))
            parsed[video_id] = parse_vtt(captions[0].read_text(encoding="utf-8")) if captions else []
        start, end = chunk.get("start_seconds", 0.0), chunk.get("end_seconds", math.inf)
        cues.extend(
            (video_id, cue) for cue in parsed[video_id] if start <= cue.start_seconds <= end
        )
    return cues


def chapter_section_times(
    notes: str, sources: list[dict], output_dir: str | Path
) -> list[SectionTime]:
    return section_times(notes, timed_cues_for_sources(sources, output_dir))
