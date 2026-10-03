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

from app.config import load_settings
from app.transcribe import transcribe_audio_to_vtt


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

    # A "watch?v=...&list=..." URL can flat-resolve to a `_type: "url"`
    # pointer at the playlist tab (e.g. ".../playlist?list=...") instead of
    # directly to the playlist's entries. Follow it so a real "id" from the
    # pointer (the playlist id) never gets mistaken for a video id below.
    hops = 0
    while info is not None and info.get("_type") == "url" and info.get("url"):
        if hops >= 5:
            raise ValueError(f"Too many redirects resolving playlist URL: {url}")
        with ydl_factory(opts) as ydl:
            info = ydl.extract_info(info["url"], download=False)
        hops += 1

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
    transcript_source: str | None = None,
    whisper_transcribe: Callable[[str | Path, str | Path], Path] = transcribe_audio_to_vtt,
) -> VideoInfo:
    """Fetch metadata + transcript for one video without downloading the
    video file. `transcript_source` (default: TRANSCRIPT_SOURCE setting,
    "auto" | "captions" | "whisper") picks the source:

    - "captions": YouTube captions only -- raises CaptionsUnavailableError
      if none exist, same as this function's original (pre-Whisper-
      fallback) behavior.
    - "whisper": skips the captions attempt entirely, transcribes audio
      via Whisper directly.
    - "auto" (default): tries captions first (free, instant); if none
      exist, falls back to downloading audio + Whisper transcription
      rather than failing the whole video.

    Either way, the returned `captions_path` always points at a plain VTT
    file -- app.nodes.chunk (and everything downstream) never needs to
    know or care which source produced it.
    """
    languages = languages or ["en"]
    captions_dir = Path(captions_dir)
    captions_dir.mkdir(parents=True, exist_ok=True)
    transcript_source = transcript_source or load_settings().transcript_source

    if transcript_source == "whisper":
        metadata = fetch_metadata(url, ydl_factory)
        vtt_path = captions_dir / f"{metadata.video_id}.{languages[0]}.vtt"
        _transcribe_via_whisper(url, vtt_path, captions_dir, ydl_factory, whisper_transcribe)
        return VideoInfo(
            video_id=metadata.video_id,
            title=metadata.title,
            duration_seconds=metadata.duration_seconds,
            url=url,
            captions_path=str(vtt_path),
        )

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
        if transcript_source == "captions":
            raise CaptionsUnavailableError(
                f"no captions found for {url} in languages {languages}"
            )
        # auto: fall back to Whisper rather than failing the whole video.
        vtt_path = captions_dir / f"{info['id']}.{languages[0]}.vtt"
        _transcribe_via_whisper(url, vtt_path, captions_dir, ydl_factory, whisper_transcribe)
        captions_path = vtt_path

    return VideoInfo(
        video_id=info["id"],
        title=info["title"],
        duration_seconds=int(info.get("duration") or 0),
        url=url,
        captions_path=str(captions_path),
    )


def _transcribe_via_whisper(
    url: str,
    vtt_path: Path,
    audio_dir: Path,
    ydl_factory: Callable[[dict[str, Any]], Any],
    whisper_transcribe: Callable[[str | Path, str | Path], Path],
) -> None:
    """Downloads audio-only (never the video), transcribes it, then always
    deletes the audio file -- root AGENTS.md: no video/audio file is kept
    around, stream mode's guarantee applies to this fallback path too."""
    audio_path = download_audio(url, audio_dir, ydl_factory)
    try:
        whisper_transcribe(audio_path, vtt_path)
    finally:
        Path(audio_path).unlink(missing_ok=True)


def download_audio(
    url: str,
    output_dir: str | Path,
    ydl_factory: Callable[[dict[str, Any]], Any] = yt_dlp.YoutubeDL,
) -> Path:
    """Downloads audio-only (bestaudio, never video) for the Whisper
    fallback. Caller is responsible for deleting it once transcribed."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }

    with ydl_factory(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    audio_path = output_dir / f"{info['id']}.{info['ext']}"
    if not audio_path.exists():
        raise RuntimeError(f"audio download produced no file for {url}")
    return audio_path


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
