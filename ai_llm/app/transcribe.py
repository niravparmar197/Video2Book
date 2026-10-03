"""Whisper transcription: audio -> VTT (root AGENTS.md "Transcript" row —
YouTube captions first, then Whisper on audio only).

Produces a plain WEBVTT file at the same path/format app.youtube's
caption-fetch path already writes, so app.nodes.chunk (which only ever
reads a VTT text file, never distinguishes its source) and everything
downstream needs zero changes to consume a Whisper-produced transcript.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

_MODEL_SIZE = "base"

_model: Any = None


def _default_model_factory() -> Any:
    """Lazily loads a single shared faster-whisper model (loading model
    weights is expensive -- do it once per process, not once per video).
    CPU + int8 by default (root AGENTS.md stack table: GPU is a "for long
    videos" optimization, not a hard requirement)."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(_MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def _format_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}"


def transcribe_audio_to_vtt(
    audio_path: str | Path,
    output_vtt_path: str | Path,
    model_factory: Callable[[], Any] = _default_model_factory,
) -> Path:
    """Transcribes `audio_path` and writes a WEBVTT file to
    `output_vtt_path`. Returns the written path.

    `model_factory` is injectable so unit tests never load a real model
    (root AGENTS.md testing rule: never call a real paid/heavy external
    dependency from a unit test) -- a fake returning canned segments
    exercises the VTT-formatting logic without the real ~150MB model
    download/load faster-whisper's default factory would trigger.
    """
    model = model_factory()
    segments, _info = model.transcribe(str(audio_path))

    lines = ["WEBVTT", ""]
    for segment in segments:
        lines.append(f"{_format_timestamp(segment.start)} --> {_format_timestamp(segment.end)}")
        lines.append(segment.text.strip())
        lines.append("")

    output_vtt_path = Path(output_vtt_path)
    output_vtt_path.parent.mkdir(parents=True, exist_ok=True)
    output_vtt_path.write_text("\n".join(lines), encoding="utf-8")
    return output_vtt_path
