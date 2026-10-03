"""Unit tests for app.transcribe — Whisper audio -> VTT.

No real model load: model_factory is replaced with a fake returning canned
segment objects, per root AGENTS.md's "never call a real paid/heavy
external dependency from a unit test" rule.
"""
from pathlib import Path
from types import SimpleNamespace

from app.transcribe import transcribe_audio_to_vtt


class FakeSegment(SimpleNamespace):
    start: float
    end: float
    text: str


class FakeModel:
    def __init__(self, segments):
        self._segments = segments

    def transcribe(self, audio_path):
        return iter(self._segments), {"language": "en"}


def _fake_model_factory(segments):
    model = FakeModel(segments)
    return lambda: model


def test_transcribe_audio_to_vtt_writes_valid_webvtt(tmp_path):
    audio_path = tmp_path / "audio.m4a"
    audio_path.write_bytes(b"fake audio bytes")
    output_path = tmp_path / "captions" / "video1.en.vtt"

    segments = [
        FakeSegment(start=0.0, end=2.5, text=" Hello and welcome. "),
        FakeSegment(start=2.5, end=5.0, text="This is a test."),
    ]

    result = transcribe_audio_to_vtt(
        audio_path, output_path, model_factory=_fake_model_factory(segments)
    )

    assert result == output_path
    text = output_path.read_text(encoding="utf-8")
    assert text.startswith("WEBVTT\n\n")
    assert "00:00:00.000 --> 00:00:02.500" in text
    assert "Hello and welcome." in text
    assert "00:00:02.500 --> 00:00:05.000" in text
    assert "This is a test." in text


def test_transcribe_audio_to_vtt_creates_parent_dirs(tmp_path):
    audio_path = tmp_path / "audio.m4a"
    audio_path.write_bytes(b"fake audio bytes")
    output_path = tmp_path / "nested" / "dirs" / "video1.en.vtt"

    segments = [FakeSegment(start=0.0, end=1.0, text="Hi.")]
    transcribe_audio_to_vtt(audio_path, output_path, model_factory=_fake_model_factory(segments))

    assert output_path.exists()


def test_transcribe_audio_to_vtt_handles_zero_segments(tmp_path):
    audio_path = tmp_path / "audio.m4a"
    audio_path.write_bytes(b"fake audio bytes")
    output_path = tmp_path / "video1.en.vtt"

    transcribe_audio_to_vtt(audio_path, output_path, model_factory=_fake_model_factory([]))

    assert output_path.read_text(encoding="utf-8") == "WEBVTT\n"


def test_transcribe_audio_to_vtt_formats_hour_plus_timestamps(tmp_path):
    audio_path = tmp_path / "audio.m4a"
    audio_path.write_bytes(b"fake audio bytes")
    output_path = tmp_path / "video1.en.vtt"

    segments = [FakeSegment(start=3661.25, end=3665.0, text="An hour in.")]
    transcribe_audio_to_vtt(audio_path, output_path, model_factory=_fake_model_factory(segments))

    text = output_path.read_text(encoding="utf-8")
    assert "01:01:01.250 --> 01:01:05.000" in text
