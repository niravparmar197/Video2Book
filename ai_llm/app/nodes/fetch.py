"""Fetch node: video metadata + captions -> videos.json.

`run_fetch` fetches a single video URL (v1 behavior, still used by
graph.py). `run_fetch_playlist` resolves a playlist (or single video) URL
into an ordered video list via app.youtube.list_playlist_videos and fetches
captions for every entry — the graph loop that consumes it is wired up in a
later sprint task.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from app.youtube import VideoInfo, fetch_video, list_playlist_videos


def run_fetch(
    url: str,
    output_dir: str | Path,
    captions_dir: str | Path | None = None,
) -> VideoInfo:
    """Fetch one video's metadata + captions and write output_dir/videos.json."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    captions_dir = Path(captions_dir) if captions_dir else output_dir / "work" / "captions"

    video = fetch_video(url, captions_dir)
    _write_videos_json(output_dir, [video])
    return video


def run_fetch_playlist(
    url: str,
    output_dir: str | Path,
    captions_dir: str | Path | None = None,
) -> list[VideoInfo]:
    """Fetch metadata + captions for every video in a playlist and write
    output_dir/videos.json as one entry per video, in playlist order.

    A plain (non-playlist) video URL resolves to a list of 1, same as
    run_fetch but through the playlist-aware path.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    captions_dir = Path(captions_dir) if captions_dir else output_dir / "work" / "captions"

    entries = list_playlist_videos(url)
    already_fetched = _load_fetched_videos(output_dir, captions_dir)
    videos = [
        replace(
            already_fetched.get(entry.video_id) or fetch_video(entry.url, captions_dir),
            playlist_index=entry.playlist_index,
        )
        for entry in entries
    ]
    _write_videos_json(output_dir, videos)
    return videos


def _load_fetched_videos(output_dir: Path, captions_dir: Path) -> dict[str, VideoInfo]:
    """Videos already fetched for this book (videos.json + their captions on
    disk), keyed by video id.

    The backend runs the graph twice (plan, then render), and --resume runs
    it again: without this every pass re-downloaded the captions (4-30s each,
    and a fresh chance of YouTube's HTTP 429 rate limit) or even re-ran Whisper
    for a video whose transcript was already sitting on disk.
    """
    videos_json_path = output_dir / "videos.json"
    if not videos_json_path.exists():
        return {}
    try:
        records = json.loads(videos_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    fetched: dict[str, VideoInfo] = {}
    for record in records:
        # videos.json may hold a path relative to another cwd; fall back to
        # the standard captions location.
        captions_path = next(
            (
                candidate
                for candidate in (Path(record["captions_path"]), captions_dir / f"{record['video_id']}.en.vtt")
                if candidate.exists()
            ),
            None,
        )
        if captions_path is not None:
            fetched[record["video_id"]] = VideoInfo(
                video_id=record["video_id"],
                title=record["title"],
                duration_seconds=record["duration_seconds"],
                url=record["url"],
                captions_path=str(captions_path),
                playlist_index=record.get("playlist_index", 0),
                channel=record.get("channel", ""),
                chapters=tuple(record.get("chapters") or ()),
            )
    return fetched


def _write_videos_json(output_dir: Path, videos: list[VideoInfo]) -> None:
    payload = [
        {
            "video_id": video.video_id,
            "title": video.title,
            "duration_seconds": video.duration_seconds,
            "channel": video.channel,
            "chapters": list(video.chapters),
            "url": video.url,
            "captions_path": video.captions_path,
            "playlist_index": video.playlist_index,
        }
        for video in videos
    ]
    videos_json_path = output_dir / "videos.json"
    videos_json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
