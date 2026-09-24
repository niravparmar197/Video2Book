"""Unit tests for app.nodes.order — topological sort of merged topics."""
import json

from app.nodes import order as order_node


def _topic(title, level=1, needs=None, sources=None):
    return {"title": title, "level": level, "needs": needs or [], "sources": sources or []}


def test_order_topics_respects_needs_dependency():
    topics = [
        _topic("Backpropagation", level=3, needs=["Gradient Descent"]),
        _topic("Gradient Descent", level=2, needs=["Vectors"]),
        _topic("Vectors", level=1),
    ]

    ordered, log_lines = order_node.order_topics(topics)

    titles = [t["title"] for t in ordered]
    assert titles.index("Vectors") < titles.index("Gradient Descent")
    assert titles.index("Gradient Descent") < titles.index("Backpropagation")
    assert log_lines == []


def test_order_topics_ties_broken_by_level_then_earliest_source():
    topics = [
        _topic(
            "Harder Independent Topic",
            level=4,
            sources=[{"video_id": "vid2", "chunk_index": 0}],
        ),
        _topic(
            "Easier Independent Topic",
            level=1,
            sources=[{"video_id": "vid1", "chunk_index": 0}],
        ),
    ]
    video_order = {"vid1": 1, "vid2": 2}

    ordered, _ = order_node.order_topics(topics, video_order=video_order)

    assert [t["title"] for t in ordered] == ["Easier Independent Topic", "Harder Independent Topic"]


def test_order_topics_breaks_a_cycle_without_raising():
    topics = [
        _topic("Topic A", level=2, needs=["Topic B"]),
        _topic("Topic B", level=1, needs=["Topic A"]),
    ]

    ordered, log_lines = order_node.order_topics(topics)

    assert {t["title"] for t in ordered} == {"Topic A", "Topic B"}
    assert len(ordered) == 2
    assert len(log_lines) == 1
    assert "Cycle detected" in log_lines[0]


def test_order_topics_ignores_unresolvable_needs_reference():
    topics = [_topic("Solo Topic", level=1, needs=["Nonexistent Topic"])]

    ordered, log_lines = order_node.order_topics(topics)

    assert [t["title"] for t in ordered] == ["Solo Topic"]
    assert log_lines == []


def test_run_order_topics_writes_order_log_on_cycle(tmp_path):
    plan = [
        {"title": "Topic A", "level": 2, "needs": ["Topic B"], "sources": []},
        {"title": "Topic B", "level": 1, "needs": ["Topic A"], "sources": []},
    ]
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")

    ordered = order_node.run_order_topics(tmp_path)

    assert len(ordered) == 2
    log_content = (tmp_path / "order_log.txt").read_text(encoding="utf-8")
    assert "Cycle detected" in log_content

    ordered_payload = json.loads((tmp_path / "ordered_plan.json").read_text(encoding="utf-8"))
    assert len(ordered_payload) == 2


def test_run_order_topics_uses_videos_json_for_tiebreak(tmp_path):
    plan = [
        {
            "title": "Second In Playlist",
            "level": 1,
            "needs": [],
            "sources": [{"video_id": "vid2", "chunk_index": 0}],
        },
        {
            "title": "First In Playlist",
            "level": 1,
            "needs": [],
            "sources": [{"video_id": "vid1", "chunk_index": 0}],
        },
    ]
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    videos = [
        {"video_id": "vid1", "playlist_index": 1},
        {"video_id": "vid2", "playlist_index": 2},
    ]
    (tmp_path / "videos.json").write_text(json.dumps(videos), encoding="utf-8")

    ordered = order_node.run_order_topics(tmp_path)

    assert [t["title"] for t in ordered] == ["First In Playlist", "Second In Playlist"]
