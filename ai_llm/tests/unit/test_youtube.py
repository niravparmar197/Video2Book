"""Unit tests for app.youtube — the yt-dlp wrapper.

No real network calls: yt_dlp.YoutubeDL is replaced with a fake client that
mimics its context-manager + extract_info() interface.
"""
from pathlib import Path

import pytest

from app.youtube import (
    CaptionsUnavailableError,
    PlaylistEntry,
    VideoInfo,
    VideoMetadata,
    download_audio,
    download_chunk_video,
    fetch_metadata,
    fetch_video,
    get_stream_url,
    list_playlist_videos,
)

TEST_URL = "https://www.youtube.com/watch?v=aircAruvnKk"
TEST_VIDEO_ID = "aircAruvnKk"
TEST_TITLE = "But what is a neural network? | Deep learning chapter 1"
TEST_DURATION = 1163  # seconds, ~19 minutes


class FakeYoutubeDL:
    """Stands in for yt_dlp.YoutubeDL: records opts, returns canned info."""

    last_opts: dict = {}

    def __init__(self, opts):
        self.opts = opts
        FakeYoutubeDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=True):
        if "outtmpl" not in self.opts:
            # A metadata-only call (fetch_metadata's shape, e.g. TRANSCRIPT_SOURCE=whisper).
            return {"id": TEST_VIDEO_ID, "title": TEST_TITLE, "duration": TEST_DURATION}
        if "writesubtitles" not in self.opts:
            # download_audio's call shape.
            out_dir = Path(self.opts["outtmpl"]).parent
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{TEST_VIDEO_ID}.m4a").write_bytes(b"fake audio")
            return {"id": TEST_VIDEO_ID, "title": TEST_TITLE, "ext": "m4a"}
        captions_dir = Path(self.opts["outtmpl"]).parent
        captions_dir.mkdir(parents=True, exist_ok=True)
        caption_file = captions_dir / f"{TEST_VIDEO_ID}.en.vtt"
        caption_file.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello.\n")
        return {
            "id": TEST_VIDEO_ID,
            "title": TEST_TITLE,
            "duration": TEST_DURATION,
            "requested_subtitles": {
                "en": {"filepath": str(caption_file)},
            },
        }


class FakeYoutubeDLNoCaptions(FakeYoutubeDL):
    """Simulates a video with no captions in the requested language. Real
    yt-dlp always returns a full info dict (id/title/duration/ext/etc.)
    regardless of which options were requested -- this fake mirrors that
    so it works whether fetch_video's auto-fallback reuses it for the
    initial captions probe or the subsequent audio download."""

    def extract_info(self, url, download=True):
        if "outtmpl" in self.opts and "writesubtitles" not in self.opts:
            # download_audio's call shape.
            out_dir = Path(self.opts["outtmpl"]).parent
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{TEST_VIDEO_ID}.m4a").write_bytes(b"fake audio")
            return {"id": TEST_VIDEO_ID, "title": TEST_TITLE, "ext": "m4a"}
        return {
            "id": TEST_VIDEO_ID,
            "title": TEST_TITLE,
            "duration": TEST_DURATION,
            "ext": "m4a",
            "requested_subtitles": None,
        }


def test_fetch_video_returns_metadata_and_captions_path(tmp_path):
    captions_dir = tmp_path / "captions"

    video = fetch_video(TEST_URL, captions_dir, ydl_factory=FakeYoutubeDL)

    assert isinstance(video, VideoInfo)
    assert video.video_id == TEST_VIDEO_ID
    assert video.title == TEST_TITLE
    assert video.duration_seconds == TEST_DURATION
    assert video.url == TEST_URL
    assert Path(video.captions_path).exists()
    assert Path(video.captions_path).read_text().startswith("WEBVTT")


def test_fetch_video_never_downloads_video_file(tmp_path):
    fetch_video(TEST_URL, tmp_path / "captions", ydl_factory=FakeYoutubeDL)

    assert FakeYoutubeDL.last_opts["skip_download"] is True
    assert FakeYoutubeDL.last_opts["writesubtitles"] is True


def test_fetch_video_raises_when_no_captions(tmp_path):
    with pytest.raises(CaptionsUnavailableError):
        fetch_video(
            TEST_URL,
            tmp_path / "captions",
            ydl_factory=FakeYoutubeDLNoCaptions,
            transcript_source="captions",
        )


class FakeAudioDownloadYDL:
    """Stands in for yt_dlp.YoutubeDL doing an audio-only download."""

    last_opts: dict = {}

    def __init__(self, opts):
        self.opts = opts
        FakeAudioDownloadYDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=True):
        out_dir = Path(self.opts["outtmpl"]).parent
        out_dir.mkdir(parents=True, exist_ok=True)
        audio_file = out_dir / f"{TEST_VIDEO_ID}.m4a"
        audio_file.write_bytes(b"fake audio")
        return {"id": TEST_VIDEO_ID, "ext": "m4a"}


def test_download_audio_returns_the_downloaded_file_path(tmp_path):
    audio_path = download_audio(TEST_URL, tmp_path / "audio", ydl_factory=FakeAudioDownloadYDL)

    assert audio_path.exists()
    assert audio_path.name == f"{TEST_VIDEO_ID}.m4a"


def test_download_audio_never_requests_the_video_stream(tmp_path):
    download_audio(TEST_URL, tmp_path / "audio", ydl_factory=FakeAudioDownloadYDL)

    assert FakeAudioDownloadYDL.last_opts["format"] == "bestaudio/best"


def _fake_whisper_transcribe_writes_vtt(audio_path, vtt_path):
    vtt_path = Path(vtt_path)
    vtt_path.parent.mkdir(parents=True, exist_ok=True)
    vtt_path.write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nWhisper-transcribed text.\n",
        encoding="utf-8",
    )
    return vtt_path


def test_fetch_video_falls_back_to_whisper_when_captions_missing_and_source_is_auto(tmp_path):
    """sprints/v11 Task: TRANSCRIPT_SOURCE=auto (root AGENTS.md's documented
    default) falls back to Whisper instead of raising when a video has no
    captions -- this is the real bug found live (GAe5oB742dw has no
    English captions and the pipeline failed outright, despite AGENTS.md
    documenting exactly this fallback)."""
    captions_dir = tmp_path / "captions"

    video = fetch_video(
        TEST_URL,
        captions_dir,
        ydl_factory=FakeYoutubeDLNoCaptions,
        transcript_source="auto",
        whisper_transcribe=_fake_whisper_transcribe_writes_vtt,
    )

    assert video.video_id == TEST_VIDEO_ID
    assert video.title == TEST_TITLE
    assert Path(video.captions_path).exists()
    assert "Whisper-transcribed text." in Path(video.captions_path).read_text(encoding="utf-8")


def test_fetch_video_auto_prefers_real_captions_over_whisper_when_available(tmp_path):
    """The Whisper fallback only triggers when captions are genuinely
    missing -- captions stay the free/instant default whenever they exist,
    per root AGENTS.md's "Captions are free and instant" rationale."""
    whisper_calls = []

    def spy_whisper_transcribe(audio_path, vtt_path):
        whisper_calls.append((audio_path, vtt_path))
        return _fake_whisper_transcribe_writes_vtt(audio_path, vtt_path)

    video = fetch_video(
        TEST_URL,
        tmp_path / "captions",
        ydl_factory=FakeYoutubeDL,
        transcript_source="auto",
        whisper_transcribe=spy_whisper_transcribe,
    )

    assert whisper_calls == []
    assert "Whisper-transcribed text." not in Path(video.captions_path).read_text(
        encoding="utf-8"
    )


def test_fetch_video_whisper_mode_skips_the_captions_attempt_entirely(tmp_path):
    """TRANSCRIPT_SOURCE=whisper forces Whisper even when captions exist --
    fetch_video must not even attempt the captions request in this mode."""
    video = fetch_video(
        TEST_URL,
        tmp_path / "captions",
        ydl_factory=FakeYoutubeDL,  # would succeed with real captions if tried
        transcript_source="whisper",
        whisper_transcribe=_fake_whisper_transcribe_writes_vtt,
    )

    assert "Whisper-transcribed text." in Path(video.captions_path).read_text(encoding="utf-8")


def test_fetch_video_whisper_fallback_deletes_the_downloaded_audio_file(tmp_path, monkeypatch):
    """root AGENTS.md: no video/audio file is ever kept around -- the
    Whisper fallback's temporary audio download must be deleted once
    transcribed, same "stream mode, no file saved" guarantee."""
    import app.youtube as youtube_module

    downloaded_paths = []

    def spy_download_audio(url, output_dir, ydl_factory=None):
        path = Path(output_dir) / f"{TEST_VIDEO_ID}.m4a"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake audio")
        downloaded_paths.append(path)
        return path

    monkeypatch.setattr(youtube_module, "download_audio", spy_download_audio)

    fetch_video(
        TEST_URL,
        tmp_path / "captions",
        ydl_factory=FakeYoutubeDLNoCaptions,
        transcript_source="auto",
        whisper_transcribe=_fake_whisper_transcribe_writes_vtt,
    )

    assert len(downloaded_paths) == 1
    assert not downloaded_paths[0].exists()


class FakeMetadataYDL:
    """Stands in for yt_dlp.YoutubeDL for a metadata-only (no download) call."""

    last_opts: dict = {}

    def __init__(self, opts):
        self.opts = opts
        FakeMetadataYDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=False):
        assert download is False
        return {"id": TEST_VIDEO_ID, "title": TEST_TITLE, "duration": TEST_DURATION}


def test_fetch_metadata_returns_title_duration_id():
    metadata = fetch_metadata(TEST_URL, ydl_factory=FakeMetadataYDL)

    assert isinstance(metadata, VideoMetadata)
    assert metadata.video_id == TEST_VIDEO_ID
    assert metadata.title == TEST_TITLE
    assert metadata.duration_seconds == TEST_DURATION


def test_fetch_metadata_never_downloads_anything():
    fetch_metadata(TEST_URL, ydl_factory=FakeMetadataYDL)

    assert FakeMetadataYDL.last_opts["skip_download"] is True
    assert "writesubtitles" not in FakeMetadataYDL.last_opts


TEST_PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLfakeplaylist"


class FakePlaylistYDL:
    """Stands in for yt_dlp.YoutubeDL doing a flat playlist extraction."""

    last_opts: dict = {}

    def __init__(self, opts):
        self.opts = opts
        FakePlaylistYDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=False):
        assert download is False
        return {
            "id": "PLfakeplaylist",
            "title": "Fake Playlist",
            "entries": [
                {"id": "vid1", "title": "First Video", "url": "vid1"},
                {"id": "vid2", "title": "Second Video", "url": "vid2"},
                {"id": "vid3", "title": "Third Video", "url": "vid3"},
            ],
        }


class FakePlaylistYDLWithGap(FakePlaylistYDL):
    """Simulates a private/deleted playlist entry (yt-dlp yields None for it)."""

    def extract_info(self, url, download=False):
        return {
            "id": "PLfakeplaylist",
            "title": "Fake Playlist",
            "entries": [
                {"id": "vid1", "title": "First Video", "url": "vid1"},
                None,
                {"id": "vid3", "title": "Third Video", "url": "vid3"},
            ],
        }


class FakeSingleVideoYDL:
    """Flat extraction of a plain (non-playlist) video URL: no 'entries' key."""

    last_opts: dict = {}

    def __init__(self, opts):
        self.opts = opts
        FakeSingleVideoYDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=False):
        return {"id": TEST_VIDEO_ID, "title": TEST_TITLE}


def test_list_playlist_videos_returns_ordered_entries():
    videos = list_playlist_videos(TEST_PLAYLIST_URL, ydl_factory=FakePlaylistYDL)

    assert videos == [
        PlaylistEntry(
            video_id="vid1",
            title="First Video",
            url="https://www.youtube.com/watch?v=vid1",
            playlist_index=1,
        ),
        PlaylistEntry(
            video_id="vid2",
            title="Second Video",
            url="https://www.youtube.com/watch?v=vid2",
            playlist_index=2,
        ),
        PlaylistEntry(
            video_id="vid3",
            title="Third Video",
            url="https://www.youtube.com/watch?v=vid3",
            playlist_index=3,
        ),
    ]


def test_list_playlist_videos_skips_none_entries_but_keeps_order():
    videos = list_playlist_videos(TEST_PLAYLIST_URL, ydl_factory=FakePlaylistYDLWithGap)

    assert [video.video_id for video in videos] == ["vid1", "vid3"]
    assert [video.playlist_index for video in videos] == [1, 2]


def test_list_playlist_videos_uses_flat_extraction():
    list_playlist_videos(TEST_PLAYLIST_URL, ydl_factory=FakePlaylistYDL)

    assert FakePlaylistYDL.last_opts["extract_flat"] is True
    assert FakePlaylistYDL.last_opts["skip_download"] is True


def test_list_playlist_videos_single_video_returns_list_of_one():
    videos = list_playlist_videos(TEST_URL, ydl_factory=FakeSingleVideoYDL)

    assert videos == [
        PlaylistEntry(
            video_id=TEST_VIDEO_ID,
            title=TEST_TITLE,
            url=f"https://www.youtube.com/watch?v={TEST_VIDEO_ID}",
            playlist_index=1,
        )
    ]


TEST_WATCH_WITH_LIST_URL = (
    "https://www.youtube.com/watch?v=O8KrViWNhOM&list=PLfakeplaylist&index=3"
)


class FakeRedirectingPlaylistYDL:
    """Simulates a real yt-dlp quirk: a flat extraction of a
    "watch?v=...&list=...&index=..." URL resolves to a `_type: "url"`
    pointer at the playlist tab (id = the *playlist* id, not a video id)
    instead of directly to the playlist's entries. The real entries only
    show up once that pointer's "url" is itself extracted.
    """

    last_opts: dict = {}
    call_count = 0

    def __init__(self, opts):
        self.opts = opts
        FakeRedirectingPlaylistYDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=False):
        assert download is False
        FakeRedirectingPlaylistYDL.call_count += 1
        if url == TEST_WATCH_WITH_LIST_URL:
            return {
                "id": "PLfakeplaylist",
                "title": "Fake Playlist",
                "_type": "url",
                "url": "https://www.youtube.com/playlist?list=PLfakeplaylist",
            }
        return {
            "id": "PLfakeplaylist",
            "title": "Fake Playlist",
            "entries": [
                {"id": "vid1", "title": "First Video", "url": "vid1"},
                {"id": "vid2", "title": "Second Video", "url": "vid2"},
            ],
        }


def test_list_playlist_videos_follows_url_pointer_to_real_entries():
    videos = list_playlist_videos(
        TEST_WATCH_WITH_LIST_URL, ydl_factory=FakeRedirectingPlaylistYDL
    )

    assert [video.video_id for video in videos] == ["vid1", "vid2"]
    assert FakeRedirectingPlaylistYDL.call_count == 2


class FakeStreamYDL:
    """Stands in for yt_dlp.YoutubeDL resolving a direct stream URL."""

    last_opts: dict = {}

    def __init__(self, opts):
        self.opts = opts
        FakeStreamYDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=False):
        assert download is False
        return {"id": TEST_VIDEO_ID, "url": "https://videoplayback.example.com/stream.mp4"}


class FakeStreamYDLRequestedFormats:
    """Simulates an extractor that only populates requested_formats, not url."""

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=False):
        return {
            "id": TEST_VIDEO_ID,
            "requested_formats": [{"url": "https://videoplayback.example.com/fallback.mp4"}],
        }


class FakeStreamYDLNoUrl:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=False):
        return {"id": TEST_VIDEO_ID}


def test_get_stream_url_returns_direct_url_without_downloading():
    stream_url = get_stream_url(TEST_URL, ydl_factory=FakeStreamYDL)

    assert stream_url == "https://videoplayback.example.com/stream.mp4"
    assert FakeStreamYDL.last_opts["skip_download"] is True


def test_get_stream_url_falls_back_to_requested_formats():
    stream_url = get_stream_url(TEST_URL, ydl_factory=FakeStreamYDLRequestedFormats)

    assert stream_url == "https://videoplayback.example.com/fallback.mp4"


def test_get_stream_url_raises_when_no_url_resolvable():
    with pytest.raises(RuntimeError):
        get_stream_url(TEST_URL, ydl_factory=FakeStreamYDLNoUrl)


class FakeChunkDownloadYDL:
    """Stands in for yt_dlp.YoutubeDL doing a download_ranges-scoped download."""

    last_opts: dict = {}

    def __init__(self, opts):
        self.opts = opts
        FakeChunkDownloadYDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def download(self, urls):
        outtmpl = self.opts["outtmpl"]
        path = Path(outtmpl.replace("%(ext)s", "mp4"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-chunk-video")


def test_download_chunk_video_writes_local_file_and_scopes_range(tmp_path):
    video_path = download_chunk_video(
        TEST_URL, 1800.0, 3600.0, tmp_path, ydl_factory=FakeChunkDownloadYDL
    )

    assert video_path.exists()
    assert video_path.read_bytes() == b"fake-chunk-video"

    ranges = FakeChunkDownloadYDL.last_opts["download_ranges"](None, None)
    assert ranges == [{"start_time": 1800.0, "end_time": 3600.0}]
    assert FakeChunkDownloadYDL.last_opts["force_keyframes_at_cuts"] is True
