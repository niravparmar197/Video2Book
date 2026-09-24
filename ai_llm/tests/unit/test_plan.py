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
