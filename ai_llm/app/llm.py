"""LLM provider chain: NVIDIA NIM primary, Gemini fallback.

Any primary error (rate limit, timeout, 5xx) retries the same request on the
fallback provider, independently per call — see root AGENTS.md LLM provider
chain. Claude is not a runtime option; no key is available.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from langsmith import traceable

from app.config import Settings, load_settings

logger = logging.getLogger(__name__)

WRITER_MODELS = {
    # nemotron-3-super-120b-a12b reached end of life 2026-10-03 (verified
    # against the real API: a 410 Gone on every call) -- openai/gpt-oss-20b
    # replaces it: verified live against NVIDIA NIM's actual model catalog
    # (GET /v1/models) and smoke-tested directly, it's free on the same
    # NIM catalog, answers in ~9s on a realistic chunk-sized prompt (vs.
    # candidates like nemotron-3.5-lightning-30b-a3b, which spent 40s+
    # narrating chain-of-thought without ever finishing even a trivial
    # prompt), and returns a plain string response (not the multi-part
    # content-block shape that previously corrupted the book -- see
    # _extract_text). Several other NIM-listed candidates (nemotron-
    # nano-3-30b-a3b, llama-3.1-nemotron-51b/70b-instruct, mistral-large-
    # 2-instruct) 404'd: listed in the catalog but not actually deployed
    # for this account.
    "nvidia": "openai/gpt-oss-20b",
    "gemini": "gemini-3.8-flash",
}

# A reasoning model can spend several thousand tokens thinking before it
# ever emits the final answer on a full 30-minute-chunk transcript (true of
# some NIM catalog models, though not the current default above). A low
# completion cap or a short HTTP timeout truncates that mid-thought and
# produces unparseable output, not a real provider failure — verified
# empirically against the real API. This pipeline runs as a batch job (root
# AGENTS.md: "30-hour playlist finishes overnight"), so trading per-call
# latency for a reliably complete response is the right call regardless of
# which model is configured.
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

# Per-provider timestamp (via `clock`) of the next free call slot,
# process-wide. Deliberately module-level: call_writer is a plain function
# invoked from many nodes across one run, and pacing must hold across all of
# them, not just within a single call_writer invocation. graph.py now calls
# call_writer concurrently (bounded thread pool) for independent chunks/
# chapters, so _pace_lock guards this dict -- without it, two threads can
# both read the same `last`, both decide they're clear to go, and both fire
# in the same instant, defeating the whole point of proactive pacing.
_last_call_at: dict[str, float] = {}
_pace_lock = threading.Lock()


class LLMProviderError(RuntimeError):
    """Raised when both the primary and fallback provider calls fail."""


def _pace(provider: str, sleep: Callable[[float], None], clock: Callable[[], float]) -> None:
    """Sleep as needed so consecutive calls to `provider` stay under its
    configured RPM -- applied before each call, proactively, not just as a
    reaction to a 429.

    Reserves this call's slot under the lock (a fast, non-blocking dict
    update) and only then sleeps outside the lock, so concurrent callers
    queue up for distinct slots instead of serializing on the sleep itself.
    """
    rpm = RATE_LIMITS_RPM.get(provider)
    if not rpm:
        return

    min_interval = 60.0 / rpm
    with _pace_lock:
        now = clock()
        last = _last_call_at.get(provider)
        next_slot = now if last is None else max(now, last + min_interval)
        _last_call_at[provider] = next_slot

    wait = next_slot - clock()
    if wait > 0:
        sleep(wait)


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

        # max_retries=0: ChatGoogleGenerativeAI defaults to retrying 429s
        # itself (up to 6x, respecting the server's suggested delay) before
        # ever raising back to _call_once. Stacked under call_writer's own
        # MAX_ATTEMPTS/BACKOFF_SECONDS retry, that turned one exhausted
        # *daily* quota (which no amount of retrying fixes) into a 20+
        # minute stall -- verified against the real API. call_writer is
        # already the single place that owns retry/backoff/fallback timing.
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )
    raise ValueError(f"unknown LLM provider: {provider}")


def _client_for(provider: str, settings: Settings) -> Any:
    api_key = settings.nvidia_api_key if provider == "nvidia" else settings.google_api_key
    model = WRITER_MODELS[provider]
    return _build_client(provider, api_key, model)


def _extract_text(response: Any) -> str:
    """Pull the plain text out of a LangChain chat response.

    `response.content` is usually a plain string, but some providers can
    return a list of content blocks instead -- e.g. [{"type": "text",
    "text": "...", "extras": {"signature": "..."}}] -- when extra
    metadata (observed from Gemini: a "thought signature" block) rides
    along with the real text. Falling back to str(content) in that case
    dumped the raw Python repr of that whole structure -- extras/
    signature blob included -- straight into a real compiled book
    (verified against a real PDF: a chapter's "notes" was literally
    "[{'type': 'text', 'text': '...', 'extras': {'signature': '...'}}]").
    Every call_writer call (topics, plan merge, glossary, preface, write,
    verify) shares this one extraction path, so this also explains
    downstream JSON-parsing nodes degrading to empty results: that text
    can never parse as JSON either, regardless of the prompt or language.
    """
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block if isinstance(block, str) else block["text"]
            for block in content
            if isinstance(block, str) or isinstance(block, dict) and isinstance(block.get("text"), str)
        ]
        if parts:
            return "".join(parts)
    return str(content)


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
        # INFO, not WARNING: a fallback is routine on the free tiers and must
        # not land in the book's warnings.jsonl; counted on the log/trace side.
        logger.info(
            "llm fallback: %s failed (%s), trying %s",
            settings.llm_provider,
            type(primary_error).__name__,
            settings.llm_fallback_provider,
        )
        try:
            _pace(settings.llm_fallback_provider, sleep, clock)
            client = factory(settings.llm_fallback_provider, settings)
            return _extract_text(client.invoke(prompt))
        except Exception as fallback_error:
            raise LLMProviderError(
                f"both providers failed: primary={primary_error!r} "
                f"fallback={fallback_error!r}"
            ) from fallback_error


# --- vision ----------------------------------------------------------------

# The NIM catalog id of root AGENTS.md's "nemotron-3-nano-omni" (verified
# live against GET /v1/models and a real screenshot: ~4-8s per image).
VISION_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
VISION_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
# Most replies take 4-8s; a stuck one (seen: 120s) is better skipped -- the
# frame is then kept unreviewed.
VISION_TIMEOUT_SECONDS = 45
# The free endpoint often answers 503 "Worker local total request limit
# reached" for a few seconds; a short retry usually gets through.
VISION_RETRY_SECONDS = (3, 10)


def _post_json(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    import json
    import urllib.request

    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310 - fixed https URL
        return json.load(response)


def _vision_trace_inputs(inputs: dict) -> dict:
    """What a vision run shows in LangSmith: the prompt and image size only --
    never the headers (they carry the API key) or the base64 image (~100KB
    per frame, hundreds of frames on a long video)."""
    payload = inputs.get("payload") or {}
    content = (payload.get("messages") or [{}])[0].get("content") or []
    prompt = next((part.get("text") for part in content if part.get("type") == "text"), None)
    image = next((part["image_url"]["url"] for part in content if part.get("type") == "image_url"), "")
    return {"model": payload.get("model"), "prompt": prompt, "image_base64_chars": len(image)}


def _vision_trace_outputs(outputs: Any) -> dict:
    """The reply text plus token usage in LangSmith's usage_metadata shape, so
    vision calls count toward a book's tokens like the LangChain calls do."""
    response = outputs.get("output", outputs) if isinstance(outputs, dict) else outputs
    if not isinstance(response, dict):
        return {"output": response}
    usage = response.get("usage") or {}
    choices = response.get("choices") or [{}]
    return {
        "output": choices[0].get("message", {}).get("content"),
        "usage_metadata": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
    }


@traceable(
    run_type="llm",
    name="NVIDIA vision",
    metadata={"ls_provider": "nvidia", "ls_model_name": VISION_MODEL},
    process_inputs=_vision_trace_inputs,
    process_outputs=_vision_trace_outputs,
)
def _post_vision(payload: dict, headers: dict, post: Callable[[str, dict, dict, float], dict]) -> dict:
    """One vision HTTP request, traced to LangSmith as an LLM run (when
    LANGSMITH_TRACING is on) -- the request bypasses LangChain, so nothing
    else would record it."""
    return post(VISION_URL, payload, headers, VISION_TIMEOUT_SECONDS)


def call_vision(
    prompt: str,
    image_bytes: bytes,
    settings: Settings | None = None,
    post: Callable[[str, dict, dict, float], dict] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Ask the NVIDIA vision model about one JPEG; returns its text reply.

    Shares the NVIDIA pacing with call_writer (one account, one RPM budget).
    No Gemini fallback, unlike call_writer: screenshot review is optional,
    and every frame of a long video falling back would spend Gemini's small
    daily cap that the writer may need. Raises LLMProviderError when every
    try fails -- callers keep the frame unreviewed.
    """
    import base64

    settings = settings or load_settings()
    post = post or _post_json
    payload = {
        "model": VISION_MODEL,
        "max_tokens": 2048,
        "temperature": 0.2,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")},
                    },
                ],
            }
        ],
    }
    headers = {"Authorization": f"Bearer {settings.nvidia_api_key}", "Content-Type": "application/json"}

    last_error: Exception | None = None
    for attempt in range(len(VISION_RETRY_SECONDS) + 1):
        try:
            _pace("nvidia", sleep, clock)
            response = _post_vision(payload, headers, post)
            return _extract_text(response["choices"][0]["message"]["content"])
        except Exception as error:  # noqa: BLE001 - any failure: retry, then give up
            last_error = error
            if attempt < len(VISION_RETRY_SECONDS):
                sleep(VISION_RETRY_SECONDS[attempt])
    raise LLMProviderError(f"vision model failed: {last_error!r}") from last_error


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
