"""Frames node: stream-mode scene detection + screenshots (VIDEO_MODE=stream).

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
from pathlib import Path
from typing import Callable

import imagehash
from PIL import Image, ImageStat

from app.youtube import download_chunk_video as _download_chunk_video
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


def dedupe_frames(
    frames: list[dict],
    hamming_threshold: int = HAMMING_DEDUPE_THRESHOLD,
    blank_stddev_threshold: float = BLANK_STDDEV_THRESHOLD,
) -> list[dict]:
    """Drop near-duplicate and blank/solid-color frames.

    `frames` is detect_scenes's output ({"path", "timestamp_seconds"},
    already in timestamp order). Returns the kept subset, same order, same
    shape -- so a static slide held for 20 minutes keeps ~1 screenshot
    instead of flooding the book with near-identical frames.
    """
    kept: list[dict] = []
    kept_hashes: list[imagehash.ImageHash] = []

    for frame in frames:
        with Image.open(frame["path"]) as image:
            grayscale = image.convert("L")
            if ImageStat.Stat(grayscale).stddev[0] < blank_stddev_threshold:
                continue

            phash = imagehash.phash(image)

        if any(phash - kept_hash <= hamming_threshold for kept_hash in kept_hashes):
            continue

        kept.append(frame)
        kept_hashes.append(phash)

    return kept


def frames_output_path(video_id: str, chunk_index: int, output_dir: str | Path) -> Path:
    """The deterministic work/frames/<video_id>_<chunk_index>.json path for a chunk.

    Exposed so callers (e.g. graph.py) can check whether a chunk's
    screenshots are already on disk without calling ffmpeg to find out.
    """
    return Path(output_dir) / "work" / "frames" / f"{video_id}_{chunk_index:03d}.json"


def run_frames(video_id: str, video_url: str, chunk: dict, output_dir: str | Path) -> Path:
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
    detected = detect_scenes_with_fallback(
        video_url, chunk["start_seconds"], chunk["end_seconds"], scene_dir
    )
    kept = dedupe_frames(detected)

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
        screenshots.extend(payload["frames"])
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
        screenshots.extend(payload["frames"])
    return screenshots
