"""Unit tests for app.nodes.write — per-video Markdown chapter notes.

No real LLM calls: app.nodes.write.call_writer is monkeypatched.
"""
import json
import re

import pytest

from app.nodes import verify as verify_module
from app.nodes import write as write_module
from app.nodes.write import chapter_status_path, run_write, run_write_topic


def _write_chunk_and_topics(output_dir, video_id, chunk_index, text, topics):
    chunks_dir = output_dir / "work" / "chunks"
    topics_dir = output_dir / "work" / "topics"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    topics_dir.mkdir(parents=True, exist_ok=True)

    name = f"{video_id}_{chunk_index:03d}.json"
    (chunks_dir / name).write_text(
        json.dumps(
            {
                "video_id": video_id,
                "chunk_index": chunk_index,
                "start_seconds": 0,
                "end_seconds": 60,
                "text": text,
            }
        ),
        encoding="utf-8",
    )
    (topics_dir / name).write_text(
        json.dumps({"video_id": video_id, "chunk_index": chunk_index, "topics": topics}),
        encoding="utf-8",
    )


def test_run_write_single_chunk_writes_markdown_file(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    _write_chunk_and_topics(
        output_dir,
        "aircAruvnKk",
        0,
        text="A neural network is made of layers of neurons.",
        topics=["neural networks", "layers of neurons"],
    )

    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nSome notes."
    )

    notes_path = run_write("aircAruvnKk", output_dir)

    assert notes_path == output_dir / "work" / "notes" / "aircAruvnKk.md"
    assert notes_path.exists()
    content = notes_path.read_text(encoding="utf-8")
    assert "## Neural Networks" in content
    assert "Some notes." in content


def test_run_write_multiple_chunks_concatenates_in_order(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    _write_chunk_and_topics(output_dir, "longvid", 0, text="chunk zero content", topics=["a"])
    _write_chunk_and_topics(output_dir, "longvid", 1, text="chunk one content", topics=["b"])

    def fake_call_writer(prompt, **kw):
        if "chunk zero content" in prompt:
            return "## Section Zero"
        if "chunk one content" in prompt:
            return "## Section One"
        raise AssertionError("unexpected prompt")

    monkeypatch.setattr(write_module, "call_writer", fake_call_writer)

    notes_path = run_write("longvid", output_dir)
    content = notes_path.read_text(encoding="utf-8")

    assert content.index("## Section Zero") < content.index("## Section One")


def test_run_write_raises_when_no_chunks_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_write("missing-video", tmp_path / "output")


def test_run_write_only_uses_numbers_present_in_transcript(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    transcript = (
        "The network has 784 input neurons and 2 hidden layers with 16 "
        "neurons each, trained over 30 epochs."
    )
    _write_chunk_and_topics(
        output_dir,
        "aircAruvnKk",
        0,
        text=transcript,
        topics=["network architecture", "training"],
    )

    fake_notes = (
        "## Network Architecture\n\nThe network has 784 input neurons and 2 "
        "hidden layers of 16 neurons each.\n\n"
        "## Training\n\nIt was trained over 30 epochs."
    )
    monkeypatch.setattr(write_module, "call_writer", lambda prompt, **kw: fake_notes)

    notes_path = run_write("aircAruvnKk", output_dir)
    content = notes_path.read_text(encoding="utf-8")

    transcript_numbers = set(re.findall(r"\d+", transcript))
    output_numbers = set(re.findall(r"\d+", content))
    assert output_numbers <= transcript_numbers
    assert output_numbers  # sanity: the fixture actually exercises this check


def test_run_write_topic_synthesizes_one_file_from_multiple_source_videos(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    _write_chunk_and_topics(
        output_dir, "vid1", 0, text="Vid1 explains gradient descent step by step.", topics=["gd"]
    )
    _write_chunk_and_topics(
        output_dir, "vid2", 1, text="Vid2 shows how neural nets learn via gradients.", topics=["gd"]
    )

    captured = {}

    def fake_call_writer(prompt, **kw):
        captured["prompt"] = prompt
        return "## Gradient Descent\n\nSynthesized notes from both sources."

    monkeypatch.setattr(write_module, "call_writer", fake_call_writer)

    topic = {
        "id": "chapter:gradient-descent",
        "slug": "gradient-descent",
        "title": "Gradient Descent",
        "sources": [
            {"video_id": "vid1", "chunk_index": 0},
            {"video_id": "vid2", "chunk_index": 1},
        ],
    }

    notes_path = run_write_topic(topic, output_dir)

    assert notes_path == output_dir / "work" / "notes" / "topic_gradient-descent.md"
    assert notes_path.exists()
    assert "Vid1 explains gradient descent step by step." in captured["prompt"]
    assert "Vid2 shows how neural nets learn via gradients." in captured["prompt"]
    assert "vid1" in captured["prompt"]
    assert "vid2" in captured["prompt"]
    # One synthesized file, not one call_writer invocation per source video.
    content = notes_path.read_text(encoding="utf-8")
    assert content.count("## Gradient Descent") == 1


def test_run_write_topic_raises_when_source_chunk_missing(tmp_path):
    topic = {
        "slug": "missing",
        "title": "Missing Topic",
        "sources": [{"video_id": "nope", "chunk_index": 0}],
    }

    with pytest.raises(FileNotFoundError):
        run_write_topic(topic, tmp_path / "output")


# --- Refine loop (sprints/v5 Task 5: video mode) ------------------------


def test_run_write_refines_chunk_notes_until_judge_passes(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    _write_chunk_and_topics(output_dir, "vid1", 0, text="Some transcript text.", topics=["a"])

    write_calls = []

    def fake_call_writer(prompt, **kw):
        write_calls.append(prompt)
        return f"## Section\n\nAttempt {len(write_calls)}."

    monkeypatch.setattr(write_module, "call_writer", fake_call_writer)

    judge_calls = []

    def fake_judge_call_writer(prompt, **kw):
        judge_calls.append(prompt)
        if len(judge_calls) < 3:
            return json.dumps({"score": 3, "feedback": "needs more detail"})
        return json.dumps({"score": 9, "feedback": "great"})

    monkeypatch.setattr(verify_module, "call_writer", fake_judge_call_writer)

    notes_path = run_write("vid1", output_dir)
    content = notes_path.read_text(encoding="utf-8")

    assert len(write_calls) == 3
    assert len(judge_calls) == 3
    assert "Attempt 3." in content


def test_run_write_gives_up_after_max_refine_attempts(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    _write_chunk_and_topics(output_dir, "vid1", 0, text="Some transcript text.", topics=["a"])

    write_calls = []

    def fake_call_writer(prompt, **kw):
        write_calls.append(prompt)
        return "## Section\n\nAlways bad."

    monkeypatch.setattr(write_module, "call_writer", fake_call_writer)
    monkeypatch.setattr(
        verify_module,
        "call_writer",
        lambda prompt, **kw: json.dumps({"score": 2, "feedback": "still bad"}),
    )

    notes_path = run_write("vid1", output_dir)

    # MAX_REFINE_ATTEMPTS default (3) -- never an infinite loop, and the
    # last attempt is kept even though it never passed.
    assert len(write_calls) == 3
    assert notes_path.exists()
    assert "Always bad." in notes_path.read_text(encoding="utf-8")


# --- Refine loop (sprints/v5 Task 6: topic mode, shares _write_and_refine) -


_TOPIC = {
    "id": "chapter:gradient-descent",
    "slug": "gradient-descent",
    "title": "Gradient Descent",
    "sources": [{"video_id": "vid1", "chunk_index": 0}],
}


def test_run_write_topic_refines_notes_until_judge_passes(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    _write_chunk_and_topics(output_dir, "vid1", 0, text="Some transcript text.", topics=["gd"])

    write_calls = []

    def fake_call_writer(prompt, **kw):
        write_calls.append(prompt)
        return f"## Section\n\nAttempt {len(write_calls)}."

    monkeypatch.setattr(write_module, "call_writer", fake_call_writer)

    judge_calls = []

    def fake_judge_call_writer(prompt, **kw):
        judge_calls.append(prompt)
        if len(judge_calls) < 3:
            return json.dumps({"score": 3, "feedback": "needs more detail"})
        return json.dumps({"score": 9, "feedback": "great"})

    monkeypatch.setattr(verify_module, "call_writer", fake_judge_call_writer)

    notes_path = run_write_topic(_TOPIC, output_dir)
    content = notes_path.read_text(encoding="utf-8")

    assert len(write_calls) == 3
    assert len(judge_calls) == 3
    assert "Attempt 3." in content


def test_run_write_topic_gives_up_after_max_refine_attempts(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    _write_chunk_and_topics(output_dir, "vid1", 0, text="Some transcript text.", topics=["gd"])

    write_calls = []

    def fake_call_writer(prompt, **kw):
        write_calls.append(prompt)
        return "## Section\n\nAlways bad."

    monkeypatch.setattr(write_module, "call_writer", fake_call_writer)
    monkeypatch.setattr(
        verify_module,
        "call_writer",
        lambda prompt, **kw: json.dumps({"score": 2, "feedback": "still bad"}),
    )

    notes_path = run_write_topic(_TOPIC, output_dir)

    assert len(write_calls) == 3
    assert notes_path.exists()
    assert "Always bad." in notes_path.read_text(encoding="utf-8")


# --- Per-chapter progress sidecar (sprints/v9) ---------------------------


def test_write_and_refine_returns_score_and_attempts_when_passing_first_try(monkeypatch):
    monkeypatch.setattr(write_module, "call_writer", lambda prompt, **kw: "## Section\n\nNotes.")
    monkeypatch.setattr(
        verify_module, "call_writer", lambda prompt, **kw: json.dumps({"score": 9, "feedback": "great"})
    )

    notes, score, attempts = write_module._write_and_refine("prompt", "transcript")

    assert score == 9
    assert attempts == 1
    assert notes == "## Section\n\nNotes."


def test_write_and_refine_returns_last_score_and_max_attempts_when_never_passing(monkeypatch):
    monkeypatch.setattr(write_module, "call_writer", lambda prompt, **kw: "## Section\n\nAlways bad.")
    monkeypatch.setattr(
        verify_module,
        "call_writer",
        lambda prompt, **kw: json.dumps({"score": 2, "feedback": "still bad"}),
    )

    _, score, attempts = write_module._write_and_refine("prompt", "transcript")

    settings = write_module.load_settings()
    assert score == 2
    assert attempts == settings.max_refine_attempts


def test_run_write_writes_chapter_status_sidecar_with_aggregated_score_and_attempts(
    tmp_path, monkeypatch
):
    output_dir = tmp_path / "output"
    _write_chunk_and_topics(output_dir, "vid1", 0, text="chunk zero content", topics=["a"])
    _write_chunk_and_topics(output_dir, "vid1", 1, text="chunk one content", topics=["b"])

    monkeypatch.setattr(write_module, "call_writer", lambda prompt, **kw: "## Section\n\nNotes.")

    def fake_judge_call_writer(prompt, **kw):
        if "chunk zero content" in prompt:
            return json.dumps({"score": 9, "feedback": "great"})
        return json.dumps({"score": 2, "feedback": "still bad"})

    monkeypatch.setattr(verify_module, "call_writer", fake_judge_call_writer)

    run_write("vid1", output_dir)

    status_path = chapter_status_path("vid1", output_dir)
    assert status_path.exists()
    # chunk zero passes attempt 1 (score 9); chunk one exhausts all 3
    # attempts stuck at score 2 -- the weaker section's score/attempts win.
    assert json.loads(status_path.read_text(encoding="utf-8")) == {
        "score": 2,
        "attempts": 3,
        "passed": False,
    }


def test_run_write_topic_writes_chapter_status_sidecar(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    _write_chunk_and_topics(output_dir, "vid1", 0, text="Some transcript text.", topics=["gd"])

    monkeypatch.setattr(write_module, "call_writer", lambda prompt, **kw: "## Section\n\nNotes.")
    monkeypatch.setattr(
        verify_module, "call_writer", lambda prompt, **kw: json.dumps({"score": 9, "feedback": "great"})
    )

    run_write_topic(_TOPIC, output_dir)

    status_path = chapter_status_path("topic_gradient-descent", output_dir)
    assert status_path.exists()
    assert json.loads(status_path.read_text(encoding="utf-8")) == {
        "score": 9,
        "attempts": 1,
        "passed": True,
    }
