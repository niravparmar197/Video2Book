"""Unit tests for app.nodes.topics — per-chunk topic extraction.

No real LLM calls: either app.nodes.topics.call_writer or the underlying
app.llm provider clients are replaced with fakes.
"""
import json

from app import llm as llm_module
from app.nodes import topics as topics_module
from app.nodes.topics import run_topics


def _write_chunk(
    tmp_path,
    video_id="aircAruvnKk",
    chunk_index=0,
    text="neural networks are layers of neurons",
):
    chunk_path = tmp_path / f"{video_id}_{chunk_index:03d}.json"
    chunk_path.write_text(
        json.dumps({"video_id": video_id, "chunk_index": chunk_index, "text": text}),
        encoding="utf-8",
    )
    return chunk_path


def test_run_topics_writes_topics_json(tmp_path, monkeypatch):
    monkeypatch.setattr(
        topics_module,
        "call_writer",
        lambda prompt, **kw: '["neural networks", "layers of neurons"]',
    )

    chunk_path = _write_chunk(tmp_path)
    topics_path = run_topics(chunk_path, tmp_path / "output")

    assert topics_path.exists()
    payload = json.loads(topics_path.read_text(encoding="utf-8"))
    assert payload["video_id"] == "aircAruvnKk"
    assert payload["chunk_index"] == 0
    assert payload["topics"] == ["neural networks", "layers of neurons"]


def test_run_topics_strips_markdown_code_fences(tmp_path, monkeypatch):
    monkeypatch.setattr(
        topics_module,
        "call_writer",
        lambda prompt, **kw: '```json\n["gradient descent"]\n```',
    )

    chunk_path = _write_chunk(tmp_path)
    topics_path = run_topics(chunk_path, tmp_path / "output")

    payload = json.loads(topics_path.read_text(encoding="utf-8"))
    assert payload["topics"] == ["gradient descent"]


def test_run_topics_extracts_array_from_surrounding_prose(tmp_path, monkeypatch):
    """A reasoning model can prepend chain-of-thought before the array despite
    being told not to; the parser must still find and use the array."""
    monkeypatch.setattr(
        topics_module,
        "call_writer",
        lambda prompt, **kw: (
            'Let me think about this... the topics are clear.\n'
            'Final answer: ["gradient descent", "backpropagation"]'
        ),
    )

    chunk_path = _write_chunk(tmp_path)
    topics_path = run_topics(chunk_path, tmp_path / "output")

    payload = json.loads(topics_path.read_text(encoding="utf-8"))
    assert payload["topics"] == ["gradient descent", "backpropagation"]


def test_run_topics_degrades_to_empty_list_when_response_is_never_a_list(tmp_path, monkeypatch):
    """A well-formed JSON value that isn't a list (e.g. an object) is treated
    the same as "no usable array": retried once, then degrades to []
    rather than raising and aborting the whole book."""
    calls = []

    def fake_call_writer(prompt, **kw):
        calls.append(prompt)
        return '{"not": "a list"}'

    monkeypatch.setattr(topics_module, "call_writer", fake_call_writer)

    chunk_path = _write_chunk(tmp_path)
    topics_path = run_topics(chunk_path, tmp_path / "output")

    payload = json.loads(topics_path.read_text(encoding="utf-8"))
    assert payload["topics"] == []
    assert len(calls) == 2  # original attempt + one stricter retry


def test_run_topics_retries_once_with_a_stricter_prompt_when_no_array_found(tmp_path, monkeypatch):
    """A reasoning-only completion (chain-of-thought prose, no JSON array at
    all — the real failure seen against the live NVIDIA API) triggers one
    retry with a stricter follow-up prompt; if the retry succeeds, its
    topics are used."""
    calls = []

    def fake_call_writer(prompt, **kw):
        calls.append(prompt)
        if len(calls) == 1:
            return (
                "We need to extract distinct topics covered in this "
                "transcript chunk... let me scan through it carefully."
            )
        return '["gradient descent", "backpropagation"]'

    monkeypatch.setattr(topics_module, "call_writer", fake_call_writer)

    chunk_path = _write_chunk(tmp_path)
    topics_path = run_topics(chunk_path, tmp_path / "output")

    payload = json.loads(topics_path.read_text(encoding="utf-8"))
    assert payload["topics"] == ["gradient descent", "backpropagation"]
    assert len(calls) == 2
    # the retry prompt must be strictly stronger, not identical to the first
    assert calls[1] != calls[0]


def test_run_topics_degrades_to_empty_list_when_retry_also_has_no_array(tmp_path, monkeypatch):
    """If neither the original call nor the stricter retry ever produces a
    JSON array (a persistently reasoning-only completion), the chunk fails
    gracefully with an empty topics list instead of crashing the whole
    graph run — root AGENTS.md crash-safety: one bad chunk must not restart
    the whole book from zero."""
    calls = []

    def fake_call_writer(prompt, **kw):
        calls.append(prompt)
        return "Let me think step by step about what topics are covered here..."

    monkeypatch.setattr(topics_module, "call_writer", fake_call_writer)

    chunk_path = _write_chunk(tmp_path)
    topics_path = run_topics(chunk_path, tmp_path / "output")

    payload = json.loads(topics_path.read_text(encoding="utf-8"))
    assert payload["video_id"] == "aircAruvnKk"
    assert payload["chunk_index"] == 0
    assert payload["topics"] == []
    assert len(calls) == 2  # original attempt + one stricter retry, then give up


class FakeNvidiaRateLimited:
    def invoke(self, prompt):
        raise RuntimeError("429 rate limit exceeded")


class FakeGeminiClient:
    def __init__(self):
        self.received_prompts = []

    def invoke(self, prompt):
        self.received_prompts.append(prompt)

        class Response:
            content = '["gradient descent", "backpropagation"]'

        return Response()


def test_run_topics_falls_back_to_gemini_when_nvidia_rate_limited(tmp_path, monkeypatch):
    gemini_client = FakeGeminiClient()

    def fake_client_for(provider, settings):
        if provider == "nvidia":
            return FakeNvidiaRateLimited()
        return gemini_client

    monkeypatch.setattr(llm_module, "_client_for", fake_client_for)

    chunk_path = _write_chunk(
        tmp_path, text="gradient descent minimizes the loss via backpropagation"
    )
    topics_path = run_topics(chunk_path, tmp_path / "output")

    payload = json.loads(topics_path.read_text(encoding="utf-8"))
    assert payload["topics"] == ["gradient descent", "backpropagation"]
    assert len(gemini_client.received_prompts) == 1
    assert "gradient descent minimizes the loss" in gemini_client.received_prompts[0]
