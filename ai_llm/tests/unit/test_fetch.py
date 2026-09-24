"""Unit tests for app.nodes.fetch — the fetch pipeline node.

No real network calls: app.youtube.fetch_video is monkeypatched.
"""
import json
from pathlib import Path

from app.nodes import fetch as fetch_node
from app.youtube import PlaylistEntry, VideoInfo

TEST_URL = "https://www.youtube.com/watch?v=aircAruvnKk"


def _fake_video_info(url, captions_dir, **kwargs):
    captions_dir = Path(captions_dir)
    captions_dir.mkdir(parents=True, exist_ok=True)
    caption_file = captions_dir / "aircAruvnKk.en.vtt"
    caption_file.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello.\n")
    return VideoInfo(
        video_id="aircAruvnKk",
        title="But what is a neural network? | Deep learning chapter 1",
        duration_seconds=1163,
        url=url,
        captions_path=str(caption_file),
    )


def test_run_fetch_writes_videos_json(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_node, "fetch_video", _fake_video_info)

    output_dir = tmp_path / "output" / "some-book"
    fetch_node.run_fetch(TEST_URL, output_dir)

    videos_json_path = output_dir / "videos.json"
    assert videos_json_path.exists()

    payload = json.loads(videos_json_path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["video_id"] == "aircAruvnKk"
    assert payload[0]["title"] == "But what is a neural network? | Deep learning chapter 1"
    assert payload[0]["duration_seconds"] == 1163
    assert payload[0]["url"] == TEST_URL
    assert Path(payload[0]["captions_path"]).exists()


def test_run_fetch_returns_video_info(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_node, "fetch_video", _fake_video_info)

    output_dir = tmp_path / "output" / "some-book"
    video = fetch_node.run_fetch(TEST_URL, output_dir)

    assert video.video_id == "aircAruvnKk"
    assert video.captions_path is not None


TEST_PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLfakeplaylist"


def _fake_playlist_entries(url):
    return [
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
    ]


def _fake_fetch_video_by_url(url, captions_dir, **kwargs):
    captions_dir = Path(captions_dir)
    captions_dir.mkdir(parents=True, exist_ok=True)
    video_id = url.rsplit("=", 1)[-1]
    caption_file = captions_dir / f"{video_id}.en.vtt"
    caption_file.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello.\n")
    return VideoInfo(
        video_id=video_id,
        title=f"Title for {video_id}",
        duration_seconds=100,
        url=url,
        captions_path=str(caption_file),
    )


def test_run_fetch_playlist_writes_one_entry_per_video(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_node, "list_playlist_videos", _fake_playlist_entries)
    monkeypatch.setattr(fetch_node, "fetch_video", _fake_fetch_video_by_url)

    output_dir = tmp_path / "output" / "some-book"
    videos = fetch_node.run_fetch_playlist(TEST_PLAYLIST_URL, output_dir)

    assert [video.video_id for video in videos] == ["vid1", "vid2"]
    assert [video.playlist_index for video in videos] == [1, 2]

    videos_json_path = output_dir / "videos.json"
    assert videos_json_path.exists()
    payload = json.loads(videos_json_path.read_text(encoding="utf-8"))

    assert len(payload) == 2
    assert payload[0]["video_id"] == "vid1"
    assert payload[0]["playlist_index"] == 1
    assert Path(payload[0]["captions_path"]).exists()
    assert payload[1]["video_id"] == "vid2"
    assert payload[1]["playlist_index"] == 2
    assert Path(payload[1]["captions_path"]).exists()


def test_run_fetch_playlist_single_video_returns_list_of_one(tmp_path, monkeypatch):
    def fake_single(url):
        return [PlaylistEntry(video_id="aircAruvnKk", title="Solo", url=url, playlist_index=1)]

    monkeypatch.setattr(fetch_node, "list_playlist_videos", fake_single)
    monkeypatch.setattr(fetch_node, "fetch_video", _fake_video_info)

    output_dir = tmp_path / "output" / "some-book"
    videos = fetch_node.run_fetch_playlist(TEST_URL, output_dir)

    assert len(videos) == 1
    assert videos[0].video_id == "aircAruvnKk"
    assert videos[0].playlist_index == 1
