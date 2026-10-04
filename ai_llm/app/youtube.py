"""yt-dlp wrapper: video metadata + captions fetch.

VIDEO_MODE=captions_only never downloads the video file — only metadata and
caption tracks are pulled from YouTube. See root AGENTS.md non-negotiable
decisions table.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yt_dlp

from app.config import load_settings
from app.transcribe import TRANSCRIPT_RECIPE
from app.transcribe import transcribe_audio_to_vtt

logger = logging.getLogger(__name__)


def _with_auth(opts: dict[str, Any]) -> dict[str, Any]:
    """Add the user's YouTube login cookies to a yt-dlp options dict, if set.

    After heavy use YouTube answers "Sign in to confirm you're not a bot"
    for every request from the IP; a signed-in session gets through.
    YOUTUBE_COOKIES_FILE (a Netscape cookies.txt exported from the browser)
    wins over YOUTUBE_COOKIES_BROWSER (read straight from an installed
    browser, e.g. "firefox" or "edge"). Neither set: unchanged.
    """
    settings = load_settings()
    # A short pause between yt-dlp's own requests: bursts of back-to-back
    # requests are what got this IP flagged as a bot.
    opts = {"sleep_interval_requests": _REQUEST_PAUSE_SECONDS, **opts}
    if settings.youtube_cookies_file:
        return {**opts, "cookiefile": settings.youtube_cookies_file}
    if settings.youtube_cookies_browser:
        return {**opts, "cookiesfrombrowser": (settings.youtube_cookies_browser,)}
    return opts


_REQUEST_PAUSE_SECONDS = 0.5


@dataclass(frozen=True)
class VideoInfo:
    video_id: str
    title: str
    duration_seconds: int
    url: str
    captions_path: str
    playlist_index: int = 1
    # The YouTube channel -- the strongest hint of a video's genre (a clip
    # from "The Diary Of A CEO Clips" is a podcast even if one person talks).
    channel: str = ""
    # YouTube's own chapters: ({title, start_seconds, end_seconds}, ...).
    chapters: tuple[dict, ...] = ()


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


class VideoUnavailableError(RuntimeError):
    """Raised when YouTube refuses a URL for a reason the user can act on:
    members-only, private, removed, age- or region-restricted. The message is
    YouTube's own reason, without yt-dlp's "ERROR: [youtube] <id>:" prefix."""


_YT_DLP_PREFIX_RE = re.compile(r"^(?:\x1b\[[0-9;]*m)*ERROR:(?:\x1b\[[0-9;]*m)*\s*(?:\[[\w:]+\]\s*)?(?:[\w-]{11}:\s*)?")


def list_playlist_videos(
    url: str,
    ydl_factory: Callable[[dict[str, Any]], Any] = yt_dlp.YoutubeDL,
) -> list[PlaylistEntry]:
    """Resolve a playlist (or single video) URL into an ordered video list.

    Uses extract_flat so this never downloads captions/metadata for each
    video — just enough to loop the per-video pipeline in playlist order.
    A plain video URL (no "entries" in the result) returns a list of 1, so
    the same call works for both a playlist and a single video.

    A single-video link whose video is already in the shared cache needs no
    YouTube request at all.
    """
    video_id = _video_id_from_url(url)
    if video_id and "list=" not in url:
        cached = _load_cached_meta(video_id)
        if cached is not None:
            return [
                PlaylistEntry(
                    video_id=video_id,
                    title=cached["title"],
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    playlist_index=1,
                )
            ]

    opts = {
        "extract_flat": True,
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with ydl_factory(_with_auth(opts)) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as error:
        raise VideoUnavailableError(_YT_DLP_PREFIX_RE.sub("", str(error)).strip()) from error

    # A "watch?v=...&list=..." URL can flat-resolve to a `_type: "url"`
    # pointer at the playlist tab (e.g. ".../playlist?list=...") instead of
    # directly to the playlist's entries. Follow it so a real "id" from the
    # pointer (the playlist id) never gets mistaken for a video id below.
    hops = 0
    while info is not None and info.get("_type") == "url" and info.get("url"):
        if hops >= 5:
            raise ValueError(f"Too many redirects resolving playlist URL: {url}")
        with ydl_factory(_with_auth(opts)) as ydl:
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

    Used by --estimate, which must never write to the filesystem or call an
    LLM. A video fetched before is answered from the shared cache, with no
    YouTube request.
    """
    video_id = _video_id_from_url(url)
    cached = _load_cached_meta(video_id) if video_id else None
    if cached is not None:
        return VideoMetadata(
            video_id=video_id,
            title=cached["title"],
            duration_seconds=int(cached["duration_seconds"]),
        )

    opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
    }

    with ydl_factory(_with_auth(opts)) as ydl:
        info = ydl.extract_info(url, download=False)

    return VideoMetadata(
        video_id=info["id"],
        title=info["title"],
        duration_seconds=int(info.get("duration") or 0),
    )


# Seconds to wait before each retry when YouTube answers a caption download
# with HTTP 429. It is an IP-level limit that clears by itself, so a short
# pause often works; if not, auto mode falls back to Whisper instead of failing.
_RATE_LIMIT_WAITS = (10, 30)


def _download_captions(
    url: str,
    opts: dict[str, Any],
    ydl_factory: Callable[[dict[str, Any]], Any],
    sleep: Callable[[float], None],
    waits: tuple[float, ...] = _RATE_LIMIT_WAITS,
) -> dict | None:
    """Download captions + metadata; None if YouTube still says 429 after
    retrying once per entry in `waits` (seconds to pause before each retry).
    Any other download error is raised unchanged."""
    for wait in (*waits, None):
        try:
            with ydl_factory(_with_auth(opts)) as ydl:
                return ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as error:
            if "429" not in str(error) and "Too Many Requests" not in str(error):
                raise
            if wait is None:
                return None
            logger.warning("caption download rate-limited (HTTP 429); retrying in %ss", wait)
            sleep(wait)
    return None


def original_caption_tracks(language: str | None) -> list[str]:
    """Caption track names that can hold the video's own language, best first.

    YouTube reports a regional language ("en-US") but names tracks by the
    base language ("en-orig", "en"), so both forms are tried. With no
    language reported, only English is tried.
    """
    languages = []
    for code in (language, (language or "").split("-")[0], "en" if not language else None):
        if code and code not in languages:
            languages.append(code)
    return [track for code in languages for track in (f"{code}-orig", code)]


def _download_original_language_captions(
    url: str,
    caption_opts: dict[str, Any],
    captions_dir: Path,
    ydl_factory: Callable[[dict[str, Any]], Any],
    sleep: Callable[[float], None],
) -> tuple[dict, Path] | None:
    """Download the video's own-language caption track (e.g. "hi-orig" for a
    Hindi video) when the requested language is missing or rate-limited.
    Returns (info, path), or None if the video has no such track (or YouTube
    still rate-limits it after the retries)."""
    try:
        with ydl_factory(_with_auth({"skip_download": True, "quiet": True, "no_warnings": True})) as ydl:
            metadata = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError:
        return None

    available = {**(metadata.get("automatic_captions") or {}), **(metadata.get("subtitles") or {})}
    candidates = [track for track in original_caption_tracks(metadata.get("language")) if track in available]
    if not candidates:
        # Never fall back to an arbitrary "-orig" track: a video with AI-dubbed
        # audio has one per dub language, and a real book got an *Arabic*
        # transcript of an English talk that way. Whisper is the safer fallback.
        return None

    track = candidates[0]
    info = _download_captions(url, {**caption_opts, "subtitleslangs": [track]}, ydl_factory, sleep)
    if info is None:
        return None
    path = _resolve_captions_path(info, captions_dir, [track])
    return (info, path) if path is not None else None


def _fetch_video_uncached(
    url: str,
    captions_dir: str | Path,
    languages: list[str] | None = None,
    ydl_factory: Callable[[dict[str, Any]], Any] = yt_dlp.YoutubeDL,
    transcript_source: str | None = None,
    whisper_transcribe: Callable[[str | Path, str | Path], Path] = transcribe_audio_to_vtt,
    sleep: Callable[[float], None] = time.sleep,
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
        _transcribe_via_whisper(
            url, metadata.video_id, vtt_path, captions_dir, ydl_factory, whisper_transcribe
        )
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

    # One try, no waiting: the English track of a non-English video is
    # YouTube's machine *translation*, which it rate-limits (HTTP 429) far more
    # than the original track, so waiting on it only wastes time.
    info = _download_captions(url, opts, ydl_factory, sleep, waits=())
    rate_limited = info is None
    captions_path = _resolve_captions_path(info, captions_dir, languages) if info else None

    if captions_path is None:
        # The video's own language track (e.g. hi-orig). The notes prompts
        # already translate any language to English, so this is far cheaper
        # than Whisper (~5-7 min per 30 min of audio on CPU).
        original = _download_original_language_captions(url, opts, captions_dir, ydl_factory, sleep)
        if original is not None:
            info, captions_path = original

    if captions_path is None:
        if info is None:
            metadata = fetch_metadata(url, ydl_factory)
            info = {
                "id": metadata.video_id,
                "title": metadata.title,
                "duration": metadata.duration_seconds,
            }
        if transcript_source == "captions":
            raise CaptionsUnavailableError(
                f"YouTube is rate-limiting caption downloads (HTTP 429) for {url}; wait a while "
                "and retry, or set TRANSCRIPT_SOURCE=auto to fall back to Whisper"
                if rate_limited
                else f"no captions found for {url} in languages {languages}"
            )
        # auto: fall back to Whisper rather than failing the whole video.
        logger.warning("no usable YouTube captions for %s; falling back to Whisper", url)
        vtt_path = captions_dir / f"{info['id']}.{languages[0]}.vtt"
        _transcribe_via_whisper(
            url, info["id"], vtt_path, captions_dir, ydl_factory, whisper_transcribe
        )
        captions_path = vtt_path

    return VideoInfo(
        video_id=info["id"],
        title=info["title"],
        duration_seconds=int(info.get("duration") or 0),
        url=url,
        captions_path=str(captions_path),
        channel=str(info.get("channel") or info.get("uploader") or ""),
        chapters=_chapters_from_info(info),
    )


def _chapters_from_info(info: dict[str, Any]) -> tuple[dict, ...]:
    """YouTube's creator-made chapters ({title, start_seconds, end_seconds}),
    if the video has any."""
    return tuple(
        {
            "title": str(chapter.get("title") or "").strip(),
            "start_seconds": float(chapter.get("start_time") or 0),
            "end_seconds": float(chapter.get("end_time") or 0),
        }
        for chapter in info.get("chapters") or []
        if str(chapter.get("title") or "").strip()
    )


# --- shared video cache --------------------------------------------------
# Every book of the same video (and every plan/render/retry pass, and the
# backend's up-front estimate) used to ask YouTube again. After a day of
# that YouTube answered "Sign in to confirm you're not a bot" for every
# request from the IP. Metadata + transcript are now kept per video id in
# the shared transcript cache, so a video is fetched from YouTube once.

_VIDEO_ID_RE = re.compile(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{6,})")


def _video_id_from_url(url: str) -> str | None:
    match = _VIDEO_ID_RE.search(url)
    return match.group(1) if match else None


def _meta_cache_path(video_id: str) -> Path:
    return Path(load_settings().transcript_cache_dir) / f"{video_id}.meta.json"


def _captions_cache_path(video_id: str) -> Path:
    return Path(load_settings().transcript_cache_dir) / f"{video_id}.transcript.vtt"


def _load_cached_meta(video_id: str) -> dict | None:
    path = _meta_cache_path(video_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _write_atomically(path: Path, data: bytes) -> None:
    # Write-then-rename so a concurrent book never reads a half-written file.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _save_cached_video(info: VideoInfo) -> None:
    # A Whisper-made transcript is tied to the Whisper recipe; YouTube
    # captions are not.
    whisper_cache = transcript_cache_path(info.video_id)
    captions = Path(info.captions_path).read_bytes()
    whisper_made = whisper_cache.exists() and whisper_cache.read_bytes() == captions
    meta = {
        "title": info.title,
        "duration_seconds": info.duration_seconds,
        "channel": info.channel,
        "chapters": list(info.chapters),
        "transcript_recipe": TRANSCRIPT_RECIPE if whisper_made else None,
    }
    _write_atomically(_captions_cache_path(info.video_id), captions)
    _write_atomically(
        _meta_cache_path(info.video_id), json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")
    )


def _load_cached_video(url: str, captions_dir: Path, language: str) -> VideoInfo | None:
    video_id = _video_id_from_url(url)
    if video_id is None:
        return None
    meta = _load_cached_meta(video_id)
    cached_captions = _captions_cache_path(video_id)
    if meta is None or not cached_captions.exists():
        return None
    if meta.get("transcript_recipe") not in (None, TRANSCRIPT_RECIPE):
        return None  # made by an older Whisper recipe
    target = captions_dir / f"{video_id}.{language}.vtt"
    captions_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cached_captions, target)
    return VideoInfo(
        video_id=video_id,
        title=meta["title"],
        duration_seconds=int(meta["duration_seconds"]),
        url=url,
        captions_path=str(target),
        channel=meta.get("channel", ""),
        chapters=tuple(meta.get("chapters") or ()),
    )


def fetch_video(
    url: str,
    captions_dir: str | Path,
    languages: list[str] | None = None,
    ydl_factory: Callable[[dict[str, Any]], Any] = yt_dlp.YoutubeDL,
    transcript_source: str | None = None,
    whisper_transcribe: Callable[[str | Path, str | Path], Path] = transcribe_audio_to_vtt,
    sleep: Callable[[float], None] = time.sleep,
) -> VideoInfo:
    """Metadata + transcript for one video: from the shared cache when this
    video was fetched before (no YouTube request at all), otherwise from
    YouTube (see _fetch_video_uncached), then cached. A forced
    TRANSCRIPT_SOURCE=whisper always transcribes afresh."""
    languages = languages or ["en"]
    transcript_source = transcript_source or load_settings().transcript_source
    if transcript_source != "whisper":
        cached = _load_cached_video(url, Path(captions_dir), languages[0])
        if cached is not None:
            return cached
    info = _fetch_video_uncached(
        url, captions_dir, languages, ydl_factory, transcript_source, whisper_transcribe, sleep
    )
    _save_cached_video(info)
    return info


def transcript_cache_path(video_id: str) -> Path:
    """Shared Whisper-transcript cache entry for one video. Keyed by the
    transcription recipe (model + decoding settings) too, so changing
    either never serves a stale transcript made the old way."""
    return Path(load_settings().transcript_cache_dir) / f"{video_id}.{TRANSCRIPT_RECIPE}.vtt"


def _transcribe_via_whisper(
    url: str,
    video_id: str,
    vtt_path: Path,
    audio_dir: Path,
    ydl_factory: Callable[[dict[str, Any]], Any],
    whisper_transcribe: Callable[[str | Path, str | Path], Path],
) -> None:
    """Downloads audio-only (never the video), transcribes it, then always
    deletes the audio file -- root AGENTS.md: no video/audio file is kept
    around, stream mode's guarantee applies to this fallback path too.

    A video already transcribed for any earlier book is copied from the
    shared transcript cache instead -- no audio download, no Whisper.
    """
    cached = transcript_cache_path(video_id)
    if cached.exists():
        vtt_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached, vtt_path)
        return

    audio_path = download_audio(url, audio_dir, ydl_factory)
    try:
        whisper_transcribe(audio_path, vtt_path)
    finally:
        Path(audio_path).unlink(missing_ok=True)

    # Write-then-rename so a concurrent book never reads a half-written file.
    cached.parent.mkdir(parents=True, exist_ok=True)
    tmp = cached.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    shutil.copyfile(vtt_path, tmp)
    os.replace(tmp, cached)


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

    with ydl_factory(_with_auth(opts)) as ydl:
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
        "format": FRAMES_VIDEO_FORMAT,
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
    }

    with ydl_factory(_with_auth(opts)) as ydl:
        info = ydl.extract_info(url, download=False)

    stream_url = info.get("url")
    if not stream_url:
        formats = info.get("requested_formats") or []
        if formats:
            stream_url = formats[0].get("url")
    if not stream_url:
        raise RuntimeError(f"could not resolve a stream URL for {url}")
    return stream_url


FRAMES_VIDEO_FORMAT = (
    "bestvideo[height<=480][vcodec^=avc1][ext=mp4]"
    "/bestvideo[height<=480][ext=mp4]"
    "/bestvideo[height<=720][ext=mp4]"
    "/bestvideo/best"
)


def download_video_for_frames(
    url: str,
    output_path: str | Path,
    ydl_factory: Callable[[dict[str, Any]], Any] = yt_dlp.YoutubeDL,
) -> Path:
    """Download a whole video, video-only, capped at 480p, for local scene
    detection (VIDEO_MODE=download). Uses yt-dlp's native chunked HTTP
    downloader -- no download_ranges, which routes through ffmpeg and gets
    throttled the same way a direct stream read does. Measured on a real
    6-minute video: 15s download + 9s local scan, vs. 191s reading the
    stream directly with ffmpeg. The caller deletes the file once every
    chunk of the video has been scanned.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": FRAMES_VIDEO_FORMAT,
        "outtmpl": str(output_path),
        "quiet": True,
        "no_warnings": True,
    }
    with ydl_factory(_with_auth(opts)) as ydl:
        ydl.download([url])
    if not output_path.exists():
        raise RuntimeError(f"video download produced no file for {url}")
    return output_path


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

    with ydl_factory(_with_auth(opts)) as ydl:
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
