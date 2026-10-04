"""Unit tests for app.nodes.plan — merging topics across the whole playlist.

No real LLM calls: app.nodes.plan.call_writer is monkeypatched.
"""
import json

import pytest

from app.nodes import plan as plan_node


def _write_topics_file(output_dir, video_id, chunk_index, topics):
    topics_dir = output_dir / "work" / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    path = topics_dir / f"{video_id}_{chunk_index:03d}.json"
    path.write_text(
        json.dumps({"video_id": video_id, "chunk_index": chunk_index, "topics": topics}),
        encoding="utf-8",
    )


def test_run_plan_topics_merges_paraphrased_duplicate_across_videos(tmp_path, monkeypatch):
    _write_topics_file(tmp_path, "vid1", 0, ["Gradient Descent Basics"])
    _write_topics_file(tmp_path, "vid2", 0, ["How Neural Nets Learn"])

    stubbed_response = json.dumps(
        [
            {
                "title": "Gradient Descent",
                "level": 2,
                "needs": [],
                "sources": [
                    {"video_id": "vid1", "chunk_index": 0},
                    {"video_id": "vid2", "chunk_index": 0},
                ],
            }
        ]
    )

    monkeypatch.setattr(plan_node, "call_writer", lambda prompt, **kw: stubbed_response)

    plan = plan_node.run_plan_topics(tmp_path)

    assert len(plan) == 1
    assert plan[0]["title"] == "Gradient Descent"
    assert {source["video_id"] for source in plan[0]["sources"]} == {"vid1", "vid2"}

    payload = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    assert payload == plan


def test_run_plan_topics_prompt_includes_every_video_and_chunk_topic(tmp_path, monkeypatch):
    _write_topics_file(tmp_path, "vid1", 0, ["Topic A"])
    _write_topics_file(tmp_path, "vid2", 0, ["Topic B"])

    captured = {}

    def fake_call_writer(prompt, **kw):
        captured["prompt"] = prompt
        return "[]"

    monkeypatch.setattr(plan_node, "call_writer", fake_call_writer)

    plan_node.run_plan_topics(tmp_path)

    assert "vid1" in captured["prompt"]
    assert "vid2" in captured["prompt"]
    assert "Topic A" in captured["prompt"]
    assert "Topic B" in captured["prompt"]


def test_run_plan_topics_retries_once_with_a_stricter_prompt_when_no_array_found(
    tmp_path, monkeypatch
):
    _write_topics_file(tmp_path, "vid1", 0, ["Topic A"])

    call_count = {"n": 0}

    def flaky_call_writer(prompt, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "Let me think about how to merge these topics first..."
        return json.dumps(
            [{"title": "Topic A", "level": 1, "needs": [], "sources": [
                {"video_id": "vid1", "chunk_index": 0}
            ]}]
        )

    monkeypatch.setattr(plan_node, "call_writer", flaky_call_writer)

    plan = plan_node.run_plan_topics(tmp_path)

    assert call_count["n"] == 2
    assert plan[0]["title"] == "Topic A"


def test_run_plan_topics_degrades_to_unmerged_plan_when_llm_never_yields_json(
    tmp_path, monkeypatch
):
    _write_topics_file(tmp_path, "vid1", 0, ["Topic A"])

    call_count = {"n": 0}

    def always_fails(prompt, **kw):
        call_count["n"] += 1
        return "I cannot comply with this request."

    monkeypatch.setattr(plan_node, "call_writer", always_fails)

    plan = plan_node.run_plan_topics(tmp_path)

    assert call_count["n"] == 2  # one retry, then degrade
    assert plan == [
        {
            "title": "Topic A",
            "level": 1,
            "needs": [],
            "sources": [{"video_id": "vid1", "chunk_index": 0}],
        }
    ]


def test_run_plan_topics_filters_filler_topics_before_prompt_and_degrade(
    tmp_path, monkeypatch
):
    _write_topics_file(
        tmp_path,
        "vid1",
        0,
        ["Gradient Descent Basics", "Welcome to StatQuest", "Links are in the description below"],
    )

    captured = {}

    def fake_call_writer(prompt, **kw):
        captured["prompt"] = prompt
        return "not json"

    monkeypatch.setattr(plan_node, "call_writer", fake_call_writer)

    plan = plan_node.run_plan_topics(tmp_path)

    assert "Welcome to StatQuest" not in captured["prompt"]
    assert "Links are in the description" not in captured["prompt"]
    assert "Gradient Descent Basics" in captured["prompt"]

    assert plan == [
        {
            "title": "Gradient Descent Basics",
            "level": 1,
            "needs": [],
            "sources": [{"video_id": "vid1", "chunk_index": 0}],
        }
    ]


def test_run_plan_topics_raises_instead_of_shipping_an_exploded_degraded_plan(
    tmp_path, monkeypatch
):
    # 15 chunks x 4 topics each = 60 raw topics, above the
    # max(20, 3 * 15) = 45 ceiling -- should raise instead of degrading.
    for i in range(15):
        _write_topics_file(
            tmp_path,
            "vid1",
            i,
            [f"topic {i} alpha", f"topic {i} beta", f"topic {i} gamma", f"topic {i} delta"],
        )

    monkeypatch.setattr(plan_node, "call_writer", lambda prompt, **kw: "not json")

    with pytest.raises(plan_node.PlanMergeFailedError):
        plan_node.run_plan_topics(tmp_path)

    assert not plan_node.plan_json_path(tmp_path).exists()


def test_run_single_chunk_plan_makes_one_chapter_covering_every_topic_without_an_llm_call(
    tmp_path, monkeypatch
):
    _write_topics_file(
        tmp_path, "vid1", 0, ["Gradient Descent", "Learning Rate", "welcome to my channel"]
    )

    def fail(prompt, **kw):
        raise AssertionError("a single-chunk plan must not call the LLM")

    monkeypatch.setattr(plan_node, "call_writer", fail)

    plan = plan_node.run_single_chunk_plan(tmp_path, "Intro to Optimization")

    assert plan == [
        {
            "title": "Intro to Optimization",
            "level": 1,
            "needs": [],
            "sources": [{"video_id": "vid1", "chunk_index": 0}],
            "covers": ["Gradient Descent", "Learning Rate"],
        }
    ]
    assert json.loads(plan_node.plan_json_path(tmp_path).read_text(encoding="utf-8")) == plan


def test_run_single_chunk_plan_returns_none_when_there_is_more_than_one_chunk(tmp_path):
    _write_topics_file(tmp_path, "vid1", 0, ["A"])
    _write_topics_file(tmp_path, "vid2", 0, ["B"])

    assert plan_node.run_single_chunk_plan(tmp_path, "Title") is None
    assert not plan_node.plan_json_path(tmp_path).exists()


def test_single_chunk_plan_does_not_use_an_unprintable_hindi_title(tmp_path):
    _write_topics_file(tmp_path, "vid1", 0, ["Rise of Moscow", "Ivan the Terrible"])

    plan = plan_node.run_single_chunk_plan(tmp_path, "सालों की कहानी")

    assert plan[0]["title"] == "Rise of Moscow"


def _write_chunk(output_dir, video_id, chunk_index, start, end):
    chunks_dir = output_dir / "work" / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    payload = {"chunk_index": chunk_index, "start_seconds": start, "end_seconds": end, "text": "x"}
    (chunks_dir / f"{video_id}_{chunk_index:03d}.json").write_text(json.dumps(payload), encoding="utf-8")


_DRIVE_CHAPTERS = [
    {"title": "Precap", "start_seconds": 0, "end_seconds": 153},
    {"title": "Requirements", "start_seconds": 153, "end_seconds": 213},
    {"title": "Where to store actual file?", "start_seconds": 213, "end_seconds": 387},
    {"title": "Quick note", "start_seconds": 387, "end_seconds": 410},
    {"title": "Upload File Flow HLD", "start_seconds": 410, "end_seconds": 1974},
    {"title": "Database Schema", "start_seconds": 1974, "end_seconds": None},
]


def test_youtube_chapter_plan_follows_the_creators_chapters_in_order(tmp_path):
    _write_chunk(tmp_path, "vid1", 0, 0.0, 1799.0)
    _write_chunk(tmp_path, "vid1", 1, 1800.0, 2700.0)
    video = {"video_id": "vid1", "duration_seconds": 2700, "chapters": _DRIVE_CHAPTERS}

    plan = plan_node.run_youtube_chapter_plan(tmp_path, [video], chunk_minutes=30)

    # The precap is dropped; the 23-second chapter is folded into the one before it.
    assert [entry["title"] for entry in plan] == [
        "Requirements", "Where to store actual file?", "Upload File Flow HLD", "Database Schema",
    ]
    assert plan[1]["time_range"] == [213.0, 410.0]
    assert plan[2]["sources"] == [
        {"video_id": "vid1", "chunk_index": 0}, {"video_id": "vid1", "chunk_index": 1},
    ]
    assert plan[3]["time_range"] == [1974.0, 2700.0]
    assert json.loads(plan_node.plan_json_path(tmp_path).read_text(encoding="utf-8")) == plan


def test_youtube_chapter_plan_is_skipped_without_usable_chapters(tmp_path):
    _write_chunk(tmp_path, "vid1", 0, 0.0, 1799.0)
    few = {"video_id": "vid1", "duration_seconds": 1800, "chapters": _DRIVE_CHAPTERS[:3]}
    huge = {
        "video_id": "vid1",
        "duration_seconds": 30000,
        "chapters": [
            {"title": f"Part {n}", "start_seconds": n * 10000, "end_seconds": (n + 1) * 10000} for n in range(3)
        ],
    }

    assert plan_node.run_youtube_chapter_plan(tmp_path, [few], 30) is None
    assert plan_node.run_youtube_chapter_plan(tmp_path, [huge], 30) is None
    assert plan_node.run_youtube_chapter_plan(tmp_path, [few, few], 30) is None
    assert not plan_node.plan_json_path(tmp_path).exists()
