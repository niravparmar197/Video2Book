"""Unit tests for app.nodes.frames — stream-mode scene detection + dedupe.

No real ffmpeg or network calls: the subprocess runner is always injected.
"""
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFilter

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


def test_dedupe_frames_drops_blurry_frames(tmp_path):
    """A scene-cut frame ffmpeg grabs mid-transition is often still visibly
    blurred -- simulated here with a real Gaussian blur over sharp content
    (not just a solid fill, which the blank check would already catch), so
    this must be the blur check specifically, not the blank one.
    """
    p1 = tmp_path / "scene_0001.jpg"
    p2 = tmp_path / "scene_0002.jpg"  # same content, heavily blurred

    sharp = Image.new("RGB", (64, 64), color=(200, 50, 50))
    ImageDraw.Draw(sharp).rectangle((0, 0, 20, 20), fill=(255, 0, 0))
    sharp.save(p1)
    sharp.filter(ImageFilter.GaussianBlur(radius=3)).save(p2)

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


def test_detect_scenes_downloaded_downloads_once_for_concurrent_chunks(tmp_path):
    """VIDEO_MODE=download: chunks of one video run on a thread pool, but
    the video must only be downloaded once, then each chunk scans the same
    local copy for its own time range."""
    from concurrent.futures import ThreadPoolExecutor

    downloads = []

    def fake_download(url, path):
        downloads.append(url)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"fake-mp4")
        return Path(path)

    scanned_inputs = []

    def fake_runner(args, **kwargs):
        scanned_inputs.append((args[args.index("-i") + 1], args[args.index("-ss") + 1]))
        return _FakeCompletedProcess(returncode=0, stderr="")

    def scan(start):
        return frames_node.detect_scenes_downloaded(
            "vidX", "https://youtube.com/watch?v=vidX", start, start + 60,
            tmp_path, tmp_path / f"scenes_{int(start)}",
            download_video=fake_download, runner=fake_runner,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(scan, [0.0, 60.0, 120.0, 180.0]))

    assert downloads == ["https://youtube.com/watch?v=vidX"]
    local = str(frames_node.local_video_path("vidX", tmp_path))
    assert sorted(scanned_inputs) == [(local, "0.0"), (local, "120.0"), (local, "180.0"), (local, "60.0")]


def test_detect_scenes_downloaded_falls_back_to_stream_when_download_fails(tmp_path, monkeypatch):
    def failing_download(url, path):
        raise RuntimeError("network down")

    stream_calls = []

    def fake_stream(url, start, end, scene_dir, **kw):
        stream_calls.append((url, start, end))
        return [{"path": Path("x.jpg"), "timestamp_seconds": start}]

    monkeypatch.setattr(frames_node, "detect_scenes_with_fallback", fake_stream)

    result = frames_node.detect_scenes_downloaded(
        "vidY", "https://youtube.com/watch?v=vidY", 0.0, 60.0,
        tmp_path, tmp_path / "scenes", download_video=failing_download,
    )

    assert stream_calls == [("https://youtube.com/watch?v=vidY", 0.0, 60.0)]
    assert result[0]["timestamp_seconds"] == 0.0


def test_run_frames_uses_download_mode_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_MODE", "download")
    chunk = {"chunk_index": 0, "start_seconds": 0.0, "end_seconds": 60.0}
    calls = []

    def fake_downloaded(video_id, video_url, start, end, output_dir, scene_dir, **kw):
        calls.append(video_id)
        Path(scene_dir).mkdir(parents=True, exist_ok=True)
        p = Path(scene_dir) / "scene_0001.jpg"
        _make_image(p, fill=(10, 20, 30), shape=(1, 1, 10, 10))
        return [{"path": p, "timestamp_seconds": 5.0}]

    def must_not_stream(*a, **kw):
        raise AssertionError("stream mode must not run when VIDEO_MODE=download")

    monkeypatch.setattr(frames_node, "detect_scenes_downloaded", fake_downloaded)
    monkeypatch.setattr(frames_node, "detect_scenes_with_fallback", must_not_stream)

    frames_node.run_frames("vid1", "https://youtube.com/watch?v=vid1", chunk, tmp_path)

    assert calls == ["vid1"]


@pytest.mark.parametrize(
    "video_mode, duration_seconds, expected",
    [
        ("stream", 300, True),  # a 5-minute video: a temporary download is small and ~8x faster
        ("stream", 13 * 3600, True),  # a 13-hour video downloads too (~0.7GB at 480p)
        ("stream", 15 * 3600, True),  # right at the 900-minute limit
        ("stream", 15 * 3600 + 1, False),  # beyond it keeps streaming (no multi-GB downloads)
        ("stream", None, False),  # unknown duration -> stream
        ("download", 30 * 3600, True),  # explicit download mode always downloads
    ],
)
def test_should_download_short_videos_even_in_stream_mode(
    monkeypatch, video_mode, duration_seconds, expected
):
    monkeypatch.setenv("VIDEO_MODE", video_mode)
    monkeypatch.delenv("FRAMES_DOWNLOAD_MAX_MINUTES", raising=False)

    assert frames_node._should_download(duration_seconds) is expected


def test_should_download_can_be_disabled_with_zero_minutes(monkeypatch):
    monkeypatch.setenv("VIDEO_MODE", "stream")
    monkeypatch.setenv("FRAMES_DOWNLOAD_MAX_MINUTES", "0")

    assert frames_node._should_download(60) is False


def test_should_download_streams_instead_when_the_disk_is_too_small(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_MODE", "stream")
    monkeypatch.delenv("FRAMES_DOWNLOAD_MAX_MINUTES", raising=False)
    fake_usage = type("Usage", (), {"free": 5e9})  # 5GB free
    monkeypatch.setattr(frames_node.shutil, "disk_usage", lambda path: fake_usage)

    # 13h needs ~11.7GB free (0.3GB/h x 3); 1h needs max(1, 0.9) = 1GB.
    assert frames_node._should_download(13 * 3600, tmp_path / "book") is False
    assert frames_node._should_download(3600, tmp_path / "book") is True


def test_limit_frames_keeps_an_even_spread_including_first_and_last():
    frames = [{"path": f"f{i}", "timestamp_seconds": i} for i in range(153)]

    kept = frames_node.limit_frames(frames, 12)

    assert len(kept) == 12
    assert kept[0] == frames[0] and kept[-1] == frames[-1]
    stamps = [frame["timestamp_seconds"] for frame in kept]
    assert stamps == sorted(set(stamps))  # in order, no repeats
    assert max(b - a for a, b in zip(stamps, stamps[1:])) <= 15  # spread across the chunk


def test_limit_frames_leaves_short_lists_and_zero_limit_alone():
    frames = [{"path": f"f{i}", "timestamp_seconds": i} for i in range(5)]

    assert frames_node.limit_frames(frames, 12) == frames
    assert frames_node.limit_frames(frames * 40, 0) == frames * 40
    assert frames_node.limit_frames(frames, 1) == [frames[0]]


def test_loading_screenshots_applies_the_per_chunk_cap_to_already_saved_frames(tmp_path, monkeypatch):
    # A book whose frames were saved before the cap existed (153 in one chunk)
    # must still render with the cap when it is retried/resumed.
    monkeypatch.setenv("MAX_SCREENSHOTS_PER_CHUNK", "12")
    frames_dir = tmp_path / "work" / "frames"
    frames_dir.mkdir(parents=True)
    saved = [{"asset_path": f"a{i}.jpg", "timestamp_seconds": i} for i in range(153)]
    (frames_dir / "vid1_000.json").write_text(
        json.dumps({"video_id": "vid1", "chunk_index": 0, "frames": saved}), encoding="utf-8"
    )

    by_video = frames_node.load_video_screenshots("vid1", tmp_path)
    by_source = frames_node.load_screenshots_for_sources(
        [{"video_id": "vid1", "chunk_index": 0}], tmp_path
    )

    assert len(by_video) == len(by_source) == 12


def test_detect_scenes_decodes_keyframes_only(tmp_path):
    captured = {}

    def fake_runner(args, **kwargs):
        captured["args"] = args
        return _FakeCompletedProcess(0, stderr="")

    frames_node.detect_scenes("https://stream", 0, 60, tmp_path, runner=fake_runner)

    args = captured["args"]
    assert args[args.index("-skip_frame") + 1] == "nokey"
    assert args.index("-skip_frame") < args.index("-i")  # an input option, before -i


def test_every_chunk_grabs_its_final_moment_and_sparse_chunks_are_sampled():
    chunk = {"start_seconds": 0.0, "end_seconds": 600.0}

    many_scenes = frames_node._extra_frame_times(chunk, scene_frame_count=10)
    whiteboard = frames_node._extra_frame_times(chunk, scene_frame_count=0)

    assert many_scenes == [597.0]  # just the finished state
    assert whiteboard == [75.0, 225.0, 375.0, 525.0, 597.0]


def test_grab_frames_writes_one_jpeg_per_timestamp(tmp_path):
    calls = []

    def fake_runner(args, **kwargs):
        calls.append(args)
        Path(args[-1]).write_bytes(b"jpg")
        return _FakeCompletedProcess(0)

    frames = frames_node.grab_frames("video.mp4", [12.5, 597.0], tmp_path, runner=fake_runner)

    assert [frame["timestamp_seconds"] for frame in frames] == [12.5, 597.0]
    assert calls[0][calls[0].index("-ss") + 1] == "12.5"
    assert all(Path(frame["path"]).exists() for frame in frames)


def test_a_whiteboard_chunk_with_no_scene_changes_still_gets_screenshots(tmp_path, monkeypatch):
    # Real case: a 44-minute whiteboard system-design video gave 0 screenshots,
    # so its finished architecture drawing never reached the book.
    monkeypatch.setenv("VIDEO_MODE", "stream")
    monkeypatch.setattr(frames_node, "detect_scenes_with_fallback", lambda *a, **k: [])
    monkeypatch.setattr(frames_node, "_get_stream_url", lambda url: "https://stream")
    colors = iter([(250, 250, 250), (30, 30, 30), (200, 40, 40), (40, 200, 40), (40, 40, 200)])

    def fake_grab(source, timestamps, out_dir, runner=None):
        frames = []
        for t in timestamps:
            path = Path(out_dir) / f"g{int(t)}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            _make_image(path, next(colors), shape=(int(t) % 50, 5, int(t) % 50 + 10, 30))
            frames.append({"path": path, "timestamp_seconds": t})
        return frames

    monkeypatch.setattr(frames_node, "grab_frames", fake_grab)
    monkeypatch.setattr(frames_node, "dedupe_frames", lambda frames, **kw: frames)

    chunk = {"chunk_index": 0, "start_seconds": 0.0, "end_seconds": 600.0}
    out = frames_node.run_frames("wb1", "https://youtube.com/watch?v=wb1", chunk, tmp_path)

    saved = json.loads(out.read_text(encoding="utf-8"))["frames"]
    assert [round(frame["timestamp_seconds"]) for frame in saved] == [75, 225, 375, 525, 597]


def _slide(path, webcam_fill=None):
    """A 'slide' with a few shapes; optionally a webcam box in the bottom-right."""
    image = Image.new("RGB", (160, 90), color=(240, 240, 240))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 70, 40), fill=(20, 20, 160))
    draw.ellipse((80, 5, 130, 45), fill=(160, 20, 20))
    if webcam_fill is not None:
        draw.rectangle((120, 60, 160, 90), fill=webcam_fill)
    image.save(path)
    return path


def test_masked_phash_ignores_the_webcam_corner(tmp_path):
    first = _slide(tmp_path / "a.png", webcam_fill=(0, 0, 0))
    second = _slide(tmp_path / "b.png", webcam_fill=(255, 255, 0))
    with Image.open(first) as a, Image.open(second) as b:
        assert frames_node.masked_phash(a) - frames_node.masked_phash(b) == 0


def test_dedupe_book_screenshots_keeps_the_later_of_near_duplicates_across_chapters(tmp_path):
    video_dir = tmp_path / "vid1"
    video_dir.mkdir()
    early = _slide(video_dir / "000_00.png")
    late = _slide(video_dir / "001_00.png", webcam_fill=(0, 200, 0))
    other = video_dir / "001_01.png"
    _make_image(other, (0, 0, 0), shape=(5, 5, 40, 60))
    chapters = [
        {"screenshots": [{"asset_path": str(early), "timestamp_seconds": 100.0}]},
        {
            "screenshots": [
                {"asset_path": str(late), "timestamp_seconds": 2000.0},
                {"asset_path": str(other), "timestamp_seconds": 2100.0},
            ]
        },
    ]

    frames_node.dedupe_book_screenshots(chapters)

    assert chapters[0]["screenshots"] == []
    assert [shot["asset_path"] for shot in chapters[1]["screenshots"]] == [str(late), str(other)]


def test_dedupe_book_screenshots_never_merges_different_videos(tmp_path):
    shots = []
    for video_id in ("vidA", "vidB"):
        (tmp_path / video_id).mkdir()
        path = _slide(tmp_path / video_id / "000_00.png")
        shots.append({"asset_path": str(path), "timestamp_seconds": 10.0})
    chapters = [{"screenshots": shots}]

    frames_node.dedupe_book_screenshots(chapters)

    assert len(chapters[0]["screenshots"]) == 2


def test_dedupe_book_screenshots_drops_a_precap_shown_again_much_later(tmp_path):
    video_dir = tmp_path / "vid1"
    video_dir.mkdir()
    precap = _slide(video_dir / "000_00.png")
    other = video_dir / "000_01.png"
    _make_image(other, (0, 0, 0), shape=(5, 5, 40, 60))
    final = _slide(video_dir / "001_00.png", webcam_fill=(0, 0, 200))
    chapters = [
        {"screenshots": [
            {"asset_path": str(precap), "timestamp_seconds": 5.0},
            {"asset_path": str(other), "timestamp_seconds": 600.0},
        ]},
        {"screenshots": [{"asset_path": str(final), "timestamp_seconds": 1900.0}]},
    ]

    frames_node.dedupe_book_screenshots(chapters)

    assert [shot["asset_path"] for shot in chapters[0]["screenshots"]] == [str(other)]
    assert len(chapters[1]["screenshots"]) == 1


def _verdict(**overrides):
    verdict = {"overlay": False, "person_only": False, "readable_content": True, "caption": "Upload flow diagram."}
    verdict.update(overrides)
    return json.dumps(verdict)


def test_review_frames_drops_person_only_frames_and_captions_the_rest(tmp_path, monkeypatch):
    slide = _slide(tmp_path / "slide.png")
    person = tmp_path / "person.png"
    _make_image(person, (90, 60, 40))
    replies = {"slide.png": _verdict(), "person.png": _verdict(person_only=True, readable_content=False)}
    monkeypatch.setattr(frames_node, "review_frame", lambda path: json.loads(replies[Path(path).name]))
    frames = [
        {"path": str(slide), "timestamp_seconds": 10.0},
        {"path": str(person), "timestamp_seconds": 20.0},
    ]

    kept = frames_node.review_frames(frames, regrab=lambda moment: None)

    assert kept == [{"path": str(slide), "timestamp_seconds": 10.0, "caption": "Upload flow diagram"}]


def test_review_frames_replaces_a_frame_with_a_popup_by_a_clean_grab(tmp_path, monkeypatch):
    popup, clean = tmp_path / "popup.png", tmp_path / "clean.png"
    _slide(popup)
    _slide(clean)
    verdicts = {"popup.png": {"overlay": True, "readable_content": True, "caption": "Diagram with a pop-up"},
                "clean.png": {"overlay": False, "readable_content": True, "caption": "Upload flow diagram"}}
    monkeypatch.setattr(frames_node, "review_frame", lambda path: verdicts[Path(path).name])
    asked = []

    def regrab(moment):
        asked.append(moment)
        return {"path": str(clean), "timestamp_seconds": moment}

    kept = frames_node.review_frames([{"path": str(popup), "timestamp_seconds": 100.0}], regrab)

    assert asked == [106.0]  # the first clean grab wins
    assert kept == [{"path": str(clean), "timestamp_seconds": 106.0, "caption": "Upload flow diagram"}]


def test_review_frames_keeps_frames_it_cannot_review(tmp_path):
    slide = _slide(tmp_path / "slide.png")
    frames = [{"path": str(slide), "timestamp_seconds": 5.0}]

    # conftest makes call_vision raise, as when the model is down.
    assert frames_node.review_frames(frames, regrab=lambda moment: None) == frames


def test_review_frame_reads_json_wrapped_in_other_text(tmp_path, monkeypatch):
    slide = _slide(tmp_path / "slide.png")
    monkeypatch.setattr(
        frames_node, "call_vision", lambda prompt, image_bytes, **kw: "Sure:\n" + _verdict(overlay=True) + "\n"
    )

    assert frames_node.review_frame(slide)["overlay"] is True
