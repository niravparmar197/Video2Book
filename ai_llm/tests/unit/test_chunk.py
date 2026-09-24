"""Unit tests for app.nodes.chunk — WebVTT parsing and 30-minute chunking.

No network calls: works purely against in-memory / tmp_path VTT fixtures.
"""
import json
from pathlib import Path

from app.nodes.chunk import Chunk, Cue, chunk_cues, parse_vtt, run_chunk

SAMPLE_VTT = """WEBVTT

00:00:00.000 --> 00:00:02.500
Hello and welcome to this video.

00:00:02.500 --> 00:00:05.000
Today we talk about neural networks.

00:00:05.000 --> 00:00:08.000
They are made of layers of neurons.
"""


def _cue(start_min: float, end_min: float, text: str) -> Cue:
    return Cue(start_seconds=start_min * 60, end_seconds=end_min * 60, text=text)


def test_parse_vtt_returns_cues_in_order():
    cues = parse_vtt(SAMPLE_VTT)

    assert len(cues) == 3
    assert cues[0].text == "Hello and welcome to this video."
    assert cues[0].start_seconds == 0.0
    assert cues[0].end_seconds == 2.5
    assert cues[2].text == "They are made of layers of neurons."


def test_parse_vtt_strips_inline_tags():
    vtt = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "<c>Hello</c> <c>world</c>.\n"
    )
    cues = parse_vtt(vtt)
    assert cues[0].text == "Hello world."


def test_chunk_cues_19_minute_video_is_one_chunk():
    cues = [
        _cue(0, 0.1, "intro"),
        _cue(9, 9.1, "middle"),
        _cue(18.5, 18.7, "outro"),  # 18min40s, matches the real test video length
    ]

    chunks = chunk_cues(cues, chunk_minutes=30)

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert "intro" in chunks[0].text
    assert "outro" in chunks[0].text


def test_chunk_cues_90_minute_transcript_produces_3_chunks():
    cues = [
        _cue(0, 0.1, "chunk zero"),
        _cue(29, 29.1, "still chunk zero"),
        _cue(35, 35.1, "chunk one"),
        _cue(55, 55.1, "still chunk one"),
        _cue(65, 65.1, "chunk two"),
        _cue(89, 89.1, "still chunk two"),
    ]

    chunks = chunk_cues(cues, chunk_minutes=30)

    assert len(chunks) == 3
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert "chunk zero" in chunks[0].text and "still chunk zero" in chunks[0].text
    assert "chunk one" in chunks[1].text
    assert "chunk two" in chunks[2].text


def test_chunk_cues_dedupes_consecutive_repeated_lines():
    cues = [
        _cue(0, 0.1, "same line"),
        _cue(0.1, 0.2, "same line"),
        _cue(0.2, 0.3, "different line"),
    ]

    chunks = chunk_cues(cues, chunk_minutes=30)

    assert chunks[0].text == "same line different line"


def test_chunk_cues_empty_input_returns_no_chunks():
    assert chunk_cues([], chunk_minutes=30) == []


def test_run_chunk_writes_one_json_file_per_chunk(tmp_path):
    captions_path = tmp_path / "aircAruvnKk.en.vtt"
    captions_path.write_text(SAMPLE_VTT, encoding="utf-8")
    output_dir = tmp_path / "output" / "some-book"

    written = run_chunk("aircAruvnKk", captions_path, output_dir, chunk_minutes=30)

    assert len(written) == 1
    chunk_path = written[0]
    assert chunk_path.exists()
    assert chunk_path.parent == output_dir / "work" / "chunks"

    payload = json.loads(chunk_path.read_text(encoding="utf-8"))
    assert payload["video_id"] == "aircAruvnKk"
    assert payload["chunk_index"] == 0
    assert "neural networks" in payload["text"]


def test_run_chunk_90_minute_transcript_produces_3_files(tmp_path):
    lines = ["WEBVTT", ""]
    for minute in (0, 35, 65):
        start = f"{minute // 60:02d}:{minute % 60:02d}:00.000"
        end = f"{minute // 60:02d}:{minute % 60:02d}:01.000"
        lines.append(f"{start} --> {end}")
        lines.append(f"segment at minute {minute}")
        lines.append("")
    captions_path = tmp_path / "longvid.en.vtt"
    captions_path.write_text("\n".join(lines), encoding="utf-8")
    output_dir = tmp_path / "output" / "long-book"

    written = run_chunk("longvid", captions_path, output_dir, chunk_minutes=30)

    assert len(written) == 3
    for path in written:
        assert path.exists()
