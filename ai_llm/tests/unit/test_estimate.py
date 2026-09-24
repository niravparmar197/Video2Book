"""Unit tests for app.estimate — the --estimate cost/time output.

No real network or LLM calls: app.youtube.fetch_metadata is monkeypatched,
and a static source check guards against any LLM client creeping in here.
"""
import inspect

from app import estimate as estimate_module
from app.estimate import EstimateResult, estimate_playlist, estimate_video, print_estimate
from app.youtube import PlaylistEntry, VideoMetadata

TEST_URL = "https://www.youtube.com/watch?v=aircAruvnKk"


def _fake_metadata(url, **kwargs):
    return VideoMetadata(
        video_id="aircAruvnKk",
        title="But what is a neural network? | Deep learning chapter 1",
        duration_seconds=1163,  # ~19 minutes
    )


def _fake_single_video_playlist(url):
    return [
        PlaylistEntry(
            video_id="aircAruvnKk",
            title="But what is a neural network? | Deep learning chapter 1",
            url=url,
            playlist_index=1,
        )
    ]


def _fake_long_metadata(url, **kwargs):
    return VideoMetadata(video_id="longvid", title="Long Course", duration_seconds=90 * 60)


def test_estimate_video_single_chunk_under_30_minutes(monkeypatch):
    monkeypatch.setattr(estimate_module, "fetch_metadata", _fake_metadata)

    result = estimate_video(TEST_URL, chunk_minutes=30)

    assert isinstance(result, EstimateResult)
    assert result.video_id == "aircAruvnKk"
    assert result.chunk_count == 1
    assert result.estimated_input_tokens > 0
    assert result.estimated_output_tokens > 0
    assert result.estimated_total_tokens == (
        result.estimated_input_tokens + result.estimated_output_tokens
    )
    assert result.estimated_cost_usd == 0.0


def test_estimate_video_accounts_for_the_judge_call_per_chunk(monkeypatch):
    """sprints/v5 Task 8: topics + write + judge = 3 transcript-reading
    LLM calls per chunk, up from 2 pre-v5.
    """
    monkeypatch.setattr(estimate_module, "fetch_metadata", _fake_metadata)

    result = estimate_video(TEST_URL, chunk_minutes=30)

    assert estimate_module.LLM_CALLS_PER_CHUNK == 3
    duration_minutes = 1163 / 60
    transcript_tokens = int(
        duration_minutes * estimate_module.WORDS_PER_MINUTE * estimate_module.TOKENS_PER_WORD
    )
    assert result.estimated_input_tokens == transcript_tokens * 3


def test_estimate_video_multiple_chunks_for_90_minute_video(monkeypatch):
    monkeypatch.setattr(estimate_module, "fetch_metadata", _fake_long_metadata)

    result = estimate_video("https://example.com/long", chunk_minutes=30)

    assert result.chunk_count == 3


def test_estimate_video_uses_settings_chunk_minutes_by_default(monkeypatch):
    monkeypatch.setattr(estimate_module, "fetch_metadata", _fake_long_metadata)
    monkeypatch.setenv("CHUNK_MINUTES", "45")

    result = estimate_video("https://example.com/long")

    assert result.chunk_count == 2  # ceil(90 / 45)


def test_estimate_module_has_no_llm_client_wired_in():
    source = inspect.getsource(estimate_module)
    forbidden_tokens = [
        "openai",
        "ChatNVIDIA",
        "ChatGoogleGenerativeAI",
        "requests.post",
        "httpx.post",
        "langchain",
    ]
    for token in forbidden_tokens:
        assert token not in source, f"estimate.py must never call an LLM (found {token!r})"


def test_print_estimate_output(monkeypatch, capsys):
    monkeypatch.setattr(estimate_module, "fetch_metadata", _fake_metadata)
    monkeypatch.setattr(estimate_module, "list_playlist_videos", _fake_single_video_playlist)

    print_estimate(TEST_URL)

    captured = capsys.readouterr()
    out_lower = captured.out.lower()
    assert "aircaruvnkk" in out_lower
    assert "chunks" in out_lower
    assert "1" in captured.out
    assert "token" in out_lower
    assert "$0.00" in captured.out


def _fake_playlist_two_videos(url):
    return [
        PlaylistEntry(
            video_id="vid1",
            title="Video One",
            url="https://www.youtube.com/watch?v=vid1",
            playlist_index=1,
        ),
        PlaylistEntry(
            video_id="vid2",
            title="Video Two",
            url="https://www.youtube.com/watch?v=vid2",
            playlist_index=2,
        ),
    ]


def _fake_metadata_by_video_id(url, **kwargs):
    video_id = url.rsplit("=", 1)[-1]
    durations = {"vid1": 600, "vid2": 1800}  # 10 min, 30 min
    return VideoMetadata(
        video_id=video_id, title=f"Title {video_id}", duration_seconds=durations[video_id]
    )


def test_estimate_playlist_sums_per_video_estimates(monkeypatch):
    monkeypatch.setattr(estimate_module, "list_playlist_videos", _fake_playlist_two_videos)
    monkeypatch.setattr(estimate_module, "fetch_metadata", _fake_metadata_by_video_id)

    results = estimate_playlist(
        "https://www.youtube.com/playlist?list=PLfake", chunk_minutes=30
    )

    assert [r.video_id for r in results] == ["vid1", "vid2"]

    total_tokens = sum(r.estimated_total_tokens for r in results)
    total_chunks = sum(r.chunk_count for r in results)
    assert total_tokens == results[0].estimated_total_tokens + results[1].estimated_total_tokens
    assert total_chunks == results[0].chunk_count + results[1].chunk_count


def test_print_estimate_playlist_output_includes_totals(monkeypatch, capsys):
    monkeypatch.setattr(estimate_module, "list_playlist_videos", _fake_playlist_two_videos)
    monkeypatch.setattr(estimate_module, "fetch_metadata", _fake_metadata_by_video_id)

    print_estimate("https://www.youtube.com/playlist?list=PLfake")

    captured = capsys.readouterr()
    out_lower = captured.out.lower()
    assert "vid1" in out_lower
    assert "vid2" in out_lower
    assert "total chunks" in out_lower
    assert "total tokens" in out_lower
    assert "total cost" in out_lower
    assert "$0.00" in captured.out


def test_print_estimate_notes_screenshots_skipped_for_captions_only(monkeypatch, capsys):
    monkeypatch.setattr(estimate_module, "fetch_metadata", _fake_metadata)
    monkeypatch.setattr(estimate_module, "list_playlist_videos", _fake_single_video_playlist)
    monkeypatch.setenv("VIDEO_MODE", "captions_only")

    print_estimate(TEST_URL)

    captured = capsys.readouterr()
    assert "skipped" in captured.out.lower()
    assert "captions_only" in captured.out


def test_print_estimate_warns_when_total_hours_exceed_max_book_hours(monkeypatch, capsys):
    monkeypatch.setattr(estimate_module, "fetch_metadata", _fake_long_metadata)
    monkeypatch.setattr(estimate_module, "list_playlist_videos", _fake_single_video_playlist)
    monkeypatch.setenv("MAX_BOOK_HOURS", "1")  # video is 90 min > 1h

    print_estimate(TEST_URL)

    captured = capsys.readouterr()
    assert "warning" in captured.out.lower()
    assert "max_book_hours" in captured.out.lower()
    assert "--force" in captured.out


def test_print_estimate_no_warning_when_under_max_book_hours(monkeypatch, capsys):
    monkeypatch.setattr(estimate_module, "fetch_metadata", _fake_metadata)
    monkeypatch.setattr(estimate_module, "list_playlist_videos", _fake_single_video_playlist)
    monkeypatch.setenv("MAX_BOOK_HOURS", "30")

    print_estimate(TEST_URL)

    captured = capsys.readouterr()
    assert "warning" not in captured.out.lower()


def test_print_estimate_warns_when_total_cost_exceeds_max_book_cost_usd(monkeypatch, capsys):
    monkeypatch.setattr(estimate_module, "fetch_metadata", _fake_metadata)
    monkeypatch.setattr(estimate_module, "list_playlist_videos", _fake_single_video_playlist)
    monkeypatch.setenv("MAX_BOOK_COST_USD", "0")

    def fake_estimate_playlist(url, chunk_minutes=None):
        result = estimate_module.estimate_video(url, chunk_minutes=chunk_minutes)
        return [
            EstimateResult(
                video_id=result.video_id,
                title=result.title,
                duration_seconds=result.duration_seconds,
                chunk_count=result.chunk_count,
                estimated_input_tokens=result.estimated_input_tokens,
                estimated_output_tokens=result.estimated_output_tokens,
                estimated_total_tokens=result.estimated_total_tokens,
                estimated_cost_usd=5.0,
            )
        ]

    monkeypatch.setattr(estimate_module, "estimate_playlist", fake_estimate_playlist)

    print_estimate(TEST_URL)

    captured = capsys.readouterr()
    assert "warning" in captured.out.lower()
    assert "max_book_cost_usd" in captured.out.lower()


def test_print_estimate_notes_screenshots_will_be_taken_for_stream_mode(monkeypatch, capsys):
    monkeypatch.setattr(estimate_module, "fetch_metadata", _fake_metadata)
    monkeypatch.setattr(estimate_module, "list_playlist_videos", _fake_single_video_playlist)
    monkeypatch.setenv("VIDEO_MODE", "stream")

    print_estimate(TEST_URL)

    captured = capsys.readouterr()
    assert "will be taken" in captured.out.lower()
    assert "skipped" not in captured.out.lower()
