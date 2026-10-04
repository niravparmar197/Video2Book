"""Unit tests for app.eval -- the eval gate (no real LLM calls)."""
import json

import pytest

from app import eval as eval_module
from app.nodes import verify as verify_module


@pytest.fixture()
def eval_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_module, "_EVAL_DIR", tmp_path)
    monkeypatch.setattr(eval_module, "DATASET_PATH", tmp_path / "dataset.jsonl")
    monkeypatch.setattr(eval_module, "BASELINE_PATH", tmp_path / "baseline.json")
    monkeypatch.delenv("EVAL_DATASET_NAME", raising=False)
    return tmp_path


def _write_dataset(eval_dir, n=2):
    lines = [
        json.dumps({"id": f"v{i}", "genre": "lecture", "topics": ["A"], "transcript": "a cache is fast"})
        for i in range(n)
    ]
    (eval_dir / "dataset.jsonl").write_text("\n".join(lines), encoding="utf-8")


def _judge_scores(monkeypatch, score):
    monkeypatch.setattr(eval_module, "call_writer", lambda prompt, **kw: "## A\n> Key point: A cache is fast.")
    monkeypatch.setattr(
        eval_module, "run_verify", lambda t, n: verify_module.VerifyResult(score=score, feedback="ok")
    )


def test_first_run_becomes_the_baseline(eval_dir, monkeypatch):
    _write_dataset(eval_dir)
    _judge_scores(monkeypatch, 8)

    assert eval_module.main([]) == 0

    baseline = json.loads((eval_dir / "baseline.json").read_text(encoding="utf-8"))
    assert baseline["average"] == 8 and baseline["examples"] == 2


def test_a_drop_is_blocked_when_the_release_gate_is_on(eval_dir, monkeypatch):
    _write_dataset(eval_dir)
    (eval_dir / "baseline.json").write_text(json.dumps({"average": 8.0, "date": "d"}), encoding="utf-8")
    _judge_scores(monkeypatch, 6)
    monkeypatch.setenv("EVAL_ON_RELEASE", "true")

    assert eval_module.main([]) == 1
    assert json.loads((eval_dir / "baseline.json").read_text(encoding="utf-8"))["average"] == 8.0


def test_a_drop_only_warns_when_the_gate_is_off_and_a_pass_can_update_the_baseline(eval_dir, monkeypatch):
    _write_dataset(eval_dir)
    (eval_dir / "baseline.json").write_text(json.dumps({"average": 7.0, "date": "d"}), encoding="utf-8")
    monkeypatch.setenv("EVAL_ON_RELEASE", "false")

    _judge_scores(monkeypatch, 6)
    assert eval_module.main([]) == 0  # WARN

    _judge_scores(monkeypatch, 9)
    assert eval_module.main(["--update-baseline"]) == 0
    assert json.loads((eval_dir / "baseline.json").read_text(encoding="utf-8"))["average"] == 9


def test_no_examples_is_reported_not_scored(eval_dir):
    assert eval_module.main([]) == 1


def test_add_example_takes_a_books_first_chunk(eval_dir, tmp_path):
    book = tmp_path / "book"
    (book / "work" / "chunks").mkdir(parents=True)
    (book / "work" / "topics").mkdir(parents=True)
    (book / "work" / "chunks" / "vid1_000.json").write_text(
        json.dumps({"video_id": "vid1", "chunk_index": 0, "text": "x" * 20_000}), encoding="utf-8"
    )
    (book / "work" / "topics" / "vid1_000.json").write_text(json.dumps({"topics": ["T"]}), encoding="utf-8")
    (book / "videos.json").write_text(json.dumps([{"video_id": "vid1", "title": "Ep 1"}]), encoding="utf-8")

    example = eval_module.add_example(book, "podcast")

    assert example["title"] == "Ep 1" and example["topics"] == ["T"] and example["genre"] == "podcast"
    assert len(example["transcript"]) == 15_000


def test_each_example_is_judged_twice_and_averaged(monkeypatch):
    scores = iter([6, 9])
    monkeypatch.setattr(eval_module, "call_writer", lambda prompt, **kw: "## A\n- x")
    monkeypatch.setattr(
        eval_module, "run_verify", lambda t, n: verify_module.VerifyResult(score=next(scores), feedback="f")
    )

    result = eval_module.score_example({"id": "v1", "genre": "lecture", "topics": [], "transcript": "t"})

    assert result["score"] == 7.5


def test_a_changed_dataset_starts_a_new_baseline_instead_of_comparing(eval_dir, monkeypatch):
    _write_dataset(eval_dir, n=3)
    (eval_dir / "baseline.json").write_text(
        json.dumps({"average": 9.0, "date": "d", "dataset": "other,examples"}), encoding="utf-8"
    )
    _judge_scores(monkeypatch, 5)
    monkeypatch.setenv("EVAL_ON_RELEASE", "true")

    assert eval_module.main([]) == 0  # not BLOCKED: nothing comparable

    baseline = json.loads((eval_dir / "baseline.json").read_text(encoding="utf-8"))
    assert baseline["average"] == 5 and baseline["dataset"] == "v0,v1,v2"
