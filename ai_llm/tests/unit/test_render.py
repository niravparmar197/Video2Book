"""Unit tests for app.nodes.render — table/diagram/chart rendering.

No real Graphviz `dot` subprocess call (mocked); matplotlib chart
rendering runs for real (fast, in-process, no subprocess).
"""
from pathlib import Path

import pytest

from app.nodes import render as render_node


def test_render_table_produces_escaped_latex_tabular():
    data = {
        "headers": ["Layer", "Size"],
        "rows": [["Input", "784"], ["Output & More", "10"]],
    }

    tex = render_node.render_table(data)

    assert r"\begin{tabular}" in tex
    assert r"\end{tabular}" in tex
    assert r"\toprule" in tex
    assert r"\midrule" in tex
    assert r"\bottomrule" in tex
    assert r"\textbf{Layer} & \textbf{Size}" in tex
    assert r"Output \& More & 10" in tex


def test_render_table_empty_rows_still_valid():
    tex = render_node.render_table({"headers": ["A"], "rows": []})

    assert r"\begin{tabular}{l}" in tex
    assert r"\begin{tabular}" in tex
    assert r"\end{tabular}" in tex


class _FakeCompletedProcess:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_render_diagram_invokes_dot_with_expected_args(tmp_path):
    captured = {}

    def fake_runner(args, **kwargs):
        captured["args"] = args
        captured["input"] = kwargs.get("input")
        Path(args[args.index("-o") + 1]).write_bytes(b"fake-png")
        return _FakeCompletedProcess(returncode=0)

    output_path = tmp_path / "diagram.png"
    result_path = render_node.render_diagram(
        {"nodes": ["Input", "Output"], "edges": [["Input", "Output"]]},
        output_path,
        runner=fake_runner,
    )

    assert result_path == output_path
    assert result_path.exists()
    args = captured["args"]
    assert args[0] == "dot"
    assert "-Tpng" in args
    assert '"Input" -> "Output";' in captured["input"]


def test_render_diagram_raises_on_dot_failure(tmp_path):
    def fake_runner(args, **kwargs):
        return _FakeCompletedProcess(returncode=1, stderr="syntax error")

    with pytest.raises(RuntimeError, match="graphviz dot failed"):
        render_node.render_diagram(
            {"nodes": ["A"], "edges": []}, tmp_path / "out.png", runner=fake_runner
        )


def test_render_chart_produces_a_real_png(tmp_path):
    output_path = tmp_path / "chart.png"

    result_path = render_node.render_chart(
        {
            "type": "bar",
            "title": "Neurons per layer",
            "categories": ["Input", "Hidden", "Output"],
            "values": [784, 16, 10],
        },
        output_path,
    )

    assert result_path == output_path
    assert result_path.exists()
    assert result_path.read_bytes().startswith(b"\x89PNG")
    assert result_path.stat().st_size > 0
