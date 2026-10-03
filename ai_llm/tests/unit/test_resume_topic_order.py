"""Unit test for app.graph's --resume path in BOOK_ORDER=topic (sprints/v3 Task 6).

Simulates a crash mid-write (topic 2 of 2's write fails) and verifies
resume_book() continues without re-invoking plan/order/outline or topic 1's
already-completed write. Mirrors sprints/v2 Task 8's playlist crash test,
now for the topic pipeline — see test_resume.py for the v2 video-order test.
"""
import json
from pathlib import Path

import pytest

from app import graph as graph_module
from app.nodes import plan as plan_module
from app.nodes import topics as topics_module
from app.nodes import verify as verify_module
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


def test_resume_continues_topic_order_after_crash_without_redoing_completed_topic(
    tmp_path, monkeypatch
):
    output_dir = tmp_path / "output" / "some-book"

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["topic"]')

    plan_call_count = {"n": 0}

    def counting_plan_call_writer(prompt, **kw):
        plan_call_count["n"] += 1
        return json.dumps(
            [
                {
                    "title": "Topic One",
                    "level": 1,
                    "needs": [],
                    "sources": [{"video_id": "vid1", "chunk_index": 0}],
                },
                {
                    "title": "Topic Two",
                    "level": 1,
                    "needs": [],
                    "sources": [{"video_id": "vid2", "chunk_index": 0}],
                },
            ]
        )

    monkeypatch.setattr(plan_module, "call_writer", counting_plan_call_writer)

    write_call_order: list = []

    # graph.py now writes each topic's chapter concurrently, so "the Nth
    # call overall" no longer reliably means "topic two's call" -- target
    # the failure at topic two specifically (via the topic dict itself,
    # which run_write_topic receives directly) instead of a global call
    # count, same fix as test_resume.py's sibling tests.
    real_run_write_topic = write_module.run_write_topic
    topic_two_failed_once = {"done": False}

    def flaky_run_write_topic(topic, output_dir):
        write_call_order.append(topic["slug"])
        if topic["slug"] == "topic-two" and not topic_two_failed_once["done"]:
            topic_two_failed_once["done"] = True
            raise RuntimeError("simulated crash on topic 2's write")
        return real_run_write_topic(topic, output_dir)

    monkeypatch.setattr(write_module, "run_write_topic", flaky_run_write_topic)
    monkeypatch.setattr(graph_module, "run_write_topic", flaky_run_write_topic)
    monkeypatch.setattr(write_module, "call_writer", lambda prompt, **kw: "## Notes\n\nSynthesized.")
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    with pytest.raises(RuntimeError, match="simulated crash on topic 2"):
        graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    assert plan_call_count["n"] == 1
    assert len(write_call_order) == 2
    assert (output_dir / "work" / "notes" / "topic_topic-one.md").exists()
    assert not (output_dir / "work" / "notes" / "topic_topic-two.md").exists()

    pdf_path = graph_module.resume_book(output_dir)

    assert pdf_path == output_dir / "book.pdf"
    assert pdf_path.exists()
    assert (output_dir / "work" / "notes" / "topic_topic-two.md").exists()

    # Resume must not re-run plan (LLM merge call) or redo topic one's write.
    assert plan_call_count["n"] == 1
    assert len(write_call_order) == 3  # only topic two's write was retried

    main_tex = (output_dir / "chapters" / "main.tex").read_text(encoding="utf-8")
    assert r"\input{topic-one}" in main_tex
    assert r"\input{topic-two}" in main_tex


def test_resume_topic_order_after_crash_mid_refine_does_not_reverify_a_passed_topic(
    tmp_path, monkeypatch
):
    """sprints/v5 Task 7: a topic that already passed judge verification
    must not be re-verified (or re-written) on --resume.
    """
    output_dir = tmp_path / "output" / "some-book"

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["topic"]')
    monkeypatch.setattr(
        plan_module,
        "call_writer",
        lambda prompt, **kw: json.dumps(
            [
                {
                    "title": "Topic One",
                    "level": 1,
                    "needs": [],
                    "sources": [{"video_id": "vid1", "chunk_index": 0}],
                },
                {
                    "title": "Topic Two",
                    "level": 1,
                    "needs": [],
                    "sources": [{"video_id": "vid2", "chunk_index": 0}],
                },
            ]
        ),
    )

    write_call_order: list = []

    # graph.py now writes each topic's chapter concurrently -- same fix as
    # the sibling test above: target topic two specifically instead of a
    # global call count.
    real_run_write_topic = write_module.run_write_topic
    topic_two_failed_once = {"done": False}

    def flaky_run_write_topic(topic, output_dir):
        write_call_order.append(topic["slug"])
        if topic["slug"] == "topic-two" and not topic_two_failed_once["done"]:
            topic_two_failed_once["done"] = True
            raise RuntimeError("simulated crash on topic 2's write")
        return real_run_write_topic(topic, output_dir)

    monkeypatch.setattr(write_module, "run_write_topic", flaky_run_write_topic)
    monkeypatch.setattr(graph_module, "run_write_topic", flaky_run_write_topic)
    monkeypatch.setattr(write_module, "call_writer", lambda prompt, **kw: "## Notes\n\nSynthesized.")

    judge_call_count = {"n": 0}

    def counting_judge_call_writer(prompt, **kw):
        judge_call_count["n"] += 1
        return '{"score": 9, "feedback": "great"}'

    monkeypatch.setattr(verify_module, "call_writer", counting_judge_call_writer)
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    with pytest.raises(RuntimeError, match="simulated crash on topic 2"):
        graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    assert len(write_call_order) == 2
    assert judge_call_count["n"] == 1  # only topic one was verified before the crash

    graph_module.resume_book(output_dir)

    assert len(write_call_order) == 3
    assert judge_call_count["n"] == 2  # topic one not re-verified; topic two verified once
