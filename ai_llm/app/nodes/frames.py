"""Frames node: scene detection + screenshots (VIDEO_MODE=stream or download).

VIDEO_MODE=download downloads each video once (480p, video-only), scans its
chunks locally, and deletes the copy afterward -- ~8x faster than stream
mode on a real video, since ffmpeg's direct stream read gets throttled.

One screenshot per scene change, never on a timer (root AGENTS.md: "A timer
gives ~720 near-duplicate images/hour"). ffmpeg scans a chunk's time range
directly against a yt-dlp-extracted stream URL -- no video file is ever
saved for stream mode. If the stream read fails, falls back to a
chunk-scoped download (app.nodes.frames.download_chunk_video, Task 2)
instead of the whole video.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess  # nosec B404 - only ever called with a fixed arg list, never shell=True
import threading
from pathlib import Path
from typing import Callable

import imagehash
from PIL import Image, ImageFilter, ImageStat

from app.config import load_settings
from app.youtube import download_chunk_video as _download_chunk_video
from app.youtube import download_video_for_frames as _download_video_for_frames
from app.youtube import get_stream_url as _get_stream_url

SCENE_THRESHOLD = 0.4
FFMPEG_TIMEOUT_SECONDS = 300

# Perceptual-hash Hamming distance at/below which two frames count as
# near-duplicates (imagehash.phash default is a 64-bit hash; empirically a
# handful of bits of difference is still visually "the same slide").
HAMMING_DEDUPE_THRESHOLD = 4
# Grayscale pixel-value standard deviation below which a frame is treated
# as blank/solid-color (e.g. a black transition frame) and dropped.
BLANK_STDDEV_THRESHOLD = 5.0
# Variance of the Laplacian/edge-detected grayscale image below which a
# frame is treated as motion-blurred (e.g. a mid-transition scene-cut
# frame ffmpeg's scene filter occasionally grabs) and dropped -- a sharp
# frame has high-contrast edges (high variance); a blurred one has edges
# smoothed into low-contrast gradients (low variance). Deliberately low: a
# false positive here throws away a real screenshot, so this only catches
# frames that are clearly, not just slightly, out of focus.
BLUR_VARIANCE_THRESHOLD = 15.0
# Pixels trimmed off each edge before measuring blur variance -- PIL's
# FIND_EDGES filter reports a spurious bright border one pixel wide around
# every image (its convolution padding, not real content), which would
# otherwise inflate every frame's variance and make even a blank image look
# "sharp" (verified against a real blank frame: border-inclusive variance
# was ~3750 vs. 0.0 once cropped).
_BLUR_CROP_MARGIN = 3

logger = logging.getLogger(__name__)

_PTS_TIME_RE = re.compile(r"pts_time:([\d.]+)")


def _parse_frame_timestamps(stderr: str, start_seconds: float) -> list[float]:
    """ffmpeg's showinfo filter reports pts_time relative to the -ss seek
    point, so add start_seconds back to get a timestamp relative to the
    whole video.
    """
    return [start_seconds + float(match) for match in _PTS_TIME_RE.findall(stderr)]


def detect_scenes(
    stream_url: str,
    start_seconds: float,
    end_seconds: float,
    output_dir: str | Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    timestamp_offset: float | None = None,
) -> list[dict]:
    """Run ffmpeg's scene-detection filter over [start_seconds, end_seconds)
    of stream_url (a stream URL or a local file path -- ffmpeg doesn't
    care), writing one JPEG per detected scene change.

    Returns a list of {"path": Path, "timestamp_seconds": float} in order.
    Raises RuntimeError if ffmpeg exits non-zero, so the caller can decide
    whether to fall back to a scoped download (detect_scenes_with_fallback).
    `timestamp_offset` defaults to `start_seconds` (the normal case: ffmpeg
    seeks within stream_url itself); the fallback path passes it explicitly
    when scanning an already-scoped local file from its own beginning.
    """
    if timestamp_offset is None:
        timestamp_offset = start_seconds

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    duration = end_seconds - start_seconds

    result = runner(
        [
            "ffmpeg",
            # Decode keyframes only: measured 4.7x faster (425x vs 90x real
            # time) on a real 27-minute lecture. It finds fewer scene changes
            # (48 vs 150 after dedupe), but the book keeps at most
            # MAX_SCREENSHOTS_PER_CHUNK (12) per chunk, so nothing is lost.
            "-skip_frame",
            "nokey",
            "-ss",
            str(start_seconds),
            "-i",
            stream_url,
            "-t",
            str(duration),
            "-vf",
            # format=yuvj420p forces full-range YUV so the mjpeg encoder
            # accepts it regardless of the source's color range -- a
            # real H.264 "tv" (limited)-range download otherwise fails
            # mjpeg encoding with "Non full-range YUV is non-standard",
            # found live against a real downloaded chunk.
            f"select='gt(scene,{SCENE_THRESHOLD})',showinfo,format=yuvj420p",
            "-fps_mode",
            "vfr",
            "-qscale:v",
            "2",
            str(output_dir / "scene_%04d.jpg"),
        ],
        capture_output=True,
        text=True,
        timeout=FFMPEG_TIMEOUT_SECONDS,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg scene detection failed (exit {result.returncode}):\n{result.stderr}"
        )

    frame_paths = sorted(output_dir.glob("scene_*.jpg"))
    timestamps = _parse_frame_timestamps(result.stderr, timestamp_offset)

    return [
        {"path": path, "timestamp_seconds": timestamp}
        for path, timestamp in zip(frame_paths, timestamps)
    ]


def detect_scenes_with_fallback(
    video_url: str,
    start_seconds: float,
    end_seconds: float,
    output_dir: str | Path,
    get_stream_url: Callable[[str], str] = _get_stream_url,
    download_chunk_video: Callable[[str, float, float, str], Path] = _download_chunk_video,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[dict]:
    """Try stream-mode scene detection first; on failure, fall back to a
    chunk-scoped download (not the whole video) and retry against the
    local file, reporting timestamps offset back to absolute video time.

    Catches both a non-zero ffmpeg exit (RuntimeError) and a stalled
    connection (subprocess.TimeoutExpired) -- verified live against a
    sandbox where ffmpeg's direct stream read hung indefinitely against a
    real googlevideo.com URL while yt-dlp's own downloader succeeded
    quickly, so a timeout is a real failure mode this must catch, not just
    a non-zero exit.
    """
    stream_url = get_stream_url(video_url)
    try:
        return detect_scenes(stream_url, start_seconds, end_seconds, output_dir, runner=runner)
    except (RuntimeError, subprocess.TimeoutExpired) as stream_error:
        logger.warning(
            "stream-mode scene detection failed for %s [%s, %s): %s -- falling back to a "
            "chunk-scoped download",
            video_url,
            start_seconds,
            end_seconds,
            stream_error,
        )
        local_path = download_chunk_video(video_url, start_seconds, end_seconds, output_dir)
        return detect_scenes(
            str(local_path),
            0.0,
            end_seconds - start_seconds,
            output_dir,
            runner=runner,
            timestamp_offset=start_seconds,
        )


def _edge_variance(grayscale: Image.Image, margin: int = _BLUR_CROP_MARGIN) -> float:
    """Variance of Laplacian-style edge response, the standard sharp/blur
    proxy: a sharp image has strong, high-contrast edges (high variance);
    a blurred one has edges smoothed into low-contrast gradients (low
    variance). `margin` crops PIL's FIND_EDGES border artifact out before
    measuring -- see BLUR_VARIANCE_THRESHOLD's comment.
    """
    edges = grayscale.filter(ImageFilter.FIND_EDGES)
    width, height = edges.size
    if width > 2 * margin and height > 2 * margin:
        edges = edges.crop((margin, margin, width - margin, height - margin))
    return ImageStat.Stat(edges).var[0]


_video_locks: dict[str, threading.Lock] = {}
_video_locks_guard = threading.Lock()


def local_video_path(video_id: str, output_dir: str | Path) -> Path:
    """Where VIDEO_MODE=download keeps a video's temporary 480p copy while
    its chunks are scanned. graph.py's frames node deletes this whole
    directory once every chunk is done."""
    return Path(output_dir) / "work" / "frames" / "_video" / f"{video_id}.mp4"


def _ensure_local_video(
    video_id: str,
    video_url: str,
    output_dir: str | Path,
    download_video: Callable[[str, Path], Path] = _download_video_for_frames,
) -> Path:
    """Download a video once even when several of its chunks are scanned
    concurrently (graph.py runs chunks on a thread pool)."""
    path = local_video_path(video_id, output_dir)
    # Keyed by path, not video_id: two books of the same video download into
    # their own output dirs and shouldn't block on each other.
    with _video_locks_guard:
        lock = _video_locks.setdefault(str(path), threading.Lock())
    with lock:
        if not path.exists():
            download_video(video_url, path)
        return path


def detect_scenes_downloaded(
    video_id: str,
    video_url: str,
    start_seconds: float,
    end_seconds: float,
    output_dir: str | Path,
    scene_dir: str | Path,
    download_video: Callable[[str, Path], Path] = _download_video_for_frames,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[dict]:
    """VIDEO_MODE=download: scan [start, end) of a locally downloaded copy.
    ffmpeg's -ss seek on a local file is fast, and the stream throttling
    that makes stream mode slow doesn't apply. Falls back to stream mode
    if the download itself fails, so a bad download never loses a chunk's
    screenshots."""
    try:
        local = _ensure_local_video(video_id, video_url, output_dir, download_video)
    except Exception as error:  # noqa: BLE001 - degrade to stream mode, never lose the chunk
        logger.warning(
            "download for scene detection failed for %s (%s); falling back to stream mode",
            video_url,
            error,
        )
        return detect_scenes_with_fallback(video_url, start_seconds, end_seconds, scene_dir)
    return detect_scenes(str(local), start_seconds, end_seconds, scene_dir, runner=runner)


def dedupe_frames(
    frames: list[dict],
    hamming_threshold: int = HAMMING_DEDUPE_THRESHOLD,
    blank_stddev_threshold: float = BLANK_STDDEV_THRESHOLD,
    blur_variance_threshold: float = BLUR_VARIANCE_THRESHOLD,
) -> list[dict]:
    """Drop near-duplicate, blank/solid-color, and motion-blurred frames.

    `frames` is detect_scenes's output ({"path", "timestamp_seconds"},
    already in timestamp order). Returns the kept subset, same order, same
    shape -- so a static slide held for 20 minutes keeps ~1 screenshot
    instead of flooding the book with near-identical frames, and a
    scene-cut frame ffmpeg grabbed mid-transition (still visibly blurred)
    never makes it into the book as a bad screenshot.
    """
    kept: list[dict] = []
    kept_hashes: list[imagehash.ImageHash] = []

    for frame in frames:
        with Image.open(frame["path"]) as image:
            grayscale = image.convert("L")
            if ImageStat.Stat(grayscale).stddev[0] < blank_stddev_threshold:
                continue

            if _edge_variance(grayscale) < blur_variance_threshold:
                continue

            phash = imagehash.phash(image)

        if any(phash - kept_hash <= hamming_threshold for kept_hash in kept_hashes):
            continue

        kept.append(frame)
        kept_hashes.append(phash)

    return kept


# A whiteboard / drawing video changes a little at a time, so scene detection
# finds almost nothing -- a real 44-minute system-design video gave 0 frames
# with keyframe-only decoding and 2 with full decoding, and its finished
# architecture drawing (the video's last frame) never reached the book.
# Below this many scene frames, a chunk is also sampled at a fixed interval;
# and every chunk's final moment is always grabbed (the finished drawing).
_MIN_SCENE_FRAMES = 3
_FALLBACK_INTERVAL_SECONDS = 150.0
_FINAL_FRAME_OFFSET_SECONDS = 3.0


def _extra_frame_times(chunk: dict, scene_frame_count: int) -> list[float]:
    start, end = float(chunk["start_seconds"]), float(chunk["end_seconds"])
    times = [max(start, end - _FINAL_FRAME_OFFSET_SECONDS)]
    if scene_frame_count < _MIN_SCENE_FRAMES:
        moment = start + _FALLBACK_INTERVAL_SECONDS / 2
        while moment < end - _FINAL_FRAME_OFFSET_SECONDS:
            times.append(moment)
            moment += _FALLBACK_INTERVAL_SECONDS
    return sorted(times)


def _frame_source(video_id: str, video_url: str, output_dir: str | Path) -> str:
    """The downloaded copy if this run has one, else a stream URL."""
    local = local_video_path(video_id, output_dir)
    return str(local) if local.exists() else _get_stream_url(video_url)


def grab_frames(
    source: str,
    timestamps: list[float],
    output_dir: str | Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[dict]:
    """One JPEG per timestamp (fast seek), as {"path", "timestamp_seconds"}."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for timestamp in timestamps:
        path = output_dir / f"grab_{int(timestamp * 1000):010d}.jpg"
        runner(
            ["ffmpeg", "-y", "-ss", str(timestamp), "-i", source, "-frames:v", "1", "-qscale:v", "2", str(path)],
            capture_output=True,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
        if path.exists():
            frames.append({"path": path, "timestamp_seconds": timestamp})
    return frames


def limit_frames(frames: list[dict], max_frames: int) -> list[dict]:
    """Keep at most `max_frames` screenshots, evenly spread across the chunk
    (first and last included), so the book still covers the whole video.

    A talking-head lecture has a "scene change" every few seconds: one real
    27-minute video kept 153 distinct frames after dedupe -- a 150-figure
    chapter that crashed LaTeX, bloated the PDF, and slowed rendering. 0 = no
    limit.
    """
    if max_frames <= 0 or len(frames) <= max_frames:
        return frames
    if max_frames == 1:
        return [frames[0]]
    step = (len(frames) - 1) / (max_frames - 1)
    return [frames[round(index * step)] for index in range(max_frames)]


def frames_output_path(video_id: str, chunk_index: int, output_dir: str | Path) -> Path:
    """The deterministic work/frames/<video_id>_<chunk_index>.json path for a chunk.

    Exposed so callers (e.g. graph.py) can check whether a chunk's
    screenshots are already on disk without calling ffmpeg to find out.
    """
    return Path(output_dir) / "work" / "frames" / f"{video_id}_{chunk_index:03d}.json"


# Worst-case size of the temporary 480p video-only copy (measured ~50MB/hour
# on a talking-head lecture; busier video is bigger), and the free-space
# safety factor required on top of it.
_DOWNLOAD_GB_PER_HOUR = 0.3
_DISK_SAFETY_FACTOR = 3


def _enough_disk_for_download(video_duration_seconds: float, output_dir: str | Path) -> bool:
    path = Path(output_dir).resolve()
    while not path.exists() and path != path.parent:
        path = path.parent
    needed_gb = max(
        1.0, video_duration_seconds / 3600 * _DOWNLOAD_GB_PER_HOUR * _DISK_SAFETY_FACTOR
    )
    free_gb = shutil.disk_usage(path).free / 1e9
    if free_gb < needed_gb:
        logger.warning(
            "only %.1fGB free (need ~%.1fGB) for a temporary download; "
            "streaming screenshots instead",
            free_gb,
            needed_gb,
        )
    return free_gb >= needed_gb


def _should_download(
    video_duration_seconds: float | None, output_dir: str | Path | None = None
) -> bool:
    """Download (fast) rather than stream (throttled) when VIDEO_MODE says so,
    or when VIDEO_MODE=stream and the video is within
    FRAMES_DOWNLOAD_MAX_MINUTES (the default covers a ~13-hour video) and the
    disk has room for the temporary copy. Beyond that it keeps streaming, so
    a 30-hour playlist never needs tens of GB."""
    settings = load_settings()
    if settings.video_mode == "download":
        return True
    max_seconds = settings.frames_download_max_minutes * 60
    if not video_duration_seconds or video_duration_seconds > max_seconds:
        return False
    return output_dir is None or _enough_disk_for_download(video_duration_seconds, output_dir)


def run_frames(
    video_id: str,
    video_url: str,
    chunk: dict,
    output_dir: str | Path,
    video_duration_seconds: float | None = None,
) -> Path:
    """Detect + dedupe one chunk's screenshots, save kept images under
    assets/<video_id>/, and write work/frames/<video_id>_<chunk>.json.

    `chunk` is one chunk.py chunk dict: at least `chunk_index`,
    `start_seconds`, `end_seconds`. Self-cache-skippable: if this chunk's
    output file already exists, returns it immediately without calling
    ffmpeg again (root AGENTS.md crash safety).
    """
    output_dir = Path(output_dir)
    output_path = frames_output_path(video_id, chunk["chunk_index"], output_dir)
    if output_path.exists():
        return output_path

    scene_dir = (
        output_dir / "work" / "frames" / "_scenes" / f"{video_id}_{chunk['chunk_index']:03d}"
    )
    if _should_download(video_duration_seconds, output_dir):
        detected = detect_scenes_downloaded(
            video_id,
            video_url,
            chunk["start_seconds"],
            chunk["end_seconds"],
            output_dir,
            scene_dir,
        )
    else:
        detected = detect_scenes_with_fallback(
            video_url, chunk["start_seconds"], chunk["end_seconds"], scene_dir
        )
    try:
        extra = grab_frames(
            _frame_source(video_id, video_url, output_dir),
            _extra_frame_times(chunk, len(detected)),
            scene_dir,
        )
    except Exception as error:  # noqa: BLE001 - extra frames are a bonus, never fatal
        logger.warning("could not grab extra frames for %s chunk %s: %s", video_id, chunk["chunk_index"], error)
        extra = []
    frames = sorted([*detected, *extra], key=lambda frame: frame["timestamp_seconds"])
    kept = limit_frames(dedupe_frames(frames), load_settings().max_screenshots_per_chunk)

    assets_dir = output_dir / "assets" / video_id
    assets_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for index, frame in enumerate(kept):
        asset_path = assets_dir / f"{chunk['chunk_index']:03d}_{index:02d}.jpg"
        shutil.copyfile(frame["path"], asset_path)
        saved.append({"asset_path": str(asset_path), "timestamp_seconds": frame["timestamp_seconds"]})

    shutil.rmtree(scene_dir, ignore_errors=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {"video_id": video_id, "chunk_index": chunk["chunk_index"], "frames": saved},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return output_path


def load_video_screenshots(video_id: str, output_dir: str | Path) -> list[dict]:
    """Load every kept screenshot across all of one video's chunks.

    Used by graph.py's video-mode render node (BOOK_ORDER=video): a
    chapter is one whole video, so it gets every one of that video's
    chunks' screenshots. Returns [] if the frames step never ran for this
    video (e.g. VIDEO_MODE=captions_only) -- not an error.
    """
    frames_dir = Path(output_dir) / "work" / "frames"
    screenshots: list[dict] = []
    for frames_path in sorted(frames_dir.glob(f"{video_id}_*.json")):
        payload = json.loads(frames_path.read_text(encoding="utf-8"))
        screenshots.extend(limit_frames(payload["frames"], load_settings().max_screenshots_per_chunk))
    return screenshots


def load_screenshots_for_sources(sources: list[dict], output_dir: str | Path) -> list[dict]:
    """Load every kept screenshot for an exact list of {video_id,
    chunk_index} source chunks.

    Used by graph.py's topic-mode render node (BOOK_ORDER=topic): a topic
    chapter only gets screenshots from the specific chunks in its
    `sources`, not every chunk of every source video. Returns [] entries
    silently skipped if the frames step never ran for that chunk.
    """
    screenshots: list[dict] = []
    for source in sources:
        frames_path = frames_output_path(source["video_id"], source["chunk_index"], output_dir)
        if not frames_path.exists():
            continue
        payload = json.loads(frames_path.read_text(encoding="utf-8"))
        screenshots.extend(limit_frames(payload["frames"], load_settings().max_screenshots_per_chunk))
    return screenshots
