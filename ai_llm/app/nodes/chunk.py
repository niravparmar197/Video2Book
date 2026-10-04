"""Chunk node: parse WebVTT captions and split into CHUNK_MINUTES segments.

See root AGENTS.md: "Everything runs in 30-minute chunks — one design works
for 10 minutes and 30 hours."
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.config import load_settings

_TIMESTAMP_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})"
)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Cue:
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    start_seconds: float
    end_seconds: float
    text: str


def _timestamp_to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_vtt(vtt_text: str) -> list[Cue]:
    """Parse a WebVTT captions file into an ordered list of cues, one per
    caption *line*, with a line that repeats the line just before it dropped.

    YouTube's auto-captions are "rolling": every cue repeats the previous
    line above the new one ("matter well since you ask" / "matter well since
    you ask" + "I'd say no or ..."). Comparing whole cues let those repeats
    through, so every auto-captioned transcript reached the LLM with each
    phrase three times -- ~3x the tokens on every call (slower, and it
    confused both the writer and the judge). Compared line by line, each
    phrase appears once. A line holding only a space is part of a cue (not
    its end), so it no longer hides the text line after it.
    """
    cues: list[Cue] = []
    lines = vtt_text.splitlines()
    previous_text = None
    i = 0
    while i < len(lines):
        match = _TIMESTAMP_RE.search(lines[i])
        if match:
            groups = match.groups()
            start = _timestamp_to_seconds(*groups[0:4])
            end = _timestamp_to_seconds(*groups[4:8])
            i += 1
            while i < len(lines) and lines[i] != "" and not _TIMESTAMP_RE.search(lines[i]):
                text = _TAG_RE.sub("", lines[i]).strip()
                if text and text != previous_text:
                    cues.append(Cue(start_seconds=start, end_seconds=end, text=text))
                    previous_text = text
                i += 1
        else:
            i += 1
    return cues


# A final chunk shorter than this share of CHUNK_MINUTES is merged into the one before.
_TAIL_MERGE_FRACTION = 0.2


def chunk_cues(cues: list[Cue], chunk_minutes: int) -> list[Chunk]:
    """Group cues into fixed-size time buckets, deduping repeated caption lines."""
    if not cues:
        return []

    chunk_seconds = chunk_minutes * 60
    buckets: dict[int, list[Cue]] = {}
    for cue in cues:
        index = int(cue.start_seconds // chunk_seconds)
        buckets.setdefault(index, []).append(cue)

    # A short tail (a 30-minute video that runs 30:40) is folded into the
    # previous chunk: as its own chunk it cost an extra topics call, forced
    # the slower multi-chunk planning path and became a junk "goodbye" chapter.
    indexes = sorted(buckets)
    if len(indexes) > 1:
        last = indexes[-1]
        tail_seconds = buckets[last][-1].end_seconds - last * chunk_seconds
        if tail_seconds < chunk_seconds * _TAIL_MERGE_FRACTION:
            buckets[indexes[-2]].extend(buckets.pop(indexes[-1]))
            indexes.pop()

    chunks: list[Chunk] = []
    for index in indexes:
        bucket = buckets[index]
        texts: list[str] = []
        for cue in bucket:
            if not texts or texts[-1] != cue.text:
                texts.append(cue.text)
        chunks.append(
            Chunk(
                chunk_index=index,
                start_seconds=bucket[0].start_seconds,
                end_seconds=bucket[-1].end_seconds,
                text=" ".join(texts),
            )
        )
    return chunks


def run_chunk(
    video_id: str,
    captions_path: str | Path,
    output_dir: str | Path,
    chunk_minutes: int | None = None,
) -> list[Path]:
    """Parse a VTT captions file and write one JSON chunk file per segment."""
    if chunk_minutes is None:
        chunk_minutes = load_settings().chunk_minutes

    vtt_text = Path(captions_path).read_text(encoding="utf-8")
    chunks = chunk_cues(parse_vtt(vtt_text), chunk_minutes)

    chunks_dir = Path(output_dir) / "work" / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    written_paths: list[Path] = []
    for chunk in chunks:
        chunk_path = chunks_dir / f"{video_id}_{chunk.chunk_index:03d}.json"
        chunk_path.write_text(
            json.dumps(
                {
                    "video_id": video_id,
                    "chunk_index": chunk.chunk_index,
                    "start_seconds": chunk.start_seconds,
                    "end_seconds": chunk.end_seconds,
                    "text": chunk.text,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        written_paths.append(chunk_path)

    return written_paths
