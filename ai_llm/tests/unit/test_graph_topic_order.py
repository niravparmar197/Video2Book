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

SAMPLE_VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:02.500\nHello and welcome to this video about gradient descent.\n"

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
    # of BOOK_ORDER=topic. (The empty conftest stub means no glossary here.)
    assert input_lines == [r"\input{gradient-descent}"]


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

    def fake_run_frames(video_id, video_url, chunk, out_dir, **kwargs):
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


def test_run_book_topic_order_runs_frames_and_topics_concurrently(tmp_path, monkeypatch):
    """sprints/v10 Task 1: same parallel frames/topics wiring as the
    video-order graph (test_graph.py's matching test) -- frames is
    independent of topics/plan/order/outline/write/book_pass in topic mode
    too, and is wired as a parallel branch off `chunk`. Asserts on start-time
    overlap, not total wall-clock, for the same reason: real SqliteSaver
    checkpoint I/O adds variable overhead unrelated to whether the two
    branches overlap.
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
        return '["gradient descent"]'

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(graph_module, "run_frames", fake_run_frames)
    monkeypatch.setattr(topics_module, "call_writer", slow_topics_call_writer)
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

    assert "frames" in start_times and "topics" in start_times
    gap = abs(start_times["frames"] - start_times["topics"])
    assert gap < 0.2, (
        f"frames started at {start_times['frames']:.3f}s, topics at "
        f"{start_times['topics']:.3f}s (gap {gap:.3f}s) -- expected both to "
        f"start together as parallel branches off chunk, not sequentially"
    )


def test_run_book_topic_order_zero_topics_does_not_crash_at_compile(tmp_path, monkeypatch):
    """sprints/v11: a real production crash. When topics extraction
    degrades to an empty list for every chunk (topics.py's own documented,
    intentional crash-safety behavior when the LLM never returns a
    parseable array, even after a retry), the merged plan and outline end
    up empty too -- but book_pass still runs (it has no early-return for
    zero chapters) and produced a truthy book_pass dict, which the render
    node used to treat as "yes, render a topic index chapter" regardless
    of whether there was anything to put in it. Rendering
    \\begin{enumerate}\\end{enumerate} with zero \\item entries is a real
    LaTeX fatal error ("Something's wrong--perhaps a missing \\item"),
    caught live against a real video whose transcript was fine but whose
    topics-extraction LLM call degraded. This must not crash: an empty
    topic index chapter is simply omitted, same as glossary already does
    via has_glossary = bool(glossary_entries).
    """
    output_dir = tmp_path / "output" / "some-book"

    monkeypatch.setattr(graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(topics_module, "call_writer", lambda prompt, **kw: "[]")
    monkeypatch.setattr(plan_module, "call_writer", lambda prompt, **kw: "[]")

    def fake_book_pass_call_writer(prompt, **kw):
        if "Chapters covered, in order:" in prompt:
            return "This book has no chapters."
        if "Chapter notes:" in prompt:
            return "[]"
        if "Chapters:" in prompt:
            return "[]"
        raise AssertionError(f"unexpected book_pass prompt: {prompt[:200]}")

    monkeypatch.setattr(book_pass_module, "call_writer", fake_book_pass_call_writer)
    monkeypatch.setattr(graph_module, "compile_chapter", _fake_compile_chapter)

    # No write_module.call_writer mock: zero chapters means the write
    # step's loop never iterates, so it must never be called at all.
    def unexpected_write_call(prompt, **kw):
        raise AssertionError("write should never be called for zero chapters")

    monkeypatch.setattr(write_module, "call_writer", unexpected_write_call)

    graph_module.run_book(TEST_PLAYLIST_URL, output_dir)  # must not raise

    main_tex = (output_dir / "chapters" / "main.tex").read_text(encoding="utf-8")
    assert r"\input{topic_index}" not in main_tex
    assert not (output_dir / "chapters" / "topic_index.tex").exists()
    assert (output_dir / "book.pdf").exists()


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
    # Topic notes, not a formal book: no preface or topic-index filler pages.
    assert r"\input{topic_index}" not in main_tex
    assert "Preface" not in main_tex

    glossary_tex = (output_dir / "chapters" / "glossary.tex").read_text(encoding="utf-8")
    assert "Gradient Descent" in glossary_tex


def test_plan_node_does_not_rerun_when_plan_already_exists(tmp_path, monkeypatch):
    """The render phase re-runs the graph from START; the plan LLM call
    must be cache-skipped there, or it could produce a different plan than
    the outline the user already reviewed."""
    from app.nodes.plan import plan_json_path

    plan_path = plan_json_path(tmp_path)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text("[]", encoding="utf-8")

    def must_not_run(output_dir):
        raise AssertionError("plan must be cache-skipped when plan.json exists")

    monkeypatch.setattr(graph_module, "run_plan_topics", must_not_run)

    graph_module._plan_node({"output_dir": str(tmp_path)})


def test_write_node_tells_each_chapter_which_chapters_share_its_chunks(tmp_path, monkeypatch):
    seen = {}

    def fake_run_write_topic(topic, output_dir):
        seen[topic["title"]] = topic.get("other_chapters")
        path = graph_module.notes_output_path(f"topic_{topic['slug']}", output_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("## x\n", encoding="utf-8")
        return path

    monkeypatch.setattr(graph_module, "run_write_topic", fake_run_write_topic)
    chapters = [
        {"id": "a", "slug": "a", "title": "A", "skip": False, "sources": [{"video_id": "v", "chunk_index": 0}]},
        {"id": "b", "slug": "b", "title": "B", "skip": False, "sources": [{"video_id": "v", "chunk_index": 0}]},
        {"id": "c", "slug": "c", "title": "C", "skip": False, "sources": [{"video_id": "v", "chunk_index": 1}]},
    ]

    graph_module._write_topic_node({"output_dir": str(tmp_path), "chapters": chapters})

    assert seen == {"A": ["B"], "B": ["A"], "C": []}


def test_screenshots_follow_youtube_chapters_to_the_matching_book_chapter(tmp_path):
    # Real case: a system-design video's finished architecture drawing (44:15)
    # landed in the wrong chapter when screenshots went to the first chapter
    # of their 30-minute chunk.
    for slug in ("upload", "schema"):
        (tmp_path / f"{slug}.md").write_text("## Notes\nText.\n", encoding="utf-8")

    def shot(minutes):
        return {"asset_path": str(tmp_path / "assets" / "gd1" / f"{minutes}.jpg"), "timestamp_seconds": minutes * 60}

    chapters = [
        {"title": "Upload Flow High Level Design", "notes_path": str(tmp_path / "upload.md"), "sources": [],
         "screenshots": [shot(14), shot(44)]},
        {"title": "Database Schema", "notes_path": str(tmp_path / "schema.md"), "sources": [], "screenshots": []},
    ]
    videos = [{"video_id": "gd1", "chapters": [
        {"title": "Upload File Flow HLD", "start_seconds": 540, "end_seconds": 1719},
        {"title": "Database Schema", "start_seconds": 2428, "end_seconds": 2657},
    ]}]

    graph_module._place_screenshots_by_chapter_time(chapters, str(tmp_path), videos)

    assert [s["timestamp_seconds"] for s in chapters[0]["screenshots"]] == [14 * 60]
    assert [s["timestamp_seconds"] for s in chapters[1]["screenshots"]] == [44 * 60]


def test_youtube_chapter_titles_map_to_the_most_alike_book_chapter():
    owners = graph_module._youtube_chapter_owners(
        [{"title": "File Storage Strategy"}, {"title": "Upload Flow High Level Design"}],
        [{"title": "Where to store actual file?"}, {"title": "Upload File Flow HLD"}, {"title": "Precap"}],
    )

    assert owners == [0, 1, None]


def test_a_single_video_book_follows_the_videos_own_chapter_order():
    planned = [  # needs/level order
        {"title": "Functional Requirements", "sources": [{"video_id": "v", "chunk_index": 0}]},
        {"title": "Database Schema", "sources": [{"video_id": "v", "chunk_index": 1}]},
        {"title": "Upload Flow Design", "sources": [{"video_id": "v", "chunk_index": 0}]},
        {"title": "User Roles", "sources": [{"video_id": "v", "chunk_index": 0}]},  # no YouTube chapter
        {"title": "Download Flow Design", "sources": [{"video_id": "v", "chunk_index": 1}]},
    ]
    youtube_chapters = [
        {"title": "Functional Requirements", "start_seconds": 150, "end_seconds": 210},
        {"title": "Upload File Flow", "start_seconds": 540, "end_seconds": 1700},
        {"title": "Download File Flow", "start_seconds": 1970, "end_seconds": 2400},
        {"title": "Database Schema", "start_seconds": 2430, "end_seconds": 2650},
    ]

    ordered = graph_module._in_video_order(planned, youtube_chapters)

    assert [t["title"] for t in ordered] == [
        "Functional Requirements", "Upload Flow Design", "User Roles", "Download Flow Design", "Database Schema",
    ]
    assert [t["order"] for t in ordered] == [1, 2, 3, 4, 5]
