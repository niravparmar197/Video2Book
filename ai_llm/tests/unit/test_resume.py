"""Unit tests for app.graph's --resume path (Task 9).

Simulates a crash mid-run (after fetch/chunk/topics have completed but
before write/render finish) by raising inside the write node's LLM call,
then verifies resume_book() continues from the SqliteSaver checkpoint
without re-fetching captions, re-chunking, or re-calling the topics LLM.
BOOK_ORDER=video is forced for every test in this file (v2 video-order
resume behavior) — see test_resume_topic_order.py for the v3 topic-order
resume test.
"""
from pathlib import Path

import pytest

from app import graph as graph_module
from app.nodes import topics as topics_module
from app.nodes import verify as verify_module
from app.nodes import write as write_module
from app.youtube import VideoInfo


@pytest.fixture(autouse=True)
def _force_video_order(monkeypatch):
    monkeypatch.setenv("BOOK_ORDER", "video")


SAMPLE_VTT = (
    "WEBVTT\n\n"
    "00:00:00.000 --> 00:00:02.500\n"
    "Hello and welcome to this video about neural networks.\n"
)

TEST_URL = "https://www.youtube.com/watch?v=aircAruvnKk"


def _fake_compile_chapter(tex_path, **kwargs):
    pdf_path = Path(tex_path).with_suffix(".pdf")
    pdf_path.write_bytes(b"%PDF-fake")
    return pdf_path


def _make_fake_run_fetch_playlist(call_log):
    def _fake_run_fetch_playlist(url, output_dir):
        call_log.append(url)
        output_dir = Path(output_dir)
        captions_dir = output_dir / "work" / "captions"
        captions_dir.mkdir(parents=True, exist_ok=True)
        captions_path = captions_dir / "aircAruvnKk.en.vtt"
        captions_path.write_text(SAMPLE_VTT, encoding="utf-8")
        return [
            VideoInfo(
                video_id="aircAruvnKk",
                title="But what is a neural network?",
                duration_seconds=150,
                url=url,
                captions_path=str(captions_path),
            )
        ]

    return _fake_run_fetch_playlist


def _make_counting_wrapper(real_fn, call_log):
    def _wrapped(*args, **kwargs):
        call_log.append(args)
        return real_fn(*args, **kwargs)

    return _wrapped


def test_resume_continues_after_a_crash_without_redoing_completed_steps(tmp_path, monkeypatch):
    output_dir = tmp_path / "output" / "some-book"

    fetch_calls: list = []
    chunk_calls: list = []
    topics_calls: list = []
    write_call_count = {"n": 0}

    monkeypatch.setattr(
        graph_module, "run_fetch_playlist", _make_fake_run_fetch_playlist(fetch_calls)
    )
    monkeypatch.setattr(
        graph_module, "run_chunk", _make_counting_wrapper(graph_module.run_chunk, chunk_calls)
    )

    def counting_topics_call_writer(prompt, **kw):
        topics_calls.append(prompt)
        return '["neural networks"]'

    monkeypatch.setattr(topics_module, "call_writer", counting_topics_call_writer)

    def flaky_write_call_writer(prompt, **kw):
        write_call_count["n"] += 1
        if write_call_count["n"] == 1:
            raise RuntimeError("simulated crash before write completes")
        return "## Neural Networks\n\nNotes."

    monkeypatch.setattr(write_module, "call_writer", flaky_write_call_writer)
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    with pytest.raises(RuntimeError, match="simulated crash"):
        graph_module.run_book(TEST_URL, output_dir)

    # fetch/chunk/topics already completed and checkpointed before the crash.
    assert len(fetch_calls) == 1
    assert len(chunk_calls) == 1
    assert len(topics_calls) == 1
    assert (output_dir / "work" / "topics" / "aircAruvnKk_000.json").exists()
    assert not (output_dir / "work" / "notes" / "aircAruvnKk.md").exists()

    pdf_path = graph_module.resume_book(output_dir)

    assert pdf_path == output_dir / "book.pdf"
    assert pdf_path.exists()
    assert (output_dir / "work" / "notes" / "aircAruvnKk.md").exists()

    # Resume must not re-fetch, re-chunk, or re-call the topics LLM.
    assert len(fetch_calls) == 1
    assert len(chunk_calls) == 1
    assert len(topics_calls) == 1
    # write is retried exactly once on resume (first call crashed, second succeeded).
    assert write_call_count["n"] == 2


def test_resume_continues_using_the_same_injected_checkpointer(tmp_path, monkeypatch):
    """sprints/v7 Task 3: resume_book must accept the same caller-supplied
    checkpointer the interrupted run_book call used, instead of only ever
    reading from a SqliteSaver file on disk."""
    from langgraph.checkpoint.memory import InMemorySaver

    output_dir = tmp_path / "output" / "some-book"
    saver = InMemorySaver()

    monkeypatch.setattr(
        graph_module, "run_fetch_playlist", _make_fake_run_fetch_playlist([])
    )

    def counting_topics_call_writer(prompt, **kw):
        return '["neural networks"]'

    monkeypatch.setattr(topics_module, "call_writer", counting_topics_call_writer)

    write_call_count = {"n": 0}

    def flaky_write_call_writer(prompt, **kw):
        write_call_count["n"] += 1
        if write_call_count["n"] == 1:
            raise RuntimeError("simulated crash before write completes")
        return "## Neural Networks\n\nNotes."

    monkeypatch.setattr(write_module, "call_writer", flaky_write_call_writer)
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    with pytest.raises(RuntimeError, match="simulated crash"):
        graph_module.run_book(TEST_URL, output_dir, checkpointer=saver)

    assert not (output_dir / "graph_state.sqlite").exists()

    pdf_path = graph_module.resume_book(output_dir, checkpointer=saver)

    assert pdf_path.exists()
    assert not (output_dir / "graph_state.sqlite").exists()
    assert write_call_count["n"] == 2


def test_resume_continues_playlist_after_crash_without_redoing_completed_video(
    tmp_path, monkeypatch
):
    """A crash mid-playlist (video 1 fully done, video 2's write fails) must
    not redo video 1's fetch/chunk/topics/write on --resume — only video 2's
    write is retried. Sprint v2 Task 8.
    """
    output_dir = tmp_path / "output" / "some-book"
    playlist_url = "https://www.youtube.com/playlist?list=PLfakeplaylist"

    fetch_calls: list = []
    chunk_calls: list = []
    topics_call_count = {"n": 0}
    write_call_order: list = []

    def fake_run_fetch_playlist(url, out_dir):
        fetch_calls.append(url)
        out_dir = Path(out_dir)
        captions_dir = out_dir / "work" / "captions"
        captions_dir.mkdir(parents=True, exist_ok=True)
        videos = []
        for video_id in ("vid1", "vid2"):
            captions_path = captions_dir / f"{video_id}.en.vtt"
            captions_path.write_text(SAMPLE_VTT, encoding="utf-8")
            videos.append(
                VideoInfo(
                    video_id=video_id,
                    title=f"Title {video_id}",
                    duration_seconds=150,
                    url=url,
                    captions_path=str(captions_path),
                )
            )
        return videos

    monkeypatch.setattr(graph_module, "run_fetch_playlist", fake_run_fetch_playlist)
    monkeypatch.setattr(
        graph_module, "run_chunk", _make_counting_wrapper(graph_module.run_chunk, chunk_calls)
    )

    def counting_topics_call_writer(prompt, **kw):
        topics_call_count["n"] += 1
        return '["neural networks"]'

    monkeypatch.setattr(topics_module, "call_writer", counting_topics_call_writer)

    def flaky_write_call_writer(prompt, **kw):
        write_call_order.append(prompt)
        # 1st call (video1) succeeds; 2nd call (video2, pre-crash) fails;
        # 3rd call (video2, on resume) succeeds.
        if len(write_call_order) == 2:
            raise RuntimeError("simulated crash on video 2's write")
        return "## Neural Networks\n\nNotes."

    monkeypatch.setattr(write_module, "call_writer", flaky_write_call_writer)
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    with pytest.raises(RuntimeError, match="simulated crash on video 2"):
        graph_module.run_book(playlist_url, output_dir)

    # video1 fully completed and was checkpointed before the crash.
    assert len(fetch_calls) == 1
    assert len(chunk_calls) == 2  # one run_chunk call per video
    assert topics_call_count["n"] == 2  # both videos' single chunk succeeded
    assert len(write_call_order) == 2  # video1 succeeded, video2 failed
    assert (output_dir / "work" / "notes" / "vid1.md").exists()
    assert not (output_dir / "work" / "notes" / "vid2.md").exists()

    pdf_path = graph_module.resume_book(output_dir)

    assert pdf_path == output_dir / "book.pdf"
    assert pdf_path.exists()
    assert (output_dir / "work" / "notes" / "vid2.md").exists()

    # Resume must not re-fetch, re-chunk, or re-call the topics LLM for
    # either video, and must not redo video1's already-cached write.
    assert len(fetch_calls) == 1
    assert len(chunk_calls) == 2
    assert topics_call_count["n"] == 2
    assert len(write_call_order) == 3  # only video2's write was retried

    main_tex = (output_dir / "chapters" / "main.tex").read_text(encoding="utf-8")
    assert r"\input{vid1}" in main_tex
    assert r"\input{vid2}" in main_tex


def test_resume_after_crash_mid_refine_does_not_reverify_a_passed_chunk(tmp_path, monkeypatch):
    """sprints/v5 Task 7: a chunk that already passed judge verification
    must not be re-verified (or re-written) on --resume — only the chunk
    that hadn't finished refining yet is retried.
    """
    output_dir = tmp_path / "output" / "some-book"
    playlist_url = "https://www.youtube.com/playlist?list=PLfakeplaylist"

    def fake_run_fetch_playlist(url, out_dir):
        out_dir = Path(out_dir)
        captions_dir = out_dir / "work" / "captions"
        captions_dir.mkdir(parents=True, exist_ok=True)
        videos = []
        for video_id in ("vid1", "vid2"):
            captions_path = captions_dir / f"{video_id}.en.vtt"
            captions_path.write_text(SAMPLE_VTT, encoding="utf-8")
            videos.append(
                VideoInfo(
                    video_id=video_id,
                    title=f"Title {video_id}",
                    duration_seconds=150,
                    url=url,
                    captions_path=str(captions_path),
                )
            )
        return videos

    monkeypatch.setattr(graph_module, "run_fetch_playlist", fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')

    write_call_order: list = []

    def flaky_write_call_writer(prompt, **kw):
        write_call_order.append(prompt)
        # 1st call (video1) succeeds; 2nd call (video2, pre-crash) fails;
        # 3rd call (video2, on resume) succeeds.
        if len(write_call_order) == 2:
            raise RuntimeError("simulated crash on video 2's write")
        return "## Neural Networks\n\nNotes."

    monkeypatch.setattr(write_module, "call_writer", flaky_write_call_writer)

    judge_call_count = {"n": 0}

    def counting_judge_call_writer(prompt, **kw):
        judge_call_count["n"] += 1
        return '{"score": 9, "feedback": "great"}'

    monkeypatch.setattr(verify_module, "call_writer", counting_judge_call_writer)
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    with pytest.raises(RuntimeError, match="simulated crash on video 2"):
        graph_module.run_book(playlist_url, output_dir)

    # video1 wrote once and was verified (judged) once before the crash.
    assert len(write_call_order) == 2
    assert judge_call_count["n"] == 1
    assert (output_dir / "work" / "notes" / "vid1.md").exists()

    graph_module.resume_book(output_dir)

    # Resume must not redo video1's already-passed write+verify -- only
    # video2's write (and its one judge call) happen.
    assert len(write_call_order) == 3
    assert judge_call_count["n"] == 2
    assert (output_dir / "work" / "notes" / "vid2.md").exists()


def test_resume_without_a_prior_checkpoint_raises(tmp_path):
    output_dir = tmp_path / "output" / "never-started"

    with pytest.raises(FileNotFoundError):
        graph_module.resume_book(output_dir)
