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
    """Parse a WebVTT captions file into an ordered list of cues."""
    cues: list[Cue] = []
    lines = vtt_text.splitlines()
    i = 0
    while i < len(lines):
        match = _TIMESTAMP_RE.search(lines[i])
        if match:
            groups = match.groups()
            start = _timestamp_to_seconds(*groups[0:4])
            end = _timestamp_to_seconds(*groups[4:8])
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip():
                text_lines.append(_TAG_RE.sub("", lines[i]).strip())
                i += 1
            text = " ".join(t for t in text_lines if t)
            if text:
                cues.append(Cue(start_seconds=start, end_seconds=end, text=text))
        else:
            i += 1
    return cues


def chunk_cues(cues: list[Cue], chunk_minutes: int) -> list[Chunk]:
    """Group cues into fixed-size time buckets, deduping repeated caption lines."""
    if not cues:
        return []

    chunk_seconds = chunk_minutes * 60
    buckets: dict[int, list[Cue]] = {}
    for cue in cues:
        index = int(cue.start_seconds // chunk_seconds)
        buckets.setdefault(index, []).append(cue)

    chunks: list[Chunk] = []
    for index in sorted(buckets):
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
