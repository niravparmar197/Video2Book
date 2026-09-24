"""yt-dlp wrapper: video metadata + captions fetch.

VIDEO_MODE=captions_only never downloads the video file — only metadata and
caption tracks are pulled from YouTube. See root AGENTS.md non-negotiable
decisions table.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yt_dlp


@dataclass(frozen=True)
class VideoInfo:
    video_id: str
    title: str
    duration_seconds: int
    url: str
    captions_path: str
    playlist_index: int = 1


@dataclass(frozen=True)
class VideoMetadata:
    video_id: str
    title: str
    duration_seconds: int


@dataclass(frozen=True)
class PlaylistEntry:
    video_id: str
    title: str
    url: str
    playlist_index: int


class CaptionsUnavailableError(RuntimeError):
    """Raised when a video has no captions in any requested language."""


def list_playlist_videos(
    url: str,
    ydl_factory: Callable[[dict[str, Any]], Any] = yt_dlp.YoutubeDL,
) -> list[PlaylistEntry]:
    """Resolve a playlist (or single video) URL into an ordered video list.

    Uses extract_flat so this never downloads captions/metadata for each
    video — just enough to loop the per-video pipeline in playlist order.
    A plain video URL (no "entries" in the result) returns a list of 1, so
    the same call works for both a playlist and a single video.
    """
    opts = {
        "extract_flat": True,
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
    }

    with ydl_factory(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    entries = info.get("entries")
    if entries is None:
        return [
            PlaylistEntry(
                video_id=info["id"],
                title=info.get("title", ""),
                url=f"https://www.youtube.com/watch?v={info['id']}",
                playlist_index=1,
            )
        ]

    videos = []
    for entry in entries:
        if entry is None:
            continue
        videos.append(
            PlaylistEntry(
                video_id=entry["id"],
                title=entry.get("title", ""),
                url=f"https://www.youtube.com/watch?v={entry['id']}",
                playlist_index=len(videos) + 1,
            )
        )
    return videos


def fetch_metadata(
    url: str,
    ydl_factory: Callable[[dict[str, Any]], Any] = yt_dlp.YoutubeDL,
) -> VideoMetadata:
    """Fetch only title/duration/id — no captions, no video, no download at all.

    Used by --estimate, which must never touch the filesystem or call an LLM.
    """
    opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
    }

    with ydl_factory(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    return VideoMetadata(
        video_id=info["id"],
        title=info["title"],
        duration_seconds=int(info.get("duration") or 0),
    )


def fetch_video(
    url: str,
    captions_dir: str | Path,
    languages: list[str] | None = None,
    ydl_factory: Callable[[dict[str, Any]], Any] = yt_dlp.YoutubeDL,
) -> VideoInfo:
    """Fetch metadata + captions for one video without downloading video/audio."""
    languages = languages or ["en"]
    captions_dir = Path(captions_dir)
    captions_dir.mkdir(parents=True, exist_ok=True)

    opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": languages,
        "subtitlesformat": "vtt",
        "outtmpl": str(captions_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }

    with ydl_factory(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    captions_path = _resolve_captions_path(info, captions_dir, languages)
    if captions_path is None:
        raise CaptionsUnavailableError(
            f"no captions found for {url} in languages {languages}"
        )

    return VideoInfo(
        video_id=info["id"],
        title=info["title"],
        duration_seconds=int(info.get("duration") or 0),
        url=url,
        captions_path=str(captions_path),
    )


def get_stream_url(
    url: str,
    ydl_factory: Callable[[dict[str, Any]], Any] = yt_dlp.YoutubeDL,
) -> str:
    """Resolve a video URL to a direct, playable stream URL -- no download.

    Used by app.nodes.frames to scan a chunk's time range with ffmpeg
    directly against the network stream (root AGENTS.md: "Stream mode by
    default, no video file saved").
    """
    opts = {
        # Video-only is enough for scene detection (no audio needed), and
        # resolves to a single format with a direct url -- unlike "best",
        # which on YouTube usually resolves to a video+audio DASH pair with
        # no single combined url (see requested_formats fallback below).
        # Capped at 480p H.264 (avc1): screenshots for a book PDF don't
        # need 1080p, and a high-res VP9/AV1 stream is slow enough to
        # software-decode that scene detection over a 30-minute chunk can
        # time out -- verified empirically against a real 1080p60 stream.
        "format": (
            "bestvideo[height<=480][vcodec^=avc1][ext=mp4]"
            "/bestvideo[height<=480][ext=mp4]"
            "/bestvideo[height<=720][ext=mp4]"
            "/bestvideo/best"
        ),
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
    }

    with ydl_factory(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    stream_url = info.get("url")
    if not stream_url:
        formats = info.get("requested_formats") or []
        if formats:
            stream_url = formats[0].get("url")
    if not stream_url:
        raise RuntimeError(f"could not resolve a stream URL for {url}")
    return stream_url


def download_chunk_video(
    url: str,
    start_seconds: float,
    end_seconds: float,
    output_dir: str | Path,
    ydl_factory: Callable[[dict[str, Any]], Any] = yt_dlp.YoutubeDL,
) -> Path:
    """Download just [start_seconds, end_seconds) of a video -- not the
    whole file. Fallback for app.nodes.frames when stream-mode scene
    detection fails (root AGENTS.md: "download only as a fallback").
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    opts = {
        "format": "bestvideo[ext=mp4]/bestvideo/best",
        "download_ranges": lambda info, ydl: [
            {"start_time": start_seconds, "end_time": end_seconds}
        ],
        "force_keyframes_at_cuts": True,
        "outtmpl": str(output_dir / "chunk_video.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }

    with ydl_factory(opts) as ydl:
        ydl.download([url])

    video_files = sorted(output_dir.glob("chunk_video.*"))
    if not video_files:
        raise RuntimeError(f"chunk-scoped download produced no file for {url}")
    return video_files[0]


def _resolve_captions_path(
    info: dict[str, Any], captions_dir: Path, languages: list[str]
) -> Path | None:
    requested = info.get("requested_subtitles") or {}
    for lang in languages:
        sub = requested.get(lang)
        if sub and sub.get("filepath"):
            path = Path(sub["filepath"])
            if path.exists():
                return path

    video_id = info.get("id", "")
    for lang in languages:
        candidate = captions_dir / f"{video_id}.{lang}.vtt"
        if candidate.exists():
            return candidate

    return None
