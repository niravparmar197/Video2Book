"""Unit tests for app.transcribe — Whisper audio -> VTT.

No real model load: model_factory is replaced with a fake returning canned
segment objects, per root AGENTS.md's "never call a real paid/heavy
external dependency from a unit test" rule.
"""
from pathlib import Path
from types import SimpleNamespace

from app import transcribe as transcribe_module
from app.transcribe import transcribe_audio_to_vtt


class FakeSegment(SimpleNamespace):
    start: float
    end: float
    text: str


class FakeModel:
    def __init__(self, segments, language="en"):
        self._segments = segments
        self._language = language
        self.calls = []

    def transcribe(self, audio_path, **kwargs):
        self.calls.append(kwargs)
        return iter(self._segments), SimpleNamespace(language=self._language)


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


def test_select_device_uses_cuda_when_a_gpu_is_present(monkeypatch):
    monkeypatch.setattr(transcribe_module.ctranslate2, "get_cuda_device_count", lambda: 1)
    assert transcribe_module._select_device() == ("cuda", "float16")


def test_select_device_falls_back_to_cpu_when_no_gpu_is_present(monkeypatch):
    monkeypatch.setattr(transcribe_module.ctranslate2, "get_cuda_device_count", lambda: 0)
    assert transcribe_module._select_device() == ("cpu", "int8")


def test_non_english_audio_is_translated_straight_to_english(tmp_path):
    """Measured live on a Hindi lecture: task="translate" was 2-5x faster
    and the only setting that kept every topic -- the book is English
    anyway."""
    model = FakeModel([FakeSegment(start=0.0, end=1.0, text="Atomicity means all or none.")], language="hi")
    out = transcribe_audio_to_vtt(tmp_path / "a.m4a", tmp_path / "v.vtt", model_factory=lambda: model)

    assert [c["task"] for c in model.calls] == ["transcribe", "translate"]
    assert "Atomicity means all or none." in out.read_text(encoding="utf-8")


def test_english_audio_is_transcribed_not_translated(tmp_path):
    model = FakeModel([FakeSegment(start=0.0, end=1.0, text="Hello.")], language="en")
    transcribe_audio_to_vtt(tmp_path / "a.m4a", tmp_path / "v.vtt", model_factory=lambda: model)

    assert [c["task"] for c in model.calls] == ["transcribe"]


def test_transcription_uses_anti_hallucination_settings(tmp_path):
    """vad_filter + condition_on_previous_text=False: without them the base
    model produced long garbage repeat loops on a real lecture."""
    model = FakeModel([], language="hi")
    transcribe_audio_to_vtt(tmp_path / "a.m4a", tmp_path / "v.vtt", model_factory=lambda: model)

    for call in model.calls:
        assert call["vad_filter"] is True
        assert call["condition_on_previous_text"] is False


def test_whisper_decodes_greedily_for_speed(tmp_path):
    # Beam 1 measured 1.4x faster than the default beam 5 with 93% of words
    # identical on a real lecture.
    model = FakeModel([], language="hi")

    transcribe_audio_to_vtt(
        tmp_path / "audio.m4a", tmp_path / "out.vtt", model_factory=lambda: model
    )

    assert all(call["beam_size"] == 1 and call["best_of"] == 1 for call in model.calls)
