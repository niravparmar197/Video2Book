"""Unit tests for app.nodes.genre -- lecture / podcast / comedy books.

No real LLM calls: app.nodes.genre.call_writer is monkeypatched.
"""
import json

import pytest

from app import graph as graph_module
from app.nodes import genre as genre_module
from app.nodes import write as write_module


def _write_first_chunk(output_dir, video_id, text):
    chunks_dir = output_dir / "work" / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    (chunks_dir / f"{video_id}_000.json").write_text(
        json.dumps({"video_id": video_id, "chunk_index": 0, "text": text}), encoding="utf-8"
    )


def test_auto_genre_asks_once_per_video_with_title_and_transcript_start(tmp_path, monkeypatch):
    _write_first_chunk(tmp_path, "v1", "So a man walks into a bar [Laughter] " * 300)
    prompts = []

    def fake_call_writer(prompt, **kw):
        prompts.append(prompt)
        return "Comedy."

    monkeypatch.setattr(genre_module, "call_writer", fake_call_writer)

    genre = genre_module.run_genre([{"video_id": "v1", "title": "Live at the Apollo"}], tmp_path)

    assert genre == "comedy"
    assert len(prompts) == 1
    assert "Live at the Apollo" in prompts[0] and "[Laughter]" in prompts[0]
    assert len(prompts[0]) < 5000  # only the start of the transcript is sent
    assert genre_module.load_genre(tmp_path) == "comedy"


def test_playlist_genre_is_the_most_common_one(tmp_path, monkeypatch):
    answers = iter(["podcast", "lecture", "podcast"])
    monkeypatch.setattr(genre_module, "call_writer", lambda prompt, **kw: next(answers))
    videos = [{"video_id": f"v{i}", "title": f"Episode {i}"} for i in range(3)]

    assert genre_module.run_genre(videos, tmp_path) == "podcast"
    saved = json.loads(genre_module.genre_json_path(tmp_path).read_text(encoding="utf-8"))
    assert saved["per_video"] == {"v0": "podcast", "v1": "lecture", "v2": "podcast"}


def test_unclear_answer_falls_back_to_lecture(tmp_path, monkeypatch):
    monkeypatch.setattr(genre_module, "call_writer", lambda prompt, **kw: "Hmm, hard to say.")

    assert genre_module.run_genre([{"video_id": "v1", "title": "T"}], tmp_path) == "lecture"


def test_video_genre_setting_forces_the_genre_without_an_llm_call(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_GENRE", "podcast")

    def fail(prompt, **kw):
        raise AssertionError("a forced genre must not call the LLM")

    monkeypatch.setattr(genre_module, "call_writer", fail)

    assert genre_module.run_genre([{"video_id": "v1", "title": "T"}], tmp_path) == "podcast"


def test_load_genre_defaults_to_lecture_before_it_is_decided(tmp_path):
    assert genre_module.load_genre(tmp_path) == "lecture"


@pytest.mark.parametrize(
    "genre, must_contain, must_not_contain",
    [
        ("lecture", ["STUDY NOTES", "> Key point:", "Think of it like", "## Key Takeaways"], ["COMEDY"]),
        ("podcast", ["PODCAST NOTES", "> Quote:", "## Mentioned in This Episode", "the guest"], ["Think of it like"]),
        ("comedy", ["COMEDY RECAP", "> Quote:", "## Best Moments", "never \"improve\" a punchline"], ["## Key Takeaways", "Think of it like"]),
    ],
)
def test_each_genre_gets_its_own_writing_style_plus_the_shared_grounding(
    genre, must_contain, must_not_contain
):
    prompt = write_module._load_prompt("some transcript", ["Topic A"], genre)

    for text in must_contain:
        assert text in prompt
    for text in must_not_contain:
        assert text not in prompt
    # Shared by every genre:
    assert "Never invent a number, name, quote or claim" in prompt
    assert "Never use a code fence for anything except" in prompt


def test_run_write_topic_uses_the_books_genre(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    chunks_dir = output_dir / "work" / "chunks"
    chunks_dir.mkdir(parents=True)
    (chunks_dir / "v1_000.json").write_text(
        json.dumps({"video_id": "v1", "chunk_index": 0, "text": "jokes"}), encoding="utf-8"
    )
    genre_module.genre_json_path(output_dir).write_text(json.dumps({"genre": "comedy"}), encoding="utf-8")
    captured = {}

    def fake_call_writer(prompt, **kw):
        captured["prompt"] = prompt
        return "## Flying with Kids\n- Setup."

    monkeypatch.setattr(write_module, "call_writer", fake_call_writer)

    write_module.run_write_topic(
        {"slug": "s", "title": "Show", "sources": [{"video_id": "v1", "chunk_index": 0}]}, output_dir
    )

    assert "COMEDY RECAP" in captured["prompt"]


def test_comedy_books_skip_the_glossary_and_index_llm_calls(tmp_path, monkeypatch):
    genre_module.genre_json_path(tmp_path).parent.mkdir(parents=True)
    genre_module.genre_json_path(tmp_path).write_text(json.dumps({"genre": "comedy"}), encoding="utf-8")
    notes = tmp_path / "n.md"
    notes.write_text("## Bit\n- joke", encoding="utf-8")

    def fail(*args, **kwargs):
        raise AssertionError("no glossary/index calls for a comedy recap")

    monkeypatch.setattr(graph_module, "run_glossary", fail)
    monkeypatch.setattr(graph_module, "run_index_terms", fail)

    result = graph_module._run_book_pass(
        [{"file_key": "c1", "title": "Show", "notes_path": str(notes)}], str(tmp_path)
    )

    assert result == {"glossary": [], "index_terms_by_file_key": {}}


def test_topics_node_also_decides_and_saves_the_genre(tmp_path, monkeypatch):
    _write_first_chunk(tmp_path, "v1", "welcome back to the podcast, my guest today is ...")
    monkeypatch.setattr(genre_module, "call_writer", lambda prompt, **kw: "podcast")
    monkeypatch.setattr(graph_module, "run_topics", lambda chunk_path, output_dir: None)

    graph_module._topics_node(
        {
            "output_dir": str(tmp_path),
            "videos": [{"video_id": "v1", "title": "Ep 1"}],
            "chunk_paths": {"v1": [str(tmp_path / "work" / "chunks" / "v1_000.json")]},
        }
    )

    assert genre_module.load_genre(tmp_path) == "podcast"
