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

    # Full-width tabularx with wrapping columns after the first, so a long
    # cell can't run off the right edge of the page.
    assert r"\begin{tabularx}{\linewidth}{l>{\raggedright\arraybackslash}X}" in tex
    assert r"\end{tabularx}" in tex
    assert r"\toprule" in tex
    assert r"\midrule" in tex
    assert r"\bottomrule" in tex
    assert r"\rowcolor{V2BPrimary!12}" in tex
    assert r"\textbf{Layer} & \textbf{Size}" in tex
    assert r"Output \& More & 10" in tex


def test_render_table_empty_rows_still_valid():
    tex = render_node.render_table({"headers": ["A"], "rows": []})

    assert r"\begin{tabularx}{\linewidth}{>{\raggedright\arraybackslash}X}" in tex
    assert r"\end{tabularx}" in tex


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


def test_render_diagram_supports_edge_labels_and_book_styling(tmp_path):
    captured = {}

    def fake_runner(args, **kwargs):
        captured["input"] = kwargs.get("input")
        Path(args[args.index("-o") + 1]).write_bytes(b"fake-png")
        return _FakeCompletedProcess(returncode=0)

    render_node.render_diagram(
        {
            "nodes": ["Begin", "Commit", "Rollback"],
            "edges": [["Begin", "Commit", "success"], ["Begin", "Rollback", 'any "failure"']],
        },
        tmp_path / "d.png",
        runner=fake_runner,
    )

    dot = captured["input"]
    assert '"Begin" -> "Commit" [label="success"];' in dot
    assert '"Begin" -> "Rollback" [label="any \\"failure\\""];' in dot
    assert 'fillcolor="#E8EEF7"' in dot


def test_render_diagram_drops_unconnected_nodes_and_merges_case_variants(tmp_path):
    """Seen in a real book: "Success"/"Failure" were listed as nodes but
    only used as arrow labels, so they floated as disconnected boxes."""
    captured = {}

    def fake_runner(args, **kwargs):
        captured["input"] = kwargs.get("input")
        Path(args[args.index("-o") + 1]).write_bytes(b"fake-png")
        return _FakeCompletedProcess(returncode=0)

    render_node.render_diagram(
        {
            "nodes": ["Begin", "Execute", "Success", "Failure", "Commit"],
            "edges": [["Begin", "Execute"], ["execute ", "commit", "if success"]],
        },
        tmp_path / "d.png",
        runner=fake_runner,
    )

    dot = captured["input"]
    assert '"Success"' not in dot and '"Failure"' not in dot
    assert '"Execute" -> "Commit" [label="if success"];' in dot
    assert '"execute' not in dot and '"commit"' not in dot


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


def test_render_diagram_folds_typographic_hyphens_and_sends_dot_utf8(tmp_path):
    captured = {}

    class _Done:
        returncode = 0
        stderr = ""

    def fake_runner(args, **kwargs):
        captured.update(kwargs)
        return _Done()

    render_node.render_diagram(
        {
            "nodes": ["High\u2011Level Design", "Low-Level Design"],
            "edges": [["High-Level Design", "Low\u2011Level Design", "next\u2011step"]],
        },
        tmp_path / "d.png",
        runner=fake_runner,
    )

    dot = captured["input"]
    assert "\u2011" not in dot
    assert dot.count('"High-Level Design";') == 1  # one box, not two lookalikes
    assert captured["encoding"] == "utf-8"


def test_render_diagram_drops_arrow_only_edge_labels(tmp_path):
    captured = {}

    class _Done:
        returncode = 0
        stderr = ""

    def fake_runner(args, **kwargs):
        captured.update(kwargs)
        return _Done()

    render_node.render_diagram(
        {"nodes": ["A", "B", "C"], "edges": [["A", "B", "\u2014>"], ["B", "C", "next step"]]},
        tmp_path / "d.png",
        runner=fake_runner,
    )

    assert '"A" -> "B";' in captured["input"]
    assert 'label="next step"' in captured["input"]
    assert 'label=">"' not in captured["input"]


def test_render_diagram_merges_parallel_arrows_and_wraps_long_labels(tmp_path):
    captured = {}

    class _Done:
        returncode = 0
        stderr = ""

    def fake_runner(args, **kwargs):
        captured.update(kwargs)
        return _Done()

    edges = [["Client", "Upload Service", "1. request upload"], ["Client", "Upload Service", "9. complete upload"]]
    edges += [[f"N{i}", f"N{i + 1}", "step"] for i in range(14)]
    render_node.render_diagram({"nodes": ["Client", "Upload Service"], "edges": edges}, tmp_path / "d.png", runner=fake_runner)

    dot = captured["input"]
    assert dot.count('"Client" -> "Upload Service"') == 1
    unwrapped = dot.replace("\\n", " ")
    assert "1. request upload; 9. complete upload" in unwrapped
    assert "\n" in dot  # the merged label wraps
    assert "concentrate=true" in dot  # a busy graph bundles parallel edges
