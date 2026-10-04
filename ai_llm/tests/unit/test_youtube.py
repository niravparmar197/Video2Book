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
    VideoUnavailableError,
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


def test_fetch_video_reuses_cached_whisper_transcript_for_a_repeat_video(tmp_path):
    """The same video submitted for a second book must not re-download
    audio or re-run Whisper (2.5-6 min on CPU) -- it reuses the shared
    transcript cache written by the first run."""
    whisper_calls = []

    def spy_whisper(audio_path, vtt_path):
        whisper_calls.append(audio_path)
        return _fake_whisper_transcribe_writes_vtt(audio_path, vtt_path)

    first = fetch_video(
        TEST_URL, tmp_path / "book1" / "captions", ydl_factory=FakeYoutubeDLNoCaptions,
        transcript_source="auto", whisper_transcribe=spy_whisper,
    )
    second = fetch_video(
        TEST_URL, tmp_path / "book2" / "captions", ydl_factory=FakeYoutubeDLNoCaptions,
        transcript_source="auto", whisper_transcribe=spy_whisper,
    )

    assert len(whisper_calls) == 1
    assert Path(second.captions_path).read_text(encoding="utf-8") == Path(
        first.captions_path
    ).read_text(encoding="utf-8")


def test_fetch_video_whisper_cache_is_keyed_by_video_id(tmp_path):
    from app.youtube import transcript_cache_path

    cached = transcript_cache_path("some-other-video")
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nWrong video.\n", encoding="utf-8")

    video = fetch_video(
        TEST_URL, tmp_path / "captions", ydl_factory=FakeYoutubeDLNoCaptions,
        transcript_source="auto", whisper_transcribe=_fake_whisper_transcribe_writes_vtt,
    )

    assert "Wrong video." not in Path(video.captions_path).read_text(encoding="utf-8")


def test_list_playlist_videos_turns_a_members_only_video_into_a_readable_error():
    import yt_dlp

    class _BlockedYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            raise yt_dlp.utils.DownloadError(
                "ERROR: [youtube] WZjSFNPS9Lo: This video is available to this channel's members"
            )

    with pytest.raises(VideoUnavailableError) as raised:
        list_playlist_videos("https://www.youtube.com/watch?v=WZjSFNPS9Lo", _BlockedYDL)

    assert str(raised.value) == "This video is available to this channel's members"


class _RateLimitedYDL:
    """Every caption download answers HTTP 429; metadata-only calls succeed."""

    calls = 0

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        import yt_dlp

        if self.opts.get("writesubtitles"):
            type(self).calls += 1
            raise yt_dlp.utils.DownloadError(
                "ERROR: Unable to download video subtitles for 'en': HTTP Error 429: Too Many Requests"
            )
        return {"id": "vid429", "title": "Rate limited", "duration": 300}


def test_fetch_video_goes_straight_to_whisper_on_a_429_when_the_video_has_no_other_track(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("TRANSCRIPT_CACHE_DIR", str(tmp_path / "cache"))
    _RateLimitedYDL.calls = 0
    sleeps = []
    transcribed = []
    monkeypatch.setattr(
        "app.youtube.download_audio", lambda url, output_dir, ydl_factory: tmp_path / "a.m4a"
    )
    (tmp_path / "a.m4a").write_bytes(b"x")

    def fake_whisper(audio_path, vtt_path):
        transcribed.append(str(vtt_path))
        Path(vtt_path).write_text("WEBVTT\n", encoding="utf-8")
        return Path(vtt_path)

    info = fetch_video(
        "https://www.youtube.com/watch?v=vid429",
        tmp_path / "captions",
        ydl_factory=_RateLimitedYDL,
        transcript_source="auto",
        whisper_transcribe=fake_whisper,
        sleep=sleeps.append,
    )

    assert _RateLimitedYDL.calls == 1  # one try, no 10s/30s waiting on the translated track
    assert sleeps == []
    assert transcribed and info.video_id == "vid429" and info.title == "Rate limited"
    assert Path(info.captions_path).exists()


class _HindiVideoYDL:
    """A Hindi video: the English track is a rate-limited machine translation,
    the original hi-orig track downloads fine."""

    requested = []

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        import yt_dlp

        meta = {
            "id": "hindi1",
            "title": "History of Russia",
            "duration": 1647,
            "language": "hi",
            "automatic_captions": {"en": [{}], "hi-orig": [{}], "bn-orig": [{}]},
            "subtitles": {},
        }
        if not download:
            return meta
        track = self.opts["subtitleslangs"][0]
        type(self).requested.append(track)
        if track == "en":
            raise yt_dlp.utils.DownloadError("ERROR: HTTP Error 429: Too Many Requests")
        out = Path(self.opts["outtmpl"].replace("%(id)s", "hindi1").replace("%(ext)s", f"{track}.vtt"))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nनमस्ते\n", encoding="utf-8"
        )
        return meta


def test_fetch_video_uses_the_original_language_track_instead_of_waiting_or_whisper(tmp_path):
    _HindiVideoYDL.requested = []
    sleeps = []

    def whisper_must_not_run(audio_path, vtt_path):
        raise AssertionError("Whisper must not run when the original-language captions work")

    info = fetch_video(
        "https://www.youtube.com/watch?v=hindi1",
        tmp_path / "captions",
        ydl_factory=_HindiVideoYDL,
        transcript_source="auto",
        whisper_transcribe=whisper_must_not_run,
        sleep=sleeps.append,
    )

    assert _HindiVideoYDL.requested == ["en", "hi-orig"]
    assert sleeps == []
    assert info.video_id == "hindi1" and info.title == "History of Russia"
    assert info.captions_path.endswith("hindi1.hi-orig.vtt")
    assert "नमस्ते" in Path(info.captions_path).read_text(encoding="utf-8")


def test_fetch_video_captions_only_mode_raises_a_clear_error_on_persistent_429(tmp_path):
    with pytest.raises(CaptionsUnavailableError, match="rate-limiting"):
        fetch_video(
            "https://www.youtube.com/watch?v=vid429",
            tmp_path / "captions",
            ydl_factory=_RateLimitedYDL,
            transcript_source="captions",
            sleep=lambda seconds: None,
        )


class _RecordingYDL:
    seen = []

    def __init__(self, opts):
        type(self).seen.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        return {"id": "abc", "title": "T", "duration": 60}


def test_youtube_cookies_file_is_passed_to_every_yt_dlp_call(monkeypatch):
    monkeypatch.setenv("YOUTUBE_COOKIES_FILE", "C:/me/youtube_cookies.txt")
    monkeypatch.setenv("YOUTUBE_COOKIES_BROWSER", "firefox")  # the file wins
    _RecordingYDL.seen = []

    fetch_metadata("https://www.youtube.com/watch?v=abc", ydl_factory=_RecordingYDL)

    assert _RecordingYDL.seen[-1]["cookiefile"] == "C:/me/youtube_cookies.txt"
    assert "cookiesfrombrowser" not in _RecordingYDL.seen[-1]


def test_youtube_cookies_browser_is_used_when_no_file_is_set(monkeypatch):
    monkeypatch.setenv("YOUTUBE_COOKIES_BROWSER", "edge")
    _RecordingYDL.seen = []

    fetch_metadata("https://www.youtube.com/watch?v=abc", ydl_factory=_RecordingYDL)

    assert _RecordingYDL.seen[-1]["cookiesfrombrowser"] == ("edge",)


def test_no_cookies_configured_leaves_yt_dlp_options_unchanged():
    _RecordingYDL.seen = []

    fetch_metadata("https://www.youtube.com/watch?v=abc", ydl_factory=_RecordingYDL)

    assert "cookiefile" not in _RecordingYDL.seen[-1]
    assert "cookiesfrombrowser" not in _RecordingYDL.seen[-1]


class _NoNetworkYDL:
    def __init__(self, opts):
        raise AssertionError("a cached video must not contact YouTube")


def test_a_video_fetched_once_is_served_from_the_shared_cache_without_youtube(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRIPT_CACHE_DIR", str(tmp_path / "cache"))
    _HindiVideoYDL.requested = []
    first = fetch_video(
        "https://www.youtube.com/watch?v=hindi1", tmp_path / "book1", ydl_factory=_HindiVideoYDL,
        transcript_source="auto", sleep=lambda s: None,
    )

    second = fetch_video(
        "https://youtu.be/hindi1", tmp_path / "book2", ydl_factory=_NoNetworkYDL, transcript_source="auto"
    )
    metadata = fetch_metadata("https://www.youtube.com/watch?v=hindi1&t=29s", ydl_factory=_NoNetworkYDL)

    assert (second.video_id, second.title, second.duration_seconds) == ("hindi1", "History of Russia", 1647)
    assert Path(second.captions_path).parent == tmp_path / "book2"
    assert Path(second.captions_path).read_text(encoding="utf-8") == Path(first.captions_path).read_text(encoding="utf-8")
    assert metadata.title == "History of Russia" and metadata.duration_seconds == 1647


def test_a_cached_whisper_transcript_from_an_older_recipe_is_not_reused(tmp_path, monkeypatch):
    import json as json_module

    monkeypatch.setenv("TRANSCRIPT_CACHE_DIR", str(tmp_path / "cache"))
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "abcdefghijk.transcript.vtt").write_text("WEBVTT\n", encoding="utf-8")
    (cache / "abcdefghijk.meta.json").write_text(
        json_module.dumps({"title": "T", "duration_seconds": 60, "transcript_recipe": "base-old-v0"}),
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match="must not contact YouTube"):
        fetch_video(
            "https://www.youtube.com/watch?v=abcdefghijk", tmp_path / "b", ydl_factory=_NoNetworkYDL,
            transcript_source="auto",
        )


def test_every_yt_dlp_call_pauses_between_requests():
    _RecordingYDL.seen = []

    fetch_metadata("https://www.youtube.com/watch?v=zzzzzzzzzzz", ydl_factory=_RecordingYDL)

    assert _RecordingYDL.seen[-1]["sleep_interval_requests"] > 0


def test_a_cached_single_video_link_resolves_without_youtube(tmp_path, monkeypatch):
    import json as json_module

    monkeypatch.setenv("TRANSCRIPT_CACHE_DIR", str(tmp_path))
    (tmp_path / "abcdefghijk.meta.json").write_text(
        json_module.dumps({"title": "Cached", "duration_seconds": 60}), encoding="utf-8"
    )

    entries = list_playlist_videos("https://www.youtube.com/watch?v=abcdefghijk&t=29s", _NoNetworkYDL)

    assert [(e.video_id, e.title) for e in entries] == [("abcdefghijk", "Cached")]


def test_original_caption_tracks_match_a_regional_language_to_youtubes_track_names():
    from app.youtube import original_caption_tracks

    assert original_caption_tracks("en-US") == ["en-US-orig", "en-US", "en-orig", "en"]
    assert original_caption_tracks("hi") == ["hi-orig", "hi"]
    assert original_caption_tracks(None) == ["en-orig", "en"]


class _DubbedVideoYDL(_HindiVideoYDL):
    """An English talk with AI-dubbed audio: an -orig track for every dub
    language, Arabic listed first. The English track is rate-limited."""

    def extract_info(self, url, download=False):
        meta = super().extract_info(url, download=False) if not download else None
        if not download:
            return {
                **meta,
                "id": "dubbed1",
                "language": "en-US",
                "automatic_captions": {"ar-orig": [{}], "bn-orig": [{}], "en-orig": [{}], "en": [{}]},
            }
        track = self.opts["subtitleslangs"][0]
        type(self).requested.append(track)
        if track == "en":
            import yt_dlp

            raise yt_dlp.utils.DownloadError("ERROR: HTTP Error 429: Too Many Requests")
        out = Path(self.opts["outtmpl"].replace("%(id)s", "dubbed1").replace("%(ext)s", f"{track}.vtt"))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")
        return {"id": "dubbed1", "title": "Design Google Drive", "duration": 2657, "language": "en-US"}


def test_a_dubbed_video_uses_its_own_english_track_never_another_dub_language(tmp_path):
    _DubbedVideoYDL.requested = []

    info = fetch_video(
        "https://www.youtube.com/watch?v=dubbed1",
        tmp_path / "captions",
        ydl_factory=_DubbedVideoYDL,
        transcript_source="auto",
        sleep=lambda s: None,
    )

    assert _DubbedVideoYDL.requested == ["en", "en-orig"]
    assert info.captions_path.endswith("dubbed1.en-orig.vtt")
