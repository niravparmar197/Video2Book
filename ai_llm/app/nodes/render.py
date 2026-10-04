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

import re
import textwrap
import subprocess  # nosec B404 - only ever called with a fixed arg list, never shell=True
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")  # headless: no display backend needed for a batch job
import matplotlib.pyplot as plt  # noqa: E402 - must follow matplotlib.use()

from app.latex.tex import escape_latex

DOT_TIMEOUT_SECONDS = 30
# Arrow labels wrap at this many characters; above this many arrows,
# Graphviz bundles parallel edges (concentrate) so a big diagram stays legible.
_LABEL_WRAP = 24
_BUSY_GRAPH_EDGES = 12


def render_table(data: dict) -> str:
    """Turn {"headers": [...], "rows": [[...], ...]} into an escaped LaTeX
    tabular block, styled with booktabs rules (toprule/midrule/bottomrule)
    rather than plain \\hline -- the open, ruled-line look professionally
    typeset tables use, instead of a boxed-in grid -- plus a light tinted
    header row (requires \\usepackage[table]{{xcolor}} in main.tex.j2) so a
    table doesn't read as plain black-and-white against the rest of the
    book's color.

    tabularx at full line width, with every column after the first set to
    wrap (ragged-right X columns): a plain `l` column never wraps, so a
    long cell ran straight off the right edge of the page (verified in a
    real compiled book). The first column stays `l` -- it's a short label.
    """
    headers = [str(header) for header in data.get("headers", [])]
    rows = [[str(cell) for cell in row] for row in data.get("rows", [])]

    wrap = r">{\raggedright\arraybackslash}X"
    column_count = max(len(headers), 1)
    column_spec = wrap if column_count == 1 else "l" + wrap * (column_count - 1)
    lines = [f"\\begin{{tabularx}}{{\\linewidth}}{{{column_spec}}}", "\\toprule"]
    lines.append("\\rowcolor{V2BPrimary!12}")
    lines.append(
        " & ".join(f"\\textbf{{{escape_latex(header)}}}" for header in headers) + r" \\"
    )
    lines.append("\\midrule")
    for row in rows:
        lines.append(" & ".join(escape_latex(cell) for cell in row) + r" \\")
    lines.append("\\bottomrule")
    lines.append("\\end{tabularx}")
    return "\n".join(lines)


# Typographic hyphens/dashes (non-breaking hyphen U+2011 is common in model
# output) make "Low-Level" and "Low‑Level" two different nodes and crashed dot's
# Windows code-page input; fold them to a plain hyphen.
_DASHES_RE = re.compile(r"[\u2010-\u2015\u2212]")


def _dot_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def render_diagram(
    data: dict,
    output_path: str | Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Path:
    """Turn {"nodes": [...], "edges": [[from, to] or [from, to, label], ...]}
    into a PNG via Graphviz `dot`, styled in the book's palette (filled
    rounded boxes, gold arrows) rather than Graphviz's bare black outlines,
    so a diagram reads as part of the book. An optional third edge element
    labels the arrow (e.g. "commit" / "rollback").
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    nodes = [_DASHES_RE.sub("-", str(node)).strip() for node in data.get("nodes", [])]
    by_key = {node.lower(): node for node in nodes}

    def canonical(name: object) -> str:
        # "commit" vs "Commit" must be one box, not two near-duplicates.
        text = _DASHES_RE.sub("-", str(name)).strip()
        return by_key.get(text.lower(), text)

    def clean_label(label: object) -> str:
        # A label of only arrows/dashes ("-->", "—>") is noise, not a label.
        text = _DASHES_RE.sub("-", str(label)).strip()
        return text if re.search(r"\w", text) else ""

    raw_edges = [
        (canonical(edge[0]), canonical(edge[1]), clean_label(edge[2]) if len(edge) > 2 else "")
        for edge in data.get("edges", [])
        if len(edge) >= 2
    ]
    # Several arrows between the same two boxes become one arrow with the
    # labels joined: a real 12-box architecture had 29 arrows and was an
    # unreadable tangle.
    merged: dict[tuple[str, str], list[str]] = {}
    for source, target, label in raw_edges:
        labels = merged.setdefault((source, target), [])
        if label and label not in labels:
            labels.append(label)
    edges = [(source, target, "; ".join(labels)) for (source, target), labels in merged.items()]
    if edges:
        # A box nothing connects to floats loose and breaks the flow (seen
        # in a real book: "Success"/"Failure" listed as nodes but only used
        # as arrow labels). Keep isolated nodes only for an edge-less list.
        connected = {source for source, _, _ in edges} | {target for _, target, _ in edges}
        nodes = [node for node in nodes if node in connected]

    # A left-to-right chain of more than ~4 boxes gets scaled down to
    # unreadable text at page width; longer flows run top-to-bottom instead.
    rankdir = "LR" if len(nodes) <= 4 else "TB"
    dot_lines = [
        "digraph G {",
        f'  graph [rankdir={rankdir}, bgcolor="white", pad="0.3", nodesep="0.5", ranksep="0.7", dpi=200,'
        f' concentrate={"true" if len(edges) > _BUSY_GRAPH_EDGES else "false"}];',
        '  node [shape=box, style="rounded,filled", fillcolor="#E8EEF7", color="#1F3864",'
        ' penwidth=1.5, fontname="Helvetica", fontsize=13, fontcolor="#1F3864", margin="0.25,0.12"];',
        '  edge [color="#C9A24B", penwidth=1.8, arrowsize=0.9, fontname="Helvetica",'
        ' fontsize=11, fontcolor="#1B6E6E"];',
    ]
    for node in nodes:
        dot_lines.append(f'  "{_dot_escape(node)}";')
    for source, target, label in edges:
        # Long (merged) labels wrap onto short lines instead of stretching the graph.
        wrapped = "\\n".join(textwrap.wrap(_dot_escape(label), _LABEL_WRAP)) if label else ""
        attrs = f' [label="{wrapped}"]' if label else ""
        dot_lines.append(f'  "{_dot_escape(source)}" -> "{_dot_escape(target)}"{attrs};')
    dot_lines.append("}")
    dot_source = "\n".join(dot_lines)

    result = runner(
        ["dot", "-Tpng", "-o", str(output_path)],
        input=dot_source,
        capture_output=True,
        text=True,
        encoding="utf-8",  # not the locale code page (cp1252 on Windows)
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

    palette = ["#1F3864", "#C9A24B", "#1B6E6E", "#7A9CC6", "#D9B86C", "#5FA3A3"]
    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(categories, values, color=[palette[i % len(palette)] for i in range(len(values))])
    ax.bar_label(bars, padding=3, fontsize=9, color="#333333")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, color="#1F3864", fontweight="bold")
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return output_path
