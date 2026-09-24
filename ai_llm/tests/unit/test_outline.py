"""Unit tests for app.nodes.outline — the video-order book plan.

BOOK_ORDER=video only this sprint: one chapter per video, in playlist
order, with stable chapter:<video_id> ids. No LLM/network calls.
"""
import json

from app.nodes import outline as outline_node

VIDEOS = [
    {"video_id": "vid1", "title": "First Video"},
    {"video_id": "vid2", "title": "Second Video"},
    {"video_id": "vid3", "title": "Third Video"},
]


def test_run_outline_writes_chapters_in_playlist_order(tmp_path):
    chapters = outline_node.run_outline(VIDEOS, tmp_path)

    assert [c["video_id"] for c in chapters] == ["vid1", "vid2", "vid3"]
    assert [c["order"] for c in chapters] == [1, 2, 3]
    assert chapters[0]["id"] == "chapter:vid1"
    assert all(c["skip"] is False and c["locked"] is False for c in chapters)

    outline_json_path = tmp_path / "outline.json"
    assert outline_json_path.exists()
    payload = json.loads(outline_json_path.read_text(encoding="utf-8"))
    assert [c["video_id"] for c in payload] == ["vid1", "vid2", "vid3"]

    outline_md_path = tmp_path / "outline.md"
    assert outline_md_path.exists()
    md = outline_md_path.read_text(encoding="utf-8")
    assert "First Video" in md
    assert "Second Video" in md
    assert "Third Video" in md


def test_run_outline_ids_are_stable_across_reruns(tmp_path):
    first = outline_node.run_outline(VIDEOS, tmp_path)
    second = outline_node.run_outline(VIDEOS, tmp_path)

    assert [c["id"] for c in first] == [c["id"] for c in second]
    assert first == second


def test_run_outline_preserves_manual_skip_edit_on_rerun(tmp_path):
    outline_node.run_outline(VIDEOS, tmp_path)

    outline_json_path = tmp_path / "outline.json"
    payload = json.loads(outline_json_path.read_text(encoding="utf-8"))
    payload[1]["skip"] = True
    outline_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    rerun = outline_node.run_outline(VIDEOS, tmp_path)

    assert rerun[0]["skip"] is False
    assert rerun[1]["skip"] is True
    assert rerun[2]["skip"] is False
    # Re-running must not clobber the md review file's reflection of the edit either.
    md = (tmp_path / "outline.md").read_text(encoding="utf-8")
    assert "[skip]" in md


TOPICS = [
    {
        "title": "Vectors",
        "level": 1,
        "needs": [],
        "sources": [{"video_id": "vid1", "chunk_index": 0}],
        "order": 1,
    },
    {
        "title": "Linear Transformations",
        "level": 2,
        "needs": ["Vectors"],
        "sources": [
            {"video_id": "vid2", "chunk_index": 0},
            {"video_id": "vid3", "chunk_index": 1},
        ],
        "order": 2,
    },
]


def test_run_topic_outline_writes_chapters_in_given_order(tmp_path):
    chapters = outline_node.run_topic_outline(TOPICS, tmp_path)

    assert [c["title"] for c in chapters] == ["Vectors", "Linear Transformations"]
    assert chapters[0]["id"] == "chapter:vectors"
    assert chapters[1]["id"] == "chapter:linear-transformations"
    assert [c["order"] for c in chapters] == [1, 2]
    assert all(c["skip"] is False and c["locked"] is False for c in chapters)

    outline_json = json.loads((tmp_path / "outline.json").read_text(encoding="utf-8"))
    assert [c["id"] for c in outline_json] == ["chapter:vectors", "chapter:linear-transformations"]

    md = (tmp_path / "outline.md").read_text(encoding="utf-8")
    assert "Vectors" in md
    assert "Linear Transformations" in md


def test_run_topic_outline_dedupes_slug_collision(tmp_path):
    topics = [
        {"title": "Gradient Descent!", "level": 1, "needs": [], "sources": [], "order": 1},
        {"title": "Gradient Descent?", "level": 1, "needs": [], "sources": [], "order": 2},
    ]

    chapters = outline_node.run_topic_outline(topics, tmp_path)

    assert chapters[0]["id"] == "chapter:gradient-descent"
    assert chapters[1]["id"] == "chapter:gradient-descent-2"


def test_run_topic_outline_preserves_manual_skip_edit_on_rerun(tmp_path):
    outline_node.run_topic_outline(TOPICS, tmp_path)

    outline_json_path = tmp_path / "outline.json"
    payload = json.loads(outline_json_path.read_text(encoding="utf-8"))
    payload[0]["skip"] = True
    outline_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    rerun = outline_node.run_topic_outline(TOPICS, tmp_path)

    assert rerun[0]["skip"] is True
    assert rerun[1]["skip"] is False
