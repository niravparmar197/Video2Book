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
    """Simulates a video with no captions in the requested language."""

    def extract_info(self, url, download=True):
        return {
            "id": TEST_VIDEO_ID,
            "title": TEST_TITLE,
            "duration": TEST_DURATION,
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
        fetch_video(TEST_URL, tmp_path / "captions", ydl_factory=FakeYoutubeDLNoCaptions)


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
