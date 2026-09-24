"""LLM provider chain: NVIDIA NIM primary, Gemini fallback.

Any primary error (rate limit, timeout, 5xx) retries the same request on the
fallback provider, independently per call — see root AGENTS.md LLM provider
chain. Claude is not a runtime option; no key is available.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from app.config import Settings, load_settings

WRITER_MODELS = {
    "nvidia": "nvidia/nemotron-3-super-120b-a12b",
    "gemini": "gemini-3.8-flash",
}

# nemotron-3-super is a reasoning model: for a full 30-minute-chunk transcript
# it can spend several thousand tokens thinking before it ever emits the
# final answer. A low completion cap or a short HTTP timeout truncates that
# mid-thought and produces unparseable output, not a real provider failure —
# verified empirically against the real API. This pipeline runs as a batch
# job (root AGENTS.md: "30-hour playlist finishes overnight"), so trading
# per-call latency for a reliably complete response is the right call here.
MAX_OUTPUT_TOKENS = 16384
REQUEST_TIMEOUT_SECONDS = 280

# If both primary and fallback fail on one attempt, retry the whole
# primary->fallback sequence with backoff before marking the step failed —
# see root AGENTS.md: "If both fail, retry with backoff, then mark the step
# failed and let --resume pick it up." A double failure is often transient
# (e.g. a provider's free tier momentarily overloaded), not permanent.
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (5, 20)

# Sprint v7 (Milestone 7 scale test): root AGENTS.md's LLM chain numbers --
# proactive pacing so a long run doesn't lean on 429-triggered fallback
# traffic to stay under these, which would burn Gemini's low daily cap
# needlessly on an otherwise-healthy NVIDIA run.
RATE_LIMITS_RPM = {
    "nvidia": 40,
    "gemini": 10,
}

# Per-provider timestamp (via `clock`) of the last paced call, process-wide.
# Deliberately module-level: call_writer is a plain function invoked from
# many nodes across one run, and pacing must hold across all of them, not
# just within a single call_writer invocation.
_last_call_at: dict[str, float] = {}


class LLMProviderError(RuntimeError):
    """Raised when both the primary and fallback provider calls fail."""


def _pace(provider: str, sleep: Callable[[float], None], clock: Callable[[], float]) -> None:
    """Sleep as needed so consecutive calls to `provider` stay under its
    configured RPM -- applied before each call, proactively, not just as a
    reaction to a 429.
    """
    rpm = RATE_LIMITS_RPM.get(provider)
    if not rpm:
        return

    min_interval = 60.0 / rpm
    now = clock()
    last = _last_call_at.get(provider)
    if last is not None:
        elapsed = now - last
        if elapsed < min_interval:
            sleep(min_interval - elapsed)
            now = last + min_interval

    _last_call_at[provider] = now


def _build_client(provider: str, api_key: str, model: str) -> Any:
    if provider == "nvidia":
        from langchain_nvidia_ai_endpoints import ChatNVIDIA

        return ChatNVIDIA(
            model=model,
            api_key=api_key,
            max_completion_tokens=MAX_OUTPUT_TOKENS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    raise ValueError(f"unknown LLM provider: {provider}")


def _client_for(provider: str, settings: Settings) -> Any:
    api_key = settings.nvidia_api_key if provider == "nvidia" else settings.google_api_key
    model = WRITER_MODELS[provider]
    return _build_client(provider, api_key, model)


def _extract_text(response: Any) -> str:
    content = getattr(response, "content", response)
    return content if isinstance(content, str) else str(content)


def _call_once(
    prompt: str,
    settings: Settings,
    factory: Callable[[str, Settings], Any],
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> str:
    """Try the primary provider, falling back to the secondary on any error."""
    try:
        _pace(settings.llm_provider, sleep, clock)
        client = factory(settings.llm_provider, settings)
        return _extract_text(client.invoke(prompt))
    except Exception as primary_error:
        try:
            _pace(settings.llm_fallback_provider, sleep, clock)
            client = factory(settings.llm_fallback_provider, settings)
            return _extract_text(client.invoke(prompt))
        except Exception as fallback_error:
            raise LLMProviderError(
                f"both providers failed: primary={primary_error!r} "
                f"fallback={fallback_error!r}"
            ) from fallback_error


def call_writer(
    prompt: str,
    settings: Settings | None = None,
    client_factory: Callable[[str, Settings], Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Call the writer-tier LLM, falling back to the secondary provider on error.

    Paces calls per provider to stay under its configured RPM (RATE_LIMITS_RPM,
    sprints/v7 PRD.md) before each attempt. If both providers fail on one
    attempt, retries the whole primary -> fallback sequence with backoff
    (MAX_ATTEMPTS total) before raising LLMProviderError — a double failure
    is often transient.

    client_factory defaults to app.llm._client_for, looked up by name at call
    time so tests can monkeypatch the module-level function.
    """
    settings = settings or load_settings()
    factory = client_factory if client_factory is not None else _client_for

    last_error: LLMProviderError | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return _call_once(prompt, settings, factory, sleep, clock)
        except LLMProviderError as error:
            last_error = error
            is_last_attempt = attempt == MAX_ATTEMPTS - 1
            if not is_last_attempt:
                sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])

    raise last_error  # type: ignore[misc] # MAX_ATTEMPTS >= 1 guarantees this is set
