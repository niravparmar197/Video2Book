"""Whisper transcription: audio -> VTT (root AGENTS.md "Transcript" row —
YouTube captions first, then Whisper on audio only).

Produces a plain WEBVTT file at the same path/format app.youtube's
caption-fetch path already writes, so app.nodes.chunk (which only ever
reads a VTT text file, never distinguishes its source) and everything
downstream needs zero changes to consume a Whisper-produced transcript.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

import ctranslate2

_MODEL_SIZE = "base"

# Shared transcript-cache key (app/youtube.py): changes whenever the model
# or decoding settings change, so a transcript produced by an older recipe
# is never served from the cache.
TRANSCRIPT_RECIPE = f"{_MODEL_SIZE}-vad-translate-beam1-v2"

_model: Any = None
_model_lock = threading.Lock()


def _select_device() -> tuple[str, str]:
    """Picks the fastest device faster-whisper can actually use on this
    machine: CUDA (float16) if a GPU is present, int8 CPU otherwise --
    root AGENTS.md stack table: "GPU for long videos" is meant to speed
    this up, not just be a config knob nobody flips. Detected for real via
    ctranslate2 (the engine faster-whisper runs on), not an env var, so
    this adapts automatically to whatever machine actually runs it instead
    of silently staying on CPU on a GPU box someone forgot to configure.
    """
    if ctranslate2.get_cuda_device_count() > 0:
        return "cuda", "float16"
    return "cpu", "int8"


def _default_model_factory() -> Any:
    """Lazily loads a single shared faster-whisper model (loading model
    weights is expensive -- do it once per process, not once per video)."""
    global _model
    with _model_lock:  # two books transcribing at once must not load it twice
        if _model is None:
            from faster_whisper import WhisperModel

            device, compute_type = _select_device()
            _model = WhisperModel(_MODEL_SIZE, device=device, compute_type=compute_type)
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

    Decoding settings, all measured live on a real Hindi lecture:
    - vad_filter skips silence/music (where hallucination loops start) and
      condition_on_previous_text=False stops a loop feeding itself --
      without these, base-model output contained long garbage repeats
      ("p3g3ng ng p3g3ng ng ...") and dropped a whole topic.
    - Non-English audio is translated straight to English (task=
      "translate"): the book is written in English anyway, and on that
      lecture it took 69s vs 148-367s and was the only setting that kept
      all four of the lecture's topics. English audio is transcribed as-is.
    """
    model = model_factory()
    # Greedy decoding (beam 1): measured 1.4x faster than faster-whisper's
    # default beam 5 on 5 minutes of a real lecture (28.5s vs 40.7s on this
    # CPU) with 93% of words identical -- run-to-run noise for the "base" model.
    decode = {
        "vad_filter": True,
        "condition_on_previous_text": False,
        "beam_size": 1,
        "best_of": 1,
    }
    # faster-whisper decodes lazily: this call only detects the language,
    # so re-calling with task="translate" doesn't waste a full decode.
    segments, info = model.transcribe(str(audio_path), task="transcribe", **decode)
    if getattr(info, "language", "en") != "en":
        segments, info = model.transcribe(str(audio_path), task="translate", **decode)

    lines = ["WEBVTT", ""]
    for segment in segments:
        lines.append(f"{_format_timestamp(segment.start)} --> {_format_timestamp(segment.end)}")
        lines.append(segment.text.strip())
        lines.append("")

    output_vtt_path = Path(output_vtt_path)
    output_vtt_path.parent.mkdir(parents=True, exist_ok=True)
    output_vtt_path.write_text("\n".join(lines), encoding="utf-8")
    return output_vtt_path
