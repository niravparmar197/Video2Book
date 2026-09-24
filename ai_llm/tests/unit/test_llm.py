"""Unit tests for app.llm — NVIDIA primary / Gemini fallback writer calls.

No real network calls: the provider client factory is monkeypatched with
fakes. See root AGENTS.md: any primary error retries on the fallback
provider, independently per call.
"""
import pytest

from app import llm as llm_module
from app.config import Settings
from app.llm import MAX_OUTPUT_TOKENS, REQUEST_TIMEOUT_SECONDS, LLMProviderError, call_writer, _build_client

TEST_SETTINGS = Settings(llm_provider="nvidia", llm_fallback_provider="gemini")


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeNvidiaClientRateLimited:
    def invoke(self, prompt):
        raise RuntimeError("429 rate limit exceeded")


class FakeGeminiClient:
    def __init__(self):
        self.received_prompts = []

    def invoke(self, prompt):
        self.received_prompts.append(prompt)
        return FakeResponse('["topic one", "topic two"]')


class FakeAlwaysFailsClient:
    def invoke(self, prompt):
        raise RuntimeError("boom")


def _fast_clock():
    """A fake clock that always jumps far ahead, so sprint v7's proactive
    rate-limit pacing never triggers a sleep -- for tests asserting on
    backoff sleeps specifically, not pacing itself (see test_llm_pacing
    tests below for pacing's own behavior).
    """
    state = {"value": 0.0}

    def _clock():
        state["value"] += 1000.0
        return state["value"]

    return _clock


def test_call_writer_falls_back_to_gemini_on_nvidia_error(monkeypatch):
    gemini_client = FakeGeminiClient()

    def fake_client_for(provider, settings):
        if provider == "nvidia":
            return FakeNvidiaClientRateLimited()
        if provider == "gemini":
            return gemini_client
        raise AssertionError(f"unexpected provider {provider}")

    monkeypatch.setattr(llm_module, "_client_for", fake_client_for)

    result = call_writer("summarize this chunk", settings=TEST_SETTINGS)

    assert result == '["topic one", "topic two"]'
    assert gemini_client.received_prompts == ["summarize this chunk"]


def test_call_writer_uses_primary_when_it_succeeds(monkeypatch):
    class FakePrimary:
        def invoke(self, prompt):
            return FakeResponse("primary result")

    def fake_client_for(provider, settings):
        assert provider == "nvidia"
        return FakePrimary()

    monkeypatch.setattr(llm_module, "_client_for", fake_client_for)

    assert call_writer("hello", settings=TEST_SETTINGS) == "primary result"


def test_call_writer_raises_when_both_providers_fail(monkeypatch):
    def fake_client_for(provider, settings):
        return FakeAlwaysFailsClient()

    monkeypatch.setattr(llm_module, "_client_for", fake_client_for)
    sleeps = []

    with pytest.raises(LLMProviderError):
        call_writer("hello", settings=TEST_SETTINGS, sleep=sleeps.append, clock=_fast_clock())

    assert len(sleeps) == llm_module.MAX_ATTEMPTS - 1


def test_call_writer_retries_after_a_transient_double_failure(monkeypatch):
    """Both providers can fail once (e.g. a free-tier 503) and still succeed
    on retry — root AGENTS.md: "retry with backoff" before marking failed.
    """
    attempts = {"count": 0}

    def fake_client_for(provider, settings):
        attempts["count"] += 1
        if attempts["count"] <= 2:  # first attempt: both primary+fallback fail
            return FakeAlwaysFailsClient()
        return FakeGeminiClient()  # second attempt: succeeds

    monkeypatch.setattr(llm_module, "_client_for", fake_client_for)
    sleeps = []

    result = call_writer("hello", settings=TEST_SETTINGS, sleep=sleeps.append, clock=_fast_clock())

    assert result == '["topic one", "topic two"]'
    assert sleeps == [llm_module.BACKOFF_SECONDS[0]]


def test_build_client_gives_nvidia_a_generous_token_budget_and_timeout():
    """Regression guard: nemotron-3-super is a reasoning model that can spend
    thousands of tokens thinking before its final answer on a full chunk
    transcript. A low completion cap or short timeout truncates mid-thought
    and yields unparseable output — verified against the real API while
    building Task 8. See app/llm.py's MAX_OUTPUT_TOKENS/REQUEST_TIMEOUT_SECONDS
    comment for the full story.
    """
    client = _build_client("nvidia", api_key="test-key", model="nvidia/nemotron-3-super-120b-a12b")
    assert client.max_tokens == MAX_OUTPUT_TOKENS
    assert client._client.timeout == REQUEST_TIMEOUT_SECONDS


def test_build_client_gives_gemini_a_generous_token_budget_and_timeout():
    client = _build_client("gemini", api_key="test-key", model="gemini-3.8-flash")
    assert client.max_output_tokens == MAX_OUTPUT_TOKENS
    assert client.timeout == REQUEST_TIMEOUT_SECONDS


def test_call_writer_extracts_string_content_directly():
    class FakeStringClient:
        def invoke(self, prompt):
            return "plain string response"

    result = call_writer(
        "hello",
        settings=TEST_SETTINGS,
        client_factory=lambda provider, settings: FakeStringClient(),
    )
    assert result == "plain string response"


class _FakeClock:
    """A fake time source shared between `sleep` and `clock`: sleeping
    advances the clock by exactly the requested amount, so elapsed-time
    math is testable without any real wait.
    """

    def __init__(self):
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _FakeStaticClient:
    def invoke(self, prompt):
        return FakeResponse("ok")


def test_call_writer_paces_consecutive_calls_to_the_same_provider(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(
        llm_module, "_client_for", lambda provider, settings: _FakeStaticClient()
    )

    call_writer("p1", settings=TEST_SETTINGS, sleep=clock.sleep, clock=clock.time)
    time_after_first = clock.now
    call_writer("p2", settings=TEST_SETTINGS, sleep=clock.sleep, clock=clock.time)
    time_after_second = clock.now

    expected_min_interval = 60.0 / llm_module.RATE_LIMITS_RPM["nvidia"]
    assert time_after_second - time_after_first >= expected_min_interval - 1e-9


def test_call_writer_does_not_pace_first_call(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(
        llm_module, "_client_for", lambda provider, settings: _FakeStaticClient()
    )

    call_writer("p1", settings=TEST_SETTINGS, sleep=clock.sleep, clock=clock.time)

    assert clock.now == 0.0  # no sleep before the very first call


def test_call_writer_paces_independently_per_provider(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(
        llm_module, "_client_for", lambda provider, settings: _FakeStaticClient()
    )

    nvidia_settings = Settings(llm_provider="nvidia", llm_fallback_provider="gemini")
    gemini_settings = Settings(llm_provider="gemini", llm_fallback_provider="nvidia")

    call_writer("p1", settings=nvidia_settings, sleep=clock.sleep, clock=clock.time)
    time_after_nvidia = clock.now
    call_writer("p2", settings=gemini_settings, sleep=clock.sleep, clock=clock.time)
    time_after_gemini = clock.now

    # A different provider's first call is never paced against another
    # provider's timestamp.
    assert time_after_gemini - time_after_nvidia == 0.0
