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
    "Hello and welcome to this video about neural networks and gradient descent.\n"
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


def test_get_warnings_returns_empty_list_before_any_run(tmp_path):
    assert graph_module.get_warnings(tmp_path / "output") == []


def test_run_book_persists_node_degradation_warnings_to_disk(tmp_path, monkeypatch):
    """sprints/v11: a node's logger.warning() (e.g. topics.py's "no usable
    JSON array" degrade-to-empty-list path) previously only reached
    stdout/worker logs. run_book must now also persist it to
    warnings.jsonl so a caller (backend/'s /events stream) can surface it.
    """
    output_dir = tmp_path / "output" / "some-book"

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    # Never a valid JSON array -> topics.py exhausts its retry and logs the
    # warning this test is checking for.
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: "not json")
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    warnings = graph_module.get_warnings(output_dir)
    assert len(warnings) >= 1
    assert any("produced no usable JSON array" in w["message"] for w in warnings)
    assert all({"ts", "logger", "message"} <= w.keys() for w in warnings)


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
        "percent": 0,
        "elapsed_seconds": 0,
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
    assert progress["percent"] == round(5 / 9 * 100)  # 5 of 9 video-order nodes done
    assert progress["elapsed_seconds"] >= 0


def test_get_progress_reports_frames_done_and_topics_pending_when_only_topics_fails(
    tmp_path, monkeypatch
):
    """sprints/v10 Task 2: frames and topics are parallel branches off
    `chunk` (sprints/v10 Task 1) -- when topics raises while frames has
    already succeeded, LangGraph commits each parallel task's checkpoint
    write independently (confirmed empirically, not superstep-atomically),
    so `frames` must report as completed and only `topics` as still
    pending/current -- not both stuck as "next" and not frames wrongly
    swept into "not yet reached" by the min-pending-index boundary logic.
    """
    from langgraph.checkpoint.memory import InMemorySaver

    output_dir = tmp_path / "output" / "some-book"
    saver = InMemorySaver()
    monkeypatch.setenv("VIDEO_MODE", "stream")

    def fake_run_frames(video_id, video_url, chunk, out_dir, **kwargs):
        frames_path = Path(out_dir) / "work" / "frames" / f"{video_id}_{chunk['chunk_index']:03d}.json"
        frames_path.parent.mkdir(parents=True, exist_ok=True)
        frames_path.write_text('{"video_id": "%s", "chunk_index": 0, "frames": []}' % video_id)
        return frames_path

    def boom(prompt, **kw):
        raise RuntimeError("simulated crash in topics")

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(graph_module, "run_frames", fake_run_frames)
    monkeypatch.setattr(topics_module, "call_writer", boom)

    with pytest.raises(RuntimeError, match="simulated crash in topics"):
        graph_module.run_book(TEST_PLAYLIST_URL, output_dir, checkpointer=saver)

    progress = graph_module.get_progress(output_dir, saver, book_order="video", phase="render")

    assert progress["completed_nodes"] == ["fetch", "check_budget", "chunk", "frames"]
    assert progress["current_node"] == "topics"
    assert progress["next_nodes"] == ["topics"]


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
    assert progress["percent"] == 100
    assert progress["elapsed_seconds"] >= 0


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
        "percent": 0,
        "elapsed_seconds": 0,
    }


# --- get_chapter_progress (sprints/v9) ------------------------------------


def test_get_chapter_progress_returns_empty_list_before_outline_exists(tmp_path):
    assert graph_module.get_chapter_progress(tmp_path / "output") == []


def test_get_chapter_progress_reports_pending_done_and_not_passed_chapters(tmp_path):
    output_dir = tmp_path / "output"
    (output_dir / "outline.json").parent.mkdir(parents=True, exist_ok=True)
    (output_dir / "outline.json").write_text(
        json.dumps(
            [
                {"id": "chapter:vid1", "video_id": "vid1", "title": "Video One", "order": 1},
                {"id": "chapter:vid2", "video_id": "vid2", "title": "Video Two", "order": 2},
                {"id": "chapter:vid3", "video_id": "vid3", "title": "Video Three", "order": 3},
            ]
        ),
        encoding="utf-8",
    )

    write_module.notes_output_path("vid1", output_dir).parent.mkdir(parents=True, exist_ok=True)
    write_module.notes_output_path("vid1", output_dir).write_text("notes", encoding="utf-8")
    write_module.chapter_status_path("vid1", output_dir).write_text(
        json.dumps({"score": 9, "attempts": 1, "passed": True}), encoding="utf-8"
    )

    write_module.notes_output_path("vid2", output_dir).write_text("notes", encoding="utf-8")
    write_module.chapter_status_path("vid2", output_dir).write_text(
        json.dumps({"score": 5, "attempts": 3, "passed": False}), encoding="utf-8"
    )

    # vid3: no notes/status files at all -- still pending.

    progress = graph_module.get_chapter_progress(output_dir)

    assert progress == [
        {
            "id": "chapter:vid1",
            "title": "Video One",
            "status": "done",
            "score": 9,
            "attempts": 1,
            "passed": True,
        },
        {
            "id": "chapter:vid2",
            "title": "Video Two",
            "status": "done",
            "score": 5,
            "attempts": 3,
            "passed": False,
        },
        {
            "id": "chapter:vid3",
            "title": "Video Three",
            "status": "pending",
            "score": None,
            "attempts": None,
            "passed": None,
        },
    ]


def test_get_chapter_progress_uses_topic_key_for_topic_mode_chapters(tmp_path):
    output_dir = tmp_path / "output"
    (output_dir).mkdir(parents=True, exist_ok=True)
    (output_dir / "outline.json").write_text(
        json.dumps(
            [{"id": "chapter:gradient-descent", "slug": "gradient-descent", "title": "GD", "order": 1}]
        ),
        encoding="utf-8",
    )

    write_module.notes_output_path("topic_gradient-descent", output_dir).parent.mkdir(
        parents=True, exist_ok=True
    )
    write_module.notes_output_path("topic_gradient-descent", output_dir).write_text(
        "notes", encoding="utf-8"
    )
    write_module.chapter_status_path("topic_gradient-descent", output_dir).write_text(
        json.dumps({"score": 8, "attempts": 2, "passed": True}), encoding="utf-8"
    )

    progress = graph_module.get_chapter_progress(output_dir)

    assert progress == [
        {
            "id": "chapter:gradient-descent",
            "title": "GD",
            "status": "done",
            "score": 8,
            "attempts": 2,
            "passed": True,
        }
    ]


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

    def fake_run_frames(video_id, video_url, chunk, out_dir, **kwargs):
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


def test_run_book_runs_frames_and_topics_concurrently_not_sequentially(
    tmp_path, monkeypatch
):
    """sprints/v10 Task 1: frames and topics are independent (frames writes
    no BookState key `topics`/`write` reads, and vice versa) and are wired
    as parallel branches off `chunk`, both converging before `render`.

    Asserting on total wall-clock time turned out flaky in practice here:
    a real SqliteSaver checkpointer (run_book's default when no
    checkpointer is injected) does real disk I/O per superstep, which adds
    variable overhead unrelated to whether frames/topics overlap. Instead,
    this asserts directly on *when* each side's first call starts,
    recorded via perf_counter() timestamps from inside the fakes -- if
    frames and topics are running as parallel branches (both become ready
    in the same superstep right after `chunk`), their first calls start
    within a few hundred ms of each other regardless of how much
    unrelated checkpoint/render overhead the rest of the run adds. A
    sequential chunk->frames->topics chain (the pre-sprints/v10 graph)
    would instead show topics starting ~0.3s *after* frames' first call
    finishes, not concurrently with it.
    """
    import time

    output_dir = tmp_path / "output" / "some-book"
    monkeypatch.setenv("VIDEO_MODE", "stream")

    start_times: dict[str, float] = {}
    t0 = time.perf_counter()

    def fake_run_frames(video_id, video_url, chunk, out_dir, **kwargs):
        start_times.setdefault("frames", time.perf_counter() - t0)
        time.sleep(0.3)
        frames_path = Path(out_dir) / "work" / "frames" / f"{video_id}_{chunk['chunk_index']:03d}.json"
        frames_path.parent.mkdir(parents=True, exist_ok=True)
        frames_path.write_text('{"video_id": "%s", "chunk_index": 0, "frames": []}' % video_id)
        return frames_path

    def slow_topics_call_writer(prompt, **kw):
        start_times.setdefault("topics", time.perf_counter() - t0)
        time.sleep(0.3)
        return '["neural networks"]'

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(graph_module, "run_frames", fake_run_frames)
    monkeypatch.setattr(topics_module, "call_writer", slow_topics_call_writer)
    monkeypatch.setattr(
        write_module, "call_writer", lambda prompt, **kw: "## Neural Networks\n\nNotes."
    )
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    graph_module.run_book(TEST_PLAYLIST_URL, output_dir)

    assert "frames" in start_times and "topics" in start_times
    gap = abs(start_times["frames"] - start_times["topics"])
    assert gap < 0.2, (
        f"frames started at {start_times['frames']:.3f}s, topics at "
        f"{start_times['topics']:.3f}s (gap {gap:.3f}s) -- expected both to "
        f"start together as parallel branches off chunk, not sequentially"
    )


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

    def counting_render_chapter(video_id, title, notes, out_dir, screenshots=None, index_terms=None, section_times=None):
        render_chapter_calls.append(video_id)
        return real_render_chapter(video_id, title, notes, out_dir, screenshots, index_terms, section_times)

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
    # Topic notes, not a formal book: no preface or topic-index filler pages.
    assert r"\input{topic_index}" not in main_tex
    assert "Preface" not in main_tex
    assert not (output_dir / "work" / "book_pass" / "preface.md").exists()

    glossary_tex = (output_dir / "chapters" / "glossary.tex").read_text(encoding="utf-8")
    assert "Gradient Descent" in glossary_tex
    assert "An optimization method." in glossary_tex


def test_concurrent_runs_each_capture_only_their_own_warnings(tmp_path):
    """With worker concurrency > 1, two books run in one process at once.
    Each run's warnings.jsonl must hold only that run's warnings -- the
    collector used to attach a handler per run to the shared "app.nodes"
    logger, which copied every book's warnings into every running book's
    file."""
    import logging
    import threading

    node_logger = logging.getLogger("app.nodes.test_isolation")
    both_inside = threading.Barrier(2)

    def run(name):
        with graph_module._collect_warnings(tmp_path / name):
            both_inside.wait(timeout=5)  # both collectors active at once
            node_logger.warning("warning from %s", name)
            both_inside.wait(timeout=5)

    threads = [threading.Thread(target=run, args=(n,)) for n in ("book_a", "book_b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for name, other in (("book_a", "book_b"), ("book_b", "book_a")):
        messages = [w["message"] for w in graph_module.get_warnings(tmp_path / name)]
        assert messages == [f"warning from {name}"], messages


def test_timed_node_records_seconds_per_node_and_merges_with_other_nodes(tmp_path):
    state = {"output_dir": str(tmp_path)}

    result = graph_module._timed("fetch", lambda s: {"ok": True})(state)
    graph_module._timed("chunk", lambda s: {})(state)

    assert result == {"ok": True}
    timings = graph_module.get_timings(tmp_path)
    assert set(timings) == {"fetch", "chunk"}
    assert all(seconds >= 0 for seconds in timings.values())


def test_timed_node_records_timing_even_when_the_node_fails(tmp_path):
    def boom(state):
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        graph_module._timed("write", boom)({"output_dir": str(tmp_path)})

    assert "write" in graph_module.get_timings(tmp_path)


def test_get_timings_is_empty_before_any_node_ran(tmp_path):
    assert graph_module.get_timings(tmp_path) == {}


def test_plan_node_skips_the_merge_llm_for_a_single_chunk_book(tmp_path, monkeypatch):
    topics_dir = tmp_path / "work" / "topics"
    topics_dir.mkdir(parents=True)
    (topics_dir / "vid1_000.json").write_text(
        json.dumps({"video_id": "vid1", "chunk_index": 0, "topics": ["A", "B"]}), encoding="utf-8"
    )

    def fail(*args, **kwargs):
        raise AssertionError("the merge LLM call must be skipped for a single-chunk book")

    monkeypatch.setattr(graph_module, "run_plan_topics", fail)

    graph_module._plan_node({"output_dir": str(tmp_path), "videos": [{"title": "My Video"}]})

    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    assert [entry["title"] for entry in plan] == ["My Video"]
    assert plan[0]["covers"] == ["A", "B"]


def test_topic_chapters_of_a_13_hour_video_total_13_hours_and_show_each_chunk_once():
    # 26 chunks (13h at 30 min). 40 chapters; each chapter draws on 1-2 chunks, so
    # many chunks feed several chapters -- the old per-chapter sum counted them all.
    chapters = []
    for index in range(40):
        first = index * 26 // 40
        sources = [{"video_id": "v", "chunk_index": first}]
        if index % 3 == 0:
            sources.append({"video_id": "v", "chunk_index": min(first + 1, 25)})
        chapters.append({"slug": f"c{index}", "sources": sources})
    used_chunks = {s["chunk_index"] for c in chapters for s in c["sources"]}

    result = graph_module._topic_chapter_hours_and_fresh_sources(chapters, chunk_minutes=30)

    total_hours = sum(hours for hours, _ in result)
    assert total_hours == pytest.approx(len(used_chunks) * 0.5)  # real time, not 20-40h
    assert total_hours <= 13
    shown = [source["chunk_index"] for _, fresh in result for source in fresh]
    assert len(shown) == len(set(shown)) == len(used_chunks)  # no chunk's screenshots repeated
    # And a 13h book now fits in one volume at the default VOLUME_HOURS.
    assert total_hours <= graph_module.load_settings().volume_hours


def test_map_parallel_runs_up_to_llm_parallel_calls_at_once(monkeypatch):
    import threading
    import time as time_module

    monkeypatch.setenv("LLM_PARALLEL_CALLS", "6")
    lock = threading.Lock()
    running = {"now": 0, "peak": 0}

    def work(item):
        with lock:
            running["now"] += 1
            running["peak"] = max(running["peak"], running["now"])
        time_module.sleep(0.05)
        with lock:
            running["now"] -= 1
        return item * 2

    assert graph_module._map_parallel(list(range(20)), work) == [i * 2 for i in range(20)]
    assert running["peak"] == 6
    running["peak"] = 0
    graph_module._map_parallel(list(range(20)), work, max_workers=2)
    assert running["peak"] == 2


def test_a_failed_screenshot_scan_does_not_fail_the_book(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_MODE", "stream")
    chunk_path = tmp_path / "work" / "chunks" / "vid1_000.json"
    chunk_path.parent.mkdir(parents=True)
    chunk_path.write_text(json.dumps({"video_id": "vid1", "chunk_index": 0}), encoding="utf-8")

    def blocked(*args, **kwargs):
        raise RuntimeError("Sign in to confirm you're not a bot")

    monkeypatch.setattr(graph_module, "run_frames", blocked)

    result = graph_module._frames_node(
        {
            "output_dir": str(tmp_path),
            "videos": [{"video_id": "vid1", "url": "u", "duration_seconds": 60}],
            "chunk_paths": {"vid1": [str(chunk_path)]},
        }
    )

    assert result == {}


def test_topics_node_uses_youtube_chapters_instead_of_the_llm(tmp_path, monkeypatch):
    chunk_path = tmp_path / "work" / "chunks" / "v1_000.json"
    chunk_path.parent.mkdir(parents=True)
    chunk_path.write_text(
        json.dumps({"video_id": "v1", "chunk_index": 0, "start_seconds": 0, "end_seconds": 1800, "text": "t"}),
        encoding="utf-8",
    )

    def fail(*args, **kwargs):
        raise AssertionError("chapters available: no topics LLM call")

    monkeypatch.setattr(graph_module, "run_topics", fail)
    chapters = [
        {"title": "Load Balancing", "start_seconds": 0, "end_seconds": 600},
        {"title": "Caching", "start_seconds": 600, "end_seconds": 1800},
    ]

    graph_module._topics_node(
        {
            "output_dir": str(tmp_path),
            "videos": [{"video_id": "v1", "title": "T", "chapters": chapters}],
            "chunk_paths": {"v1": [str(chunk_path)]},
        }
    )

    saved = json.loads((tmp_path / "work" / "topics" / "v1_000.json").read_text(encoding="utf-8"))
    assert saved["topics"] == ["Load Balancing", "Caching"]
