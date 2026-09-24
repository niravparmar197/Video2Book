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
    videos = [
        replace(fetch_video(entry.url, captions_dir), playlist_index=entry.playlist_index)
        for entry in entries
    ]
    _write_videos_json(output_dir, videos)
    return videos


def _write_videos_json(output_dir: Path, videos: list[VideoInfo]) -> None:
    payload = [
        {
            "video_id": video.video_id,
            "title": video.title,
            "duration_seconds": video.duration_seconds,
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
