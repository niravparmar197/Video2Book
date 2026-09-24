"""Unit tests for app.nodes.frames — stream-mode scene detection + dedupe.

No real ffmpeg or network calls: the subprocess runner is always injected.
"""
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.nodes import frames as frames_node


def _make_image(path, fill, shape=None):
    image = Image.new("RGB", (64, 64), color=fill)
    if shape is not None:
        ImageDraw.Draw(image).rectangle(shape, fill=(255, 0, 0))
    image.save(path)


class _FakeCompletedProcess:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_detect_scenes_writes_frames_in_order(tmp_path):
    def fake_runner(args, **kwargs):
        output_dir = Path(args[-1]).parent
        (output_dir / "scene_0001.jpg").write_bytes(b"fake-jpeg-1")
        (output_dir / "scene_0002.jpg").write_bytes(b"fake-jpeg-2")
        stderr = (
            "[Parsed_showinfo_1 @ 0x1] n:   0 pts:    100 pts_time:2.500\n"
            "[Parsed_showinfo_1 @ 0x1] n:   1 pts:    500 pts_time:12.750\n"
        )
        return _FakeCompletedProcess(returncode=0, stderr=stderr)

    frames = frames_node.detect_scenes(
        "https://example.com/stream.mp4",
        start_seconds=0.0,
        end_seconds=1800.0,
        output_dir=tmp_path,
        runner=fake_runner,
    )

    assert len(frames) == 2
    assert frames[0]["timestamp_seconds"] == pytest.approx(2.5)
    assert frames[1]["timestamp_seconds"] == pytest.approx(12.75)
    assert frames[0]["path"].exists()
    assert frames[0]["path"] < frames[1]["path"]


def test_detect_scenes_offsets_timestamps_by_chunk_start(tmp_path):
    def fake_runner(args, **kwargs):
        output_dir = Path(args[-1]).parent
        (output_dir / "scene_0001.jpg").write_bytes(b"fake")
        return _FakeCompletedProcess(returncode=0, stderr="pts_time:5.000\n")

    frames = frames_node.detect_scenes(
        "https://example.com/stream.mp4",
        start_seconds=1800.0,
        end_seconds=3600.0,
        output_dir=tmp_path,
        runner=fake_runner,
    )

    # A chunk starting at 1800s (30 min in) with a frame at relative 5s
    # should report an absolute timestamp of 1805s.
    assert frames[0]["timestamp_seconds"] == pytest.approx(1805.0)


def test_detect_scenes_invokes_ffmpeg_with_expected_args(tmp_path):
    captured = {}

    def fake_runner(args, **kwargs):
        captured["args"] = args
        return _FakeCompletedProcess(returncode=0, stderr="")

    frames_node.detect_scenes(
        "https://example.com/stream.mp4",
        start_seconds=10.0,
        end_seconds=70.0,
        output_dir=tmp_path,
        runner=fake_runner,
    )

    args = captured["args"]
    assert args[0] == "ffmpeg"
    assert "-ss" in args and "10.0" in args
    assert "-t" in args and "60.0" in args
    assert "https://example.com/stream.mp4" in args
    assert any("select=" in arg for arg in args)


def test_detect_scenes_raises_on_ffmpeg_failure(tmp_path):
    def fake_runner(args, **kwargs):
        return _FakeCompletedProcess(returncode=1, stderr="Error: no such file")

    with pytest.raises(RuntimeError, match="ffmpeg scene detection failed"):
        frames_node.detect_scenes(
            "https://example.com/stream.mp4",
            start_seconds=0.0,
            end_seconds=60.0,
            output_dir=tmp_path,
            runner=fake_runner,
        )


def test_detect_scenes_with_fallback_uses_stream_when_it_succeeds(tmp_path):
    download_calls = []

    def fake_get_stream_url(url):
        return "https://example.com/stream.mp4"

    def fake_download_chunk_video(url, start, end, output_dir):
        download_calls.append((url, start, end))
        raise AssertionError("download fallback must not be called when the stream succeeds")

    def fake_runner(args, **kwargs):
        output_dir = Path(args[-1]).parent
        (output_dir / "scene_0001.jpg").write_bytes(b"fake")
        return _FakeCompletedProcess(returncode=0, stderr="pts_time:1.000\n")

    frames = frames_node.detect_scenes_with_fallback(
        "https://youtube.com/watch?v=x",
        0.0,
        60.0,
        tmp_path,
        get_stream_url=fake_get_stream_url,
        download_chunk_video=fake_download_chunk_video,
        runner=fake_runner,
    )

    assert len(frames) == 1
    assert download_calls == []


def test_detect_scenes_with_fallback_downloads_exact_chunk_range_on_stream_failure(tmp_path):
    def fake_get_stream_url(url):
        return "https://example.com/stream.mp4"

    download_calls = []

    def fake_download_chunk_video(url, start, end, output_dir):
        download_calls.append((url, start, end))
        local_path = Path(output_dir) / "chunk_video.mp4"
        local_path.write_bytes(b"fake-video")
        return local_path

    call_count = {"n": 0}

    def fake_runner(args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _FakeCompletedProcess(returncode=1, stderr="network error")
        output_dir = Path(args[-1]).parent
        (output_dir / "scene_0001.jpg").write_bytes(b"fake")
        return _FakeCompletedProcess(returncode=0, stderr="pts_time:3.000\n")

    frames = frames_node.detect_scenes_with_fallback(
        "https://youtube.com/watch?v=x",
        1800.0,
        3600.0,
        tmp_path,
        get_stream_url=fake_get_stream_url,
        download_chunk_video=fake_download_chunk_video,
        runner=fake_runner,
    )

    assert download_calls == [("https://youtube.com/watch?v=x", 1800.0, 3600.0)]
    assert len(frames) == 1
    # Timestamp is offset by the chunk's original start (1800s) even though
    # the downloaded file's own scan starts at 0 -- absolute, not relative.
    assert frames[0]["timestamp_seconds"] == pytest.approx(1803.0)


def test_detect_scenes_with_fallback_downloads_on_stream_timeout(tmp_path):
    """A stalled connection raises subprocess.TimeoutExpired, not
    RuntimeError -- verified live against a real network stall; the
    fallback must catch this too, not just a non-zero ffmpeg exit.
    """

    def fake_get_stream_url(url):
        return "https://example.com/stream.mp4"

    download_calls = []

    def fake_download_chunk_video(url, start, end, output_dir):
        download_calls.append((url, start, end))
        local_path = Path(output_dir) / "chunk_video.mp4"
        local_path.write_bytes(b"fake-video")
        return local_path

    call_count = {"n": 0}

    def fake_runner(args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise subprocess.TimeoutExpired(cmd=args, timeout=300)
        output_dir = Path(args[-1]).parent
        (output_dir / "scene_0001.jpg").write_bytes(b"fake")
        return _FakeCompletedProcess(returncode=0, stderr="pts_time:2.000\n")

    frames = frames_node.detect_scenes_with_fallback(
        "https://youtube.com/watch?v=x",
        0.0,
        60.0,
        tmp_path,
        get_stream_url=fake_get_stream_url,
        download_chunk_video=fake_download_chunk_video,
        runner=fake_runner,
    )

    assert download_calls == [("https://youtube.com/watch?v=x", 0.0, 60.0)]
    assert len(frames) == 1


def test_dedupe_frames_drops_near_duplicates(tmp_path):
    p1 = tmp_path / "scene_0001.jpg"
    p2 = tmp_path / "scene_0002.jpg"  # near-identical to p1 (1px shifted shape)
    p3 = tmp_path / "scene_0003.jpg"  # genuinely distinct

    _make_image(p1, fill=(200, 200, 200), shape=(10, 10, 30, 30))
    _make_image(p2, fill=(200, 200, 200), shape=(11, 11, 31, 31))
    _make_image(p3, fill=(20, 20, 200), shape=(40, 5, 60, 25))

    frames = [
        {"path": p1, "timestamp_seconds": 1.0},
        {"path": p2, "timestamp_seconds": 2.0},
        {"path": p3, "timestamp_seconds": 3.0},
    ]

    kept = frames_node.dedupe_frames(frames)
    kept_timestamps = [f["timestamp_seconds"] for f in kept]

    assert 1.0 in kept_timestamps
    assert 2.0 not in kept_timestamps  # near-duplicate of frame 1, dropped
    assert 3.0 in kept_timestamps  # distinct enough, kept


def test_dedupe_frames_drops_blank_frames(tmp_path):
    p1 = tmp_path / "scene_0001.jpg"
    p2 = tmp_path / "scene_0002.jpg"  # solid color, no content

    _make_image(p1, fill=(50, 100, 150), shape=(5, 5, 55, 55))
    _make_image(p2, fill=(255, 255, 255))

    frames = [
        {"path": p1, "timestamp_seconds": 1.0},
        {"path": p2, "timestamp_seconds": 2.0},
    ]

    kept = frames_node.dedupe_frames(frames)

    assert len(kept) == 1
    assert kept[0]["timestamp_seconds"] == 1.0


def test_dedupe_frames_keeps_all_when_all_distinct(tmp_path):
    p1 = tmp_path / "scene_0001.jpg"
    p2 = tmp_path / "scene_0002.jpg"

    _make_image(p1, fill=(200, 50, 50), shape=(0, 0, 20, 20))
    _make_image(p2, fill=(50, 200, 50), shape=(40, 40, 64, 64))

    frames = [
        {"path": p1, "timestamp_seconds": 1.0},
        {"path": p2, "timestamp_seconds": 2.0},
    ]

    kept = frames_node.dedupe_frames(frames)

    assert len(kept) == 2


def test_run_frames_writes_metadata_and_saved_assets(tmp_path, monkeypatch):
    chunk = {"chunk_index": 0, "start_seconds": 0.0, "end_seconds": 60.0}

    def fake_detect_scenes_with_fallback(video_url, start, end, output_dir, **kw):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        p = output_dir / "scene_0001.jpg"
        _make_image(p, fill=(10, 20, 30), shape=(1, 1, 10, 10))
        return [{"path": p, "timestamp_seconds": 5.0}]

    monkeypatch.setattr(
        frames_node, "detect_scenes_with_fallback", fake_detect_scenes_with_fallback
    )

    output_path = frames_node.run_frames(
        "vid1", "https://youtube.com/watch?v=vid1", chunk, tmp_path
    )

    assert output_path == tmp_path / "work" / "frames" / "vid1_000.json"
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["video_id"] == "vid1"
    assert payload["chunk_index"] == 0
    assert len(payload["frames"]) == 1
    assert payload["frames"][0]["timestamp_seconds"] == 5.0

    asset_path = Path(payload["frames"][0]["asset_path"])
    assert asset_path.exists()
    assert asset_path.parent == tmp_path / "assets" / "vid1"


def test_run_frames_is_cache_skippable(tmp_path, monkeypatch):
    chunk = {"chunk_index": 0, "start_seconds": 0.0, "end_seconds": 60.0}
    calls = {"n": 0}

    def fake_detect_scenes_with_fallback(video_url, start, end, output_dir, **kw):
        calls["n"] += 1
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        p = output_dir / "scene_0001.jpg"
        _make_image(p, fill=(10, 20, 30), shape=(1, 1, 10, 10))
        return [{"path": p, "timestamp_seconds": 5.0}]

    monkeypatch.setattr(
        frames_node, "detect_scenes_with_fallback", fake_detect_scenes_with_fallback
    )

    frames_node.run_frames("vid1", "https://youtube.com/watch?v=vid1", chunk, tmp_path)
    frames_node.run_frames("vid1", "https://youtube.com/watch?v=vid1", chunk, tmp_path)

    assert calls["n"] == 1
