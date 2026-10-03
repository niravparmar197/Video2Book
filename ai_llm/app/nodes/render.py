"""Render node: tables, diagrams, and charts -> LaTeX/PNG assets.

The AI never writes raw LaTeX, Graphviz DOT, or matplotlib code -- it
emits structured JSON (see app.latex.tex.Visual, sprints/v5 PRD.md); this
module is the only place that turns that JSON into an artifact. See root
AGENTS.md: the AI never writes raw LaTeX, and a table/diagram/chart is
never forced where the content doesn't call for one -- that decision was
already made by the writer LLM (app/prompts/write_notes.md); this module
only renders what it's given.
"""
from __future__ import annotations

import subprocess  # nosec B404 - only ever called with a fixed arg list, never shell=True
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")  # headless: no display backend needed for a batch job
import matplotlib.pyplot as plt  # noqa: E402 - must follow matplotlib.use()

from app.latex.tex import escape_latex

DOT_TIMEOUT_SECONDS = 30


def render_table(data: dict) -> str:
    """Turn {"headers": [...], "rows": [[...], ...]} into an escaped LaTeX
    tabular block, styled with booktabs rules (toprule/midrule/bottomrule)
    rather than plain \\hline -- the open, ruled-line look professionally
    typeset tables use, instead of a boxed-in grid.
    """
    headers = [str(header) for header in data.get("headers", [])]
    rows = [[str(cell) for cell in row] for row in data.get("rows", [])]

    column_spec = "l" * max(len(headers), 1)
    lines = [f"\\begin{{tabular}}{{{column_spec}}}", "\\toprule"]
    lines.append(
        " & ".join(f"\\textbf{{{escape_latex(header)}}}" for header in headers) + r" \\"
    )
    lines.append("\\midrule")
    for row in rows:
        lines.append(" & ".join(escape_latex(cell) for cell in row) + r" \\")
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    return "\n".join(lines)


def _dot_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def render_diagram(
    data: dict,
    output_path: str | Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Path:
    """Turn {"nodes": [...], "edges": [[from, to], ...]} into a PNG via Graphviz `dot`."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    nodes = [str(node) for node in data.get("nodes", [])]
    edges = [(str(pair[0]), str(pair[1])) for pair in data.get("edges", [])]

    dot_lines = ["digraph G {"]
    for node in nodes:
        dot_lines.append(f'  "{_dot_escape(node)}";')
    for source, target in edges:
        dot_lines.append(f'  "{_dot_escape(source)}" -> "{_dot_escape(target)}";')
    dot_lines.append("}")
    dot_source = "\n".join(dot_lines)

    result = runner(
        ["dot", "-Tpng", "-o", str(output_path)],
        input=dot_source,
        capture_output=True,
        text=True,
        timeout=DOT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"graphviz dot failed (exit {result.returncode}):\n{result.stderr}")
    return output_path


def render_chart(data: dict, output_path: str | Path) -> Path:
    """Turn {"type", "title", "categories", "values"} into a PNG via matplotlib.

    Only "bar" is implemented this sprint (matches the shape write_notes.md
    instructs the writer LLM to emit); values come straight from the
    writer's JSON, which the prompt requires to be real transcript numbers.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    categories = [str(category) for category in data.get("categories", [])]
    values = [float(value) for value in data.get("values", [])]
    title = str(data.get("title", ""))

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(categories, values)
    if title:
        ax.set_title(title)
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    return output_path
