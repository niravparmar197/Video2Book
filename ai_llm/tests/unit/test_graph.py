"""Unit tests for app.graph — the fetch->chunk->topics->write->render graph.

No real network, LLM, or latexmk calls: run_fetch_playlist, call_writer
(topics and write), and compile_chapter are all monkeypatched with fakes.
BOOK_ORDER=video is forced for every test in this file (this file tests the
v2 video-order graph specifically) — see test_graph_topic_order.py for the
v3 topic-order graph.
"""
import json
from pathlib import Path

import pytest

from app import graph as graph_module
from app.nodes import book_pass as book_pass_module
from app.nodes import topics as topics_module
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

TEST_PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLfakeplaylist"

_PLAYLIST_VIDEOS = [
    ("vid1", "First Video"),
    ("vid2", "Second Video"),
]


def _fake_run_fetch_playlist(url, output_dir):
    output_dir = Path(output_dir)
    captions_dir = output_dir / "work" / "captions"
    captions_dir.mkdir(parents=True, exist_ok=True)

    videos = []
    for index, (video_id, title) in enumerate(_PLAYLIST_VIDEOS, start=1):
        captions_path = captions_dir / f"{video_id}.en.vtt"
        captions_path.write_text(SAMPLE_VTT, encoding="utf-8")
        videos.append(
            VideoInfo(
                video_id=video_id,
                title=title,
                duration_seconds=150,
                url=f"https://www.youtube.com/watch?v={video_id}",
                captions_path=str(captions_path),
                playlist_index=index,
            )
        )
    return videos


def _fake_compile_chapter(tex_path, **kwargs):
    pdf_path = Path(tex_path).with_suffix(".pdf")
    pdf_path.write_bytes(b"%PDF-fake")
    return pdf_path


def test_run_book_produces_book_pdf(tmp_path, monkeypatch):
    output_dir = tmp_path / "output" / "some-book"

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    pdf_path = graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    assert pdf_path == output_dir / "book.pdf"
    assert pdf_path.exists()
    for video_id, _ in _PLAYLIST_VIDEOS:
        assert (output_dir / "work" / "topics" / f"{video_id}_000.json").exists()
        assert (output_dir / "work" / "notes" / f"{video_id}.md").exists()
        assert (output_dir / "chapters" / f"{video_id}.tex").exists()


def test_run_book_defaults_to_sqlite_checkpoint_file_when_no_checkpointer_given(
    tmp_path, monkeypatch
):
    """sprints/v7 Task 3: omitting `checkpointer` must reproduce today's
    exact behavior byte-for-byte -- every existing caller (the CLI, every
    other test in this file) doesn't pass one."""
    output_dir = tmp_path / "output" / "some-book"

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    assert (output_dir / "graph_state.sqlite").exists()


def test_run_book_uses_injected_checkpointer_instead_of_sqlite_file(tmp_path, monkeypatch):
    """sprints/v7 Task 3: a caller-supplied checkpointer (e.g. backend/'s
    Postgres-backed one) is used as-is instead of the default SqliteSaver,
    and its lifecycle is the caller's responsibility -- run_book must not
    wrap it in a `with` block that would close it after one call."""
    from langgraph.checkpoint.memory import InMemorySaver

    output_dir = tmp_path / "output" / "some-book"

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    saver = InMemorySaver()
    pdf_path = graph_module.run_book(TEST_PLAYLIST_URL, output_dir, checkpointer=saver)

    assert pdf_path.exists()
    assert not (output_dir / "graph_state.sqlite").exists()
    # The injected saver really was used -- it now has a checkpoint for
    # this run's thread_id.
    config = {"configurable": {"thread_id": str(output_dir)}}
    assert saver.get_tuple(config) is not None


def test_get_progress_returns_empty_for_a_thread_that_never_ran(tmp_path):
    """sprints/v7 Task 4."""
    from langgraph.checkpoint.memory import InMemorySaver

    output_dir = tmp_path / "output" / "never-run-book"
    saver = InMemorySaver()

    progress = graph_module.get_progress(output_dir, saver, book_order="video")

    assert progress == {
        "completed_nodes": [],
        "current_node": None,
        "next_nodes": [],
        "step": 0,
    }


def test_get_progress_reflects_completed_and_next_node_mid_run(tmp_path, monkeypatch):
    """sprints/v7 Task 4: a run interrupted after 'topics' but before 'write'
    reports 'fetch'/'check_budget'/'chunk'/'frames'/'topics' as completed and
    'write' as the current/next node."""
    from langgraph.checkpoint.memory import InMemorySaver

    output_dir = tmp_path / "output" / "some-book"
    saver = InMemorySaver()

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')

    def boom(prompt, **kw):
        raise RuntimeError("simulated crash before write completes")

    monkeypatch.setattr(write_module, "call_writer", boom)

    with pytest.raises(RuntimeError, match="simulated crash"):
        graph_module.run_book(TEST_PLAYLIST_URL, output_dir, checkpointer=saver)

    progress = graph_module.get_progress(output_dir, saver, book_order="video", phase="render")

    assert progress["completed_nodes"] == ["fetch", "check_budget", "chunk", "frames", "topics"]
    assert progress["current_node"] == "write"
    assert progress["next_nodes"] == ["write"]
    assert progress["step"] > 0


def test_get_progress_reports_all_nodes_completed_after_a_full_run(tmp_path, monkeypatch):
    """sprints/v7 Task 4."""
    from langgraph.checkpoint.memory import InMemorySaver

    output_dir = tmp_path / "output" / "some-book"
    saver = InMemorySaver()

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    graph_module.run_book(TEST_PLAYLIST_URL, output_dir, checkpointer=saver)

    progress = graph_module.get_progress(output_dir, saver, book_order="video", phase="render")

    assert progress["current_node"] is None
    assert progress["next_nodes"] == []
    assert progress["completed_nodes"] == [
        "fetch",
        "check_budget",
        "chunk",
        "frames",
        "topics",
        "write",
        "outline",
        "book_pass",
        "render",
    ]


def test_get_progress_normalizes_the_transient_start_pending_state(monkeypatch):
    """sprints/v7 Task 8: a real end-to-end SSE integration test (backend/'s
    tests/integration/test_books_events_real_pipeline.py) caught get_progress
    misreporting LangGraph's transient "only START is pending" checkpoint --
    written the instant graph.invoke() begins, before any real node has run
    -- as "every node completed", since START ("__start__") isn't in
    node_order and fell into the same branch as a truly-finished next=()."""
    from langgraph.graph import START
    from langgraph.types import StateSnapshot

    class _FakeGraph:
        def get_state(self, config):
            return StateSnapshot(
                values={},
                next=(START,),
                config=config,
                metadata={"step": -1},
                created_at="2026-01-01T00:00:00Z",
                parent_config=None,
                tasks=(),
                interrupts=(),
            )

    monkeypatch.setattr(graph_module, "build_graph", lambda **kw: _FakeGraph())

    progress = graph_module.get_progress("some/output/dir", object(), book_order="video")

    assert progress == {
        "completed_nodes": [],
        "current_node": None,
        "next_nodes": [],
        "step": 0,
    }


def test_run_plan_stops_before_render(tmp_path, monkeypatch):
    output_dir = tmp_path / "output" / "some-book"

    render_calls = []

    def fake_compile_chapter(tex_path, **kwargs):
        render_calls.append(tex_path)
        pdf_path = Path(tex_path).with_suffix(".pdf")
        pdf_path.write_bytes(b"%PDF-fake")
        return pdf_path

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", fake_compile_chapter)

    videos, chapters = graph_module.run_plan(TEST_PLAYLIST_URL, output_dir)

    assert len(chapters) == len(_PLAYLIST_VIDEOS)
    assert [c["video_id"] for c in chapters] == [vid for vid, _ in _PLAYLIST_VIDEOS]
    assert [v["video_id"] for v in videos] == [vid for vid, _ in _PLAYLIST_VIDEOS]
    assert (output_dir / "outline.json").exists()
    assert (output_dir / "outline.md").exists()
    # render/compile must never be invoked by --plan-only.
    assert render_calls == []
    assert not (output_dir / "book.pdf").exists()
    assert not (output_dir / "chapters").exists()


def test_run_plan_uses_injected_checkpointer_instead_of_sqlite_file(tmp_path, monkeypatch):
    """sprints/v7 Task 3."""
    from langgraph.checkpoint.memory import InMemorySaver

    output_dir = tmp_path / "output" / "some-book"

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )

    saver = InMemorySaver()
    videos, chapters = graph_module.run_plan(TEST_PLAYLIST_URL, output_dir, checkpointer=saver)

    assert len(chapters) == len(_PLAYLIST_VIDEOS)
    assert not (output_dir / "graph_state.sqlite").exists()
    config = {"configurable": {"thread_id": str(output_dir)}}
    assert saver.get_tuple(config) is not None


def test_run_book_does_not_recall_llm_on_rerun(tmp_path, monkeypatch):
    output_dir = tmp_path / "output" / "some-book"

    topics_calls = []
    write_calls = []

    def fake_topics_call_writer(prompt, **kw):
        topics_calls.append(prompt)
        return '["neural networks"]'

    def fake_write_call_writer(prompt, **kw):
        write_calls.append(prompt)
        return "## Neural Networks\n\nNotes."

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", fake_topics_call_writer)
    monkeypatch.setattr(write_module, "call_writer", fake_write_call_writer)
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    graph_module.run_book(TEST_PLAYLIST_URL, output_dir)
    # One topics/write LLM call per video (each fake video is a single chunk).
    assert len(topics_calls) == len(_PLAYLIST_VIDEOS)
    assert len(write_calls) == len(_PLAYLIST_VIDEOS)

    # Re-running the same URL/output_dir must not re-call the LLM for
    # already-cached chunk topics/notes (cache.py, checked by file existence)
    # for either video.
    graph_module.run_book(TEST_PLAYLIST_URL, output_dir)
    assert len(topics_calls) == len(_PLAYLIST_VIDEOS)
    assert len(write_calls) == len(_PLAYLIST_VIDEOS)


def test_run_book_video_mode_stream_calls_run_frames_per_chunk(tmp_path, monkeypatch):
    """sprints/v4 Task 5: frames node runs per chunk when VIDEO_MODE=stream."""
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
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    assert sorted(frames_calls) == sorted((vid, 0) for vid, _ in _PLAYLIST_VIDEOS)
    for video_id, _ in _PLAYLIST_VIDEOS:
        assert (output_dir / "work" / "frames" / f"{video_id}_000.json").exists()


def test_run_book_video_mode_captions_only_never_calls_run_frames(tmp_path, monkeypatch):
    """sprints/v4 Task 5: frames node is a no-op when VIDEO_MODE=captions_only."""
    output_dir = tmp_path / "output" / "some-book"
    # conftest.py already defaults VIDEO_MODE=captions_only; set it
    # explicitly here so the intent is clear without depending on that.
    monkeypatch.setenv("VIDEO_MODE", "captions_only")

    frames_calls = []

    def fake_run_frames(*args, **kwargs):
        frames_calls.append(args)
        raise AssertionError("run_frames must not be called when VIDEO_MODE=captions_only")

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(graph_module, "run_frames", fake_run_frames)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    assert frames_calls == []
    assert not (output_dir / "work" / "frames").exists()


def test_run_book_video_order_never_creates_topic_mode_artifacts(tmp_path, monkeypatch):
    """BOOK_ORDER=video (sprints/v3 Task 7): v3's new plan/order nodes must
    be fully inert unless BOOK_ORDER=topic — zero regression to v2.
    """
    output_dir = tmp_path / "output" / "some-book"

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    assert not (output_dir / "plan.json").exists()
    assert not (output_dir / "ordered_plan.json").exists()
    assert not (output_dir / "order_log.txt").exists()

    outline = json.loads((output_dir / "outline.json").read_text(encoding="utf-8"))
    for chapter in outline:
        # topic-mode chapters have a "slug"/"sources" field; video-mode ones don't.
        assert "slug" not in chapter
        assert "sources" not in chapter
        assert chapter["id"] == f"chapter:{chapter['video_id']}"


def test_run_book_respects_outline_skip_flag_on_rerun(tmp_path, monkeypatch):
    output_dir = tmp_path / "output" / "some-book"

    render_chapter_calls = []
    real_render_chapter = graph_module.render_chapter

    def counting_render_chapter(video_id, title, notes, out_dir, screenshots=None, index_terms=None):
        render_chapter_calls.append(video_id)
        return real_render_chapter(video_id, title, notes, out_dir, screenshots, index_terms)

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)
    monkeypatch.setattr(graph_module, "render_chapter", counting_render_chapter)

    graph_module.run_book(TEST_PLAYLIST_URL, output_dir)
    assert sorted(render_chapter_calls) == sorted(vid for vid, _ in _PLAYLIST_VIDEOS)

    # Operator edits outline.json to skip the second video.
    outline_path = output_dir / "outline.json"
    payload = json.loads(outline_path.read_text(encoding="utf-8"))
    skip_video_id = _PLAYLIST_VIDEOS[1][0]
    keep_video_id = _PLAYLIST_VIDEOS[0][0]
    for chapter in payload:
        if chapter["video_id"] == skip_video_id:
            chapter["skip"] = True
    outline_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    render_chapter_calls.clear()
    graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    # The skipped chapter's render is never invoked again; the other still is.
    assert render_chapter_calls == [keep_video_id]

    main_tex = (output_dir / "chapters" / "main.tex").read_text(encoding="utf-8")
    assert f"\\input{{{keep_video_id}}}" in main_tex
    assert f"\\input{{{skip_video_id}}}" not in main_tex


def test_run_book_every_chapter_gets_notes_with_the_verify_loop_active(tmp_path, monkeypatch):
    """sprints/v5 Task 8 regression guard: the write+verify+refine loop
    must not leave any chapter without notes when the judge passes
    normally (the conftest default), for either video in the playlist.
    """
    output_dir = tmp_path / "output" / "some-book"

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    for video_id, _ in _PLAYLIST_VIDEOS:
        notes_path = output_dir / "work" / "notes" / f"{video_id}.md"
        assert notes_path.exists()
        assert notes_path.read_text(encoding="utf-8").strip() != ""


def test_run_book_splits_into_volumes_when_over_volume_hours(tmp_path, monkeypatch):
    """sprints/v6 Task 7: a playlist whose total video duration crosses
    VOLUME_HOURS produces book_vol1.pdf/book_vol2.pdf, not a single
    book.pdf.
    """
    output_dir = tmp_path / "output" / "some-book"
    monkeypatch.setenv("VOLUME_HOURS", "10")

    def fake_long_run_fetch_playlist(url, out_dir):
        out_dir = Path(out_dir)
        captions_dir = out_dir / "work" / "captions"
        captions_dir.mkdir(parents=True, exist_ok=True)
        videos = []
        for index, video_id in enumerate(("vid1", "vid2"), start=1):
            captions_path = captions_dir / f"{video_id}.en.vtt"
            captions_path.write_text(SAMPLE_VTT, encoding="utf-8")
            videos.append(
                VideoInfo(
                    video_id=video_id,
                    title=f"Title {video_id}",
                    duration_seconds=8 * 3600,  # 8 hours each; 16h total > 10h
                    url=url,
                    captions_path=str(captions_path),
                    playlist_index=index,
                )
            )
        return videos

    monkeypatch.setattr(graph_module, "run_fetch_playlist", fake_long_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    assert not (output_dir / "book.pdf").exists()
    assert (output_dir / "book_vol1.pdf").exists()
    assert (output_dir / "book_vol2.pdf").exists()
    assert (output_dir / "chapters" / "main_vol1.tex").exists()
    assert (output_dir / "chapters" / "main_vol2.tex").exists()


def test_run_book_stays_single_volume_when_under_volume_hours(tmp_path, monkeypatch):
    output_dir = tmp_path / "output" / "some-book"
    monkeypatch.setenv("VOLUME_HOURS", "10")

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    assert (output_dir / "book.pdf").exists()
    assert not (output_dir / "book_vol1.pdf").exists()


def test_run_book_raises_over_max_book_hours_without_force(tmp_path, monkeypatch):
    """sprints/v7 Task 2: a playlist over MAX_BOOK_HOURS refuses to proceed
    past fetch unless --force (run_book(force=True)) is passed.
    """
    output_dir = tmp_path / "output" / "some-book"
    monkeypatch.setenv("MAX_BOOK_HOURS", "0")  # fake videos are 150s each -> always over a 0h budget

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    with pytest.raises(graph_module.BudgetExceededError):
        graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    # Refused before chunking/writing ever started.
    assert not (output_dir / "work" / "notes").exists()


def test_run_book_proceeds_over_max_book_hours_with_force(tmp_path, monkeypatch):
    """sprints/v7 Task 2: --force (run_book(force=True)) reaches the fetch
    node's downstream work even when over MAX_BOOK_HOURS.
    """
    output_dir = tmp_path / "output" / "some-book"
    monkeypatch.setenv("MAX_BOOK_HOURS", "0")

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    pdf_path = graph_module.run_book(TEST_PLAYLIST_URL, output_dir, force=True)

    assert pdf_path.exists()
    for video_id, _ in _PLAYLIST_VIDEOS:
        assert (output_dir / "work" / "notes" / f"{video_id}.md").exists()


def test_run_book_raises_over_max_book_cost_usd_without_force(tmp_path, monkeypatch):
    """sprints/v7 Task 3: same gate as Task 2, driven by a forced non-zero
    cost estimate (always $0.00 today with the free-tier providers).
    """
    output_dir = tmp_path / "output" / "some-book"
    monkeypatch.setenv("MAX_BOOK_COST_USD", "1")
    monkeypatch.setattr(graph_module, "_estimate_total_cost_usd", lambda videos: 5.0)

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    with pytest.raises(graph_module.BudgetExceededError):
        graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    assert not (output_dir / "work" / "notes").exists()


def test_run_book_proceeds_over_max_book_cost_usd_with_force(tmp_path, monkeypatch):
    output_dir = tmp_path / "output" / "some-book"
    monkeypatch.setenv("MAX_BOOK_COST_USD", "1")
    monkeypatch.setattr(graph_module, "_estimate_total_cost_usd", lambda videos: 5.0)

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["neural networks"]')
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    pdf_path = graph_module.run_book(TEST_PLAYLIST_URL, output_dir, force=True)

    assert pdf_path.exists()


def test_run_book_wires_real_glossary_and_indexes_into_the_compiled_book(tmp_path, monkeypatch):
    """sprints/v6 Task 8: book_pass's real glossary/index-terms/preface
    output actually reaches the compiled main.tex, not just the inert
    conftest default.
    """
    output_dir = tmp_path / "output" / "some-book"

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: '["gradient descent"]')
    monkeypatch.setattr(
        write_module,
        "call_writer",
        lambda prompt, **kw: "## Gradient Descent\n\nGradient descent minimizes loss.",
    )

    def fake_book_pass_call_writer(prompt, **kw):
        # Each book_pass prompt ends with a distinct data-section label --
        # more reliable than generic keyword matching to tell them apart.
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
    assert "An optimization method." in glossary_tex
