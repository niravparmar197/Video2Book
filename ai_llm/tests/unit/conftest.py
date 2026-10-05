"""Shared pytest fixtures for the unit test suite.

VIDEO_MODE defaults to captions_only for every unit test: graph.py's
_frames_node (sprints/v4) is real ffmpeg/yt-dlp work that must never run in
a unit test (root AGENTS.md: never call a real network/API in a unit
test). Tests that specifically exercise the frames node override this
locally with monkeypatch.setenv("VIDEO_MODE", "stream").

app.nodes.verify.call_writer defaults to an always-passing stub judge
response for every unit test: write.py's refine loop (sprints/v5) calls
run_verify() internally, which is a *separate* real LLM call from
write.py's own call_writer -- a test that only mocks write_module's
call_writer would otherwise leave the judge call unmocked and hit a real
API. Tests that specifically exercise the refine loop override this
locally with monkeypatch.setattr(verify_module, "call_writer", ...).

app.nodes.book_pass.call_writer defaults to an inert "[]" response for the
same reason: graph.py's book_pass node (sprints/v6) calls
run_glossary() internally, each a
*separate* real LLM call from write.py's/topics.py's own call_writer. "[]"
degrades glossary/index-terms to empty (harmless).
Tests that specifically exercise book_pass override this locally.

app.llm._last_call_at (sprints/v7 proactive rate-limit pacing) is reset
before every unit test: it's process-wide, mutable, module-level state, so
without a reset a fast-running earlier test could leave a provider's "last
call" timestamp close enough to "now" that a later test's call_writer call
triggers a real (or real-if-unmocked) pacing sleep -- test isolation, not a
behavior test in itself.

TRANSCRIPT_SOURCE defaults to "captions" for every unit test, same
rationale as VIDEO_MODE above: the real .env default is "auto" (sprints/
v11's Whisper fallback), and app.youtube.fetch_video's default
whisper_transcribe callable loads a real faster-whisper model on first
use -- without this override, any existing/future test whose fake
ydl_factory reports no captions would silently trigger a real, heavy model
load instead of raising CaptionsUnavailableError as originally intended.
Tests that specifically exercise the Whisper fallback override this
locally with monkeypatch.setenv("TRANSCRIPT_SOURCE", "auto"/"whisper") or
pass transcript_source= explicitly.
"""
import json

import pytest

# Every setting app.config.load_settings() reads. Defined first so it runs
# before the fixtures below that set specific values.
_SETTING_ENV_VARS = (
    "VIDEO_MODE", "CHUNK_MINUTES", "FRAMES_DOWNLOAD_MAX_MINUTES", "MAX_SCREENSHOTS_PER_CHUNK",
    "TRANSCRIPT_SOURCE", "VIDEO_GENRE", "LLM_PROVIDER", "LLM_FALLBACK_PROVIDER", "BOOK_ORDER", "REVIEW_OUTLINE",
    "PASS_SCORE", "MAX_REFINE_ATTEMPTS", "LLM_PARALLEL_CALLS", "MAX_BOOK_HOURS",
    "MAX_BOOK_COST_USD", "VOLUME_HOURS", "YOUTUBE_COOKIES_FILE", "YOUTUBE_COOKIES_BROWSER",
    "SCREENSHOT_REVIEW",
)


@pytest.fixture(autouse=True)
def _isolated_from_developer_dotenv(monkeypatch):
    """Tests see the code's defaults, never the developer's ai_llm/.env.
    Without this the suite silently depended on whatever .env said (it
    passed only while .env happened to set MAX_REFINE_ATTEMPTS=3)."""
    monkeypatch.setattr("app.config.load_dotenv", lambda *args, **kwargs: None)
    for name in _SETTING_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    # A traced function (app.llm._post_vision) must never send a test run to LangSmith.
    for name in ("LANGSMITH_TRACING", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING_V2"):
        monkeypatch.delenv(name, raising=False)
    # Stream-mode tests stub the stream path; the short-video download path
    # would otherwise call real YouTube. Tests of that path set it themselves.
    monkeypatch.setenv("FRAMES_DOWNLOAD_MAX_MINUTES", "0")


@pytest.fixture(autouse=True)
def _default_captions_only_video_mode(monkeypatch, _isolated_from_developer_dotenv):
    monkeypatch.setenv("VIDEO_MODE", "captions_only")


@pytest.fixture(autouse=True)
def _default_captions_transcript_source(monkeypatch, _isolated_from_developer_dotenv):
    monkeypatch.setenv("TRANSCRIPT_SOURCE", "captions")


@pytest.fixture(autouse=True)
def _isolated_transcript_cache(monkeypatch, tmp_path):
    """The real shared Whisper-transcript cache lives under ai_llm/output/;
    each test gets its own empty one so a fake transcript from one test is
    never served to another (or written into the real cache)."""
    monkeypatch.setenv("TRANSCRIPT_CACHE_DIR", str(tmp_path / "_transcript_cache"))


@pytest.fixture(autouse=True)
def _default_passing_judge(monkeypatch):
    from app.nodes import verify as verify_module

    monkeypatch.setattr(
        verify_module,
        "call_writer",
        lambda prompt, **kw: json.dumps({"score": 10, "feedback": "looks good"}),
    )


@pytest.fixture(autouse=True)
def _default_inert_book_pass(monkeypatch):
    from app.nodes import book_pass as book_pass_module

    monkeypatch.setattr(book_pass_module, "call_writer", lambda prompt, **kw: "[]")


@pytest.fixture(autouse=True)
def _no_stream_url_lookups(monkeypatch):
    """run_frames also grabs a chunk's final frame from the video; resolving
    a stream URL is a real YouTube request, which no unit test may make.
    Tests of that path stub it themselves."""
    from app.nodes import frames as frames_module

    def no_network(url):
        raise RuntimeError("no YouTube requests in unit tests")

    monkeypatch.setattr(frames_module, "_get_stream_url", no_network)


@pytest.fixture(autouse=True)
def _default_lecture_genre(monkeypatch):
    """The topics node also decides the book's genre with one LLM call; tests
    get "lecture" (the study-notes style) unless they override it."""
    from app.nodes import genre as genre_module

    monkeypatch.setattr(genre_module, "call_writer", lambda prompt, **kw: "lecture")


@pytest.fixture(autouse=True)
def _reset_llm_rate_limit_pacing_state(monkeypatch):
    from app import llm as llm_module

    monkeypatch.setattr(llm_module, "_last_call_at", {})


@pytest.fixture(autouse=True)
def _no_closing_parts_check(monkeypatch):
    """write.py fails a lecture chapter that lacks 3+ Key Takeaways and a
    Test Yourself quiz. Most tests' fake writers return a one-line note, so
    the check is off by default; test_write.py tests it directly."""
    from app.nodes import write as write_module

    monkeypatch.setattr(write_module, "missing_parts", lambda notes, genre: [])


@pytest.fixture(autouse=True)
def _no_vision_calls(monkeypatch):
    """run_frames asks the vision model about each kept screenshot -- a real
    NVIDIA call. By default it is "down", so frames are kept unreviewed;
    tests of the review step stub it themselves."""
    from app.llm import LLMProviderError
    from app.nodes import frames as frames_module

    def unavailable(prompt, image_bytes, **kwargs):
        raise LLMProviderError("no vision calls in unit tests")

    monkeypatch.setattr(frames_module, "call_vision", unavailable)
