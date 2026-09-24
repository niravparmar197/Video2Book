"""Unit tests for app.cache — skip a step whose output already exists."""
from app.cache import run_cached


def test_run_cached_calls_compute_when_output_missing(tmp_path):
    output_path = tmp_path / "out.json"
    calls = []

    def compute():
        calls.append(1)
        output_path.write_text("done", encoding="utf-8")

    result = run_cached(output_path, compute)

    assert result == output_path
    assert calls == [1]
    assert output_path.read_text(encoding="utf-8") == "done"


def test_run_cached_skips_compute_when_output_exists(tmp_path):
    output_path = tmp_path / "out.json"
    output_path.write_text("already here", encoding="utf-8")
    calls = []

    def compute():
        calls.append(1)
        output_path.write_text("overwritten", encoding="utf-8")

    result = run_cached(output_path, compute)

    assert result == output_path
    assert calls == []
    assert output_path.read_text(encoding="utf-8") == "already here"
