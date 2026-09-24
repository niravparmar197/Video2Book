"""Unit test for app.graph — the BOOK_ORDER=topic graph (sprints/v3 Task 5).

No real network, LLM, or latexmk calls: run_fetch_playlist, plan.py's and
write.py's call_writer, and compile_chapter are all monkeypatched.
"""
import json
from pathlib import Path

import pytest

from app import graph as graph_module
from app.nodes import book_pass as book_pass_module
from app.nodes import plan as plan_module
from app.nodes import topics as topics_module
from app.nodes import write as write_module
from app.youtube import VideoInfo

SAMPLE_VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:02.500\nHello and welcome to this video.\n"

TEST_PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLfakeplaylist"


@pytest.fixture(autouse=True)
def _force_topic_order(monkeypatch):
    monkeypatch.setenv("BOOK_ORDER", "topic")


def _fake_run_fetch_playlist(url, output_dir):
    output_dir = Path(output_dir)
    captions_dir = output_dir / "work" / "captions"
    captions_dir.mkdir(parents=True, exist_ok=True)

    videos = []
    for index, video_id in enumerate(("vid1", "vid2"), start=1):
        captions_path = captions_dir / f"{video_id}.en.vtt"
        captions_path.write_text(SAMPLE_VTT, encoding="utf-8")
        videos.append(
            VideoInfo(
                video_id=video_id,
                title=f"Title {video_id}",
                duration_seconds=150,
                url=url,
                captions_path=str(captions_path),
                playlist_index=index,
            )
        )
    return videos


def _fake_compile_chapter(tex_path, **kwargs):
    pdf_path = Path(tex_path).with_suffix(".pdf")
    pdf_path.write_bytes(b"%PDF-fake")
    return pdf_path


def test_run_book_topic_order_merges_overlapping_topic_into_one_chapter(tmp_path, monkeypatch):
    output_dir = tmp_path / "output" / "some-book"

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["gradient descent"]')

    merged_plan_response = json.dumps(
        [
            {
                "title": "Gradient Descent",
                "level": 1,
                "needs": [],
                "sources": [
                    {"video_id": "vid1", "chunk_index": 0},
                    {"video_id": "vid2", "chunk_index": 0},
                ],
            }
        ]
    )
    monkeypatch.setattr(plan_module, "call_writer", lambda prompt, **kw: merged_plan_response)
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Gradient Descent\n\nSynthesized."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    pdf_path = graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    assert pdf_path == output_dir / "book.pdf"
    assert pdf_path.exists()
    assert (output_dir / "plan.json").exists()
    assert (output_dir / "ordered_plan.json").exists()
    assert (output_dir / "work" / "notes" / "topic_gradient-descent.md").exists()

    main_tex = (output_dir / "chapters" / "main.tex").read_text(encoding="utf-8")
    input_lines = [line for line in main_tex.splitlines() if line.strip().startswith(r"\input{")]
    # ONE chapter for the merged topic, not one per video — the whole point
    # of BOOK_ORDER=topic. (book_pass, sprints/v6, always adds a topic
    # index once it runs; the empty conftest stub means no glossary here.)
    assert input_lines == [r"\input{gradient-descent}", r"\input{topic_index}"]


def test_run_book_topic_order_raises_over_max_book_hours_without_force(tmp_path, monkeypatch):
    """sprints/v7 Task 2: the budget gate also applies to BOOK_ORDER=topic,
    not just the video-order graph.
    """
    output_dir = tmp_path / "output" / "some-book"
    monkeypatch.setenv("MAX_BOOK_HOURS", "0")  # fake videos are 150s each -> always over a 0h budget

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["gradient descent"]')

    with pytest.raises(graph_module.BudgetExceededError):
        graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    assert not (output_dir / "plan.json").exists()


def test_run_plan_topic_order_stops_before_render(tmp_path, monkeypatch):
    output_dir = tmp_path / "output" / "some-book"

    render_calls = []

    def fake_compile_chapter(tex_path, **kwargs):
        render_calls.append(tex_path)
        return _fake_compile_chapter(tex_path, **kwargs)

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["gradient descent"]')
    monkeypatch.setattr(
        plan_module,
        "call_writer",
        lambda prompt, **kw: json.dumps(
            [
                {
                    "title": "Gradient Descent",
                    "level": 1,
                    "needs": [],
                    "sources": [
                        {"video_id": "vid1", "chunk_index": 0},
                        {"video_id": "vid2", "chunk_index": 0},
                    ],
                }
            ]
        ),
    )
    monkeypatch.setattr(graph_module, "compile_chapter", fake_compile_chapter)

    videos, chapters = graph_module.run_plan(TEST_PLAYLIST_URL, output_dir)

    assert len(chapters) == 1
    assert chapters[0]["id"] == "chapter:gradient-descent"
    assert {v["video_id"] for v in videos} == {"vid1", "vid2"}
    assert (output_dir / "outline.json").exists()
    assert (output_dir / "outline.md").exists()
    assert (output_dir / "plan.json").exists()
    assert (output_dir / "ordered_plan.json").exists()
    # render/compile and the write_topic LLM call must never happen.
    assert render_calls == []
    assert not (output_dir / "book.pdf").exists()
    assert not (output_dir / "work" / "notes").exists()


def test_run_book_topic_order_video_mode_stream_calls_run_frames_per_chunk(tmp_path, monkeypatch):
    """sprints/v4 Task 5: frames node also runs in the topic-order graph."""
    output_dir = tmp_path / "output" / "some-book"
    monkeypatch.setenv("VIDEO_MODE", "stream")

    frames_calls = []

    def fake_run_frames(video_id, video_url, chunk, out_dir):
        frames_calls.append((video_id, chunk["chunk_index"]))
        frames_path = Path(out_dir) / "work" / "frames" / f"{video_id}_{chunk['chunk_index']:03d}.json"
        frames_path.parent.mkdir(parents=True, exist_ok=True)
        frames_path.write_text('{"video_id": "%s", "chunk_index": 0, "frames": []}' % video_id)
        return frames_path

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(graph_module, "run_frames", fake_run_frames)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["gradient descent"]')
    monkeypatch.setattr(
        plan_module,
        "call_writer",
        lambda prompt, **kw: json.dumps(
            [
                {
                    "title": "Gradient Descent",
                    "level": 1,
                    "needs": [],
                    "sources": [
                        {"video_id": "vid1", "chunk_index": 0},
                        {"video_id": "vid2", "chunk_index": 0},
                    ],
                }
            ]
        ),
    )
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Gradient Descent\n\nSynthesized."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    assert sorted(frames_calls) == [("vid1", 0), ("vid2", 0)]
    assert (output_dir / "work" / "frames" / "vid1_000.json").exists()
    assert (output_dir / "work" / "frames" / "vid2_000.json").exists()


def test_run_book_topic_order_wires_real_glossary_and_indexes(tmp_path, monkeypatch):
    """sprints/v6 Task 8: book_pass's real output reaches the compiled
    main.tex in topic mode too, not just video mode.
    """
    output_dir = tmp_path / "output" / "some-book"

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["gradient descent"]')
    monkeypatch.setattr(
        plan_module,
        "call_writer",
        lambda prompt, **kw: json.dumps(
            [
                {
                    "title": "Gradient Descent",
                    "level": 1,
                    "needs": [],
                    "sources": [
                        {"video_id": "vid1", "chunk_index": 0},
                        {"video_id": "vid2", "chunk_index": 0},
                    ],
                }
            ]
        ),
    )
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Gradient Descent\n\nSynthesized."
    )

    def fake_book_pass_call_writer(prompt, **kw):
        if "Chapters covered, in order:" in prompt:
            return "This book covers gradient descent."
        if "Chapter notes:" in prompt:
            return json.dumps(["Gradient Descent"])
        if "Chapters:" in prompt:
            return json.dumps(
                [{"term": "Gradient Descent", "definition": "An optimization method."}]
            )
        raise AssertionError(f"unexpected book_pass prompt: {prompt[:200]}")

    monkeypatch.setattr(book_pass_module, "call_writer", fake_book_pass_call_writer)
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    main_tex = (output_dir / "chapters" / "main.tex").read_text(encoding="utf-8")
    assert r"\input{glossary}" in main_tex
    assert r"\printindex" in main_tex
    assert r"\input{topic_index}" in main_tex
    assert "Preface" in main_tex

    glossary_tex = (output_dir / "chapters" / "glossary.tex").read_text(encoding="utf-8")
    assert "Gradient Descent" in glossary_tex
