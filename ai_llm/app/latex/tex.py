"""LaTeX rendering: Markdown notes -> compiling .tex chapter via Jinja2 + latexmk.

The AI writes Markdown/JSON only; this module owns all LaTeX syntax and
escaping, so a model never has to get LaTeX right and transcript-derived
text can never break a compile. See root AGENTS.md.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess  # nosec B404 - invokes only the fixed "latexmk" arg list below, never shell=True
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_LATEX_SPECIAL_CHARS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_LATEX_ESCAPE_RE = re.compile("|".join(re.escape(c) for c in _LATEX_SPECIAL_CHARS))

# Unicode space variants an LLM writer routinely emits (narrow no-break space
# before "T1"/"T2"-style labels, non-breaking space, thin space, ...) that
# Latin Modern -- LuaLaTeX's default font -- has no glyph for, rendering as a
# broken/missing character. Verified against a real compiled book: the writer
# model wrote U+202F before "T1", which came out as a broken glyph in the PDF.
# Collapsing to a plain space is safe since none of these carry meaning that
# survives into a PDF anyway.
_UNSUPPORTED_UNICODE_SPACES_RE = re.compile("[\u00a0\u2000-\u200a\u202f\u205f\u3000]")

_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)([^*]+?)\*(?!\*)")


def escape_latex(text: str) -> str:
    """Escape LaTeX special characters so model/transcript text never breaks a compile."""
    text = _UNSUPPORTED_UNICODE_SPACES_RE.sub(" ", text)
    return _LATEX_ESCAPE_RE.sub(lambda m: _LATEX_SPECIAL_CHARS[m.group()], text)


def _convert_markdown_emphasis(text: str) -> str:
    """Convert **bold**/*italic* markdown emphasis -- a habit the writer
    model falls into even though write_notes.md never asks for it -- into
    LaTeX \\textbf/\\textit. Previously passed straight through, so a
    compiled book showed literal asterisks (verified against a real book)."""
    text = _MD_BOLD_RE.sub(r"\\textbf{\1}", text)
    return _MD_ITALIC_RE.sub(r"\\textit{\1}", text)


@dataclass(frozen=True)
class Visual:
    kind: str  # "table" | "diagram" | "chart"
    data: dict


@dataclass(frozen=True)
class Section:
    heading: str
    paragraphs: list[str]
    visuals: list[Visual] = field(default_factory=list)


@dataclass(frozen=True)
class Figure:
    relative_path: str
    caption: str


_VISUAL_FENCE_RE = re.compile(r"^```(table|diagram|chart)\s*$")
_VISUAL_KINDS = {"table", "diagram", "chart"}


def markdown_notes_to_sections(markdown_text: str) -> list[Section]:
    """Convert AI-written Markdown notes into escaped Sections for the template.

    Handles the subset of Markdown write_notes.md/write_topic_notes.md
    produce: `## heading` lines, blank-line-separated paragraphs, and an
    optional trailing ```table/```diagram/```chart fenced JSON block per
    section (sprints/v5 PRD.md). A malformed visual block is dropped with a
    logged warning rather than raising -- one bad block must not crash the
    whole write step.
    """
    sections: list[Section] = []
    current_heading: str | None = None
    current_paragraphs: list[str] = []
    current_visuals: list[Visual] = []
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            text = " ".join(paragraph_lines).strip()
            if text:
                current_paragraphs.append(_convert_markdown_emphasis(escape_latex(text)))
            paragraph_lines.clear()

    def flush_section() -> None:
        flush_paragraph()
        if current_heading is not None:
            sections.append(
                Section(
                    heading=escape_latex(current_heading),
                    paragraphs=list(current_paragraphs),
                    visuals=list(current_visuals),
                )
            )
        current_paragraphs.clear()
        current_visuals.clear()

    lines = markdown_text.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        fence_match = _VISUAL_FENCE_RE.match(stripped)

        if fence_match:
            flush_paragraph()
            kind = fence_match.group(1)
            index += 1
            json_lines = []
            while index < len(lines) and lines[index].strip() != "```":
                json_lines.append(lines[index])
                index += 1
            try:
                data = json.loads("\n".join(json_lines))
                current_visuals.append(Visual(kind=kind, data=data))
            except json.JSONDecodeError:
                logger.warning("ignoring malformed ```%s block in notes", kind)
            index += 1  # skip the closing fence (or end of text if unterminated)
            continue

        if stripped.startswith("## "):
            flush_section()
            current_heading = stripped[3:].strip()
        elif stripped == "":
            flush_paragraph()
        else:
            paragraph_lines.append(stripped)
        index += 1

    flush_section()
    return sections


def _build_figures(screenshots: list[dict] | None, chapters_dir: Path) -> list[Figure]:
    """Sort a chapter's/topic's screenshots by timestamp and resolve each
    asset path relative to chapters_dir, so \\includegraphics resolves
    regardless of where output_dir itself lives on disk.
    """
    figures = []
    for shot in sorted(screenshots or [], key=lambda s: s["timestamp_seconds"]):
        asset_path = Path(shot["asset_path"]).resolve()
        relative_path = os.path.relpath(asset_path, chapters_dir).replace("\\", "/")
        minutes, seconds = divmod(int(shot["timestamp_seconds"]), 60)
        figures.append(
            Figure(relative_path=relative_path, caption=f"Screenshot at {minutes:02d}:{seconds:02d}")
        )
    return figures


def _distribute_figures(figures: list[Figure], section_count: int) -> list[list[Figure]]:
    """Split a chapter's timestamp-ordered screenshots evenly across its
    sections, so each section gets the figures nearest to its own place in
    the chapter instead of every screenshot being dumped in one block after
    all the text (the previous behavior: screenshots read as disconnected
    from the content they illustrate). Order-preserving, proportional by
    count -- not a real per-section timestamp match, but a much closer
    approximation than one undifferentiated block at the end.

    Returns a list of length `section_count` (each a possibly-empty slice
    of `figures`, in order); returns `[]` if there are no sections at all,
    so the caller falls back to rendering `figures` as its own block.
    """
    if section_count == 0:
        return []
    total = len(figures)
    slices: list[list[Figure]] = []
    for index in range(section_count):
        start = round(index * total / section_count)
        end = round((index + 1) * total / section_count)
        slices.append(figures[start:end])
    return slices


def _render_section_visuals(
    section: Section, section_index: int, video_id: str, output_dir: Path, chapters_dir: Path
) -> dict:
    """Render a section's parsed Visuals into LaTeX tables + diagram/chart
    figures. A visual that fails to render (bad Graphviz/matplotlib input)
    is skipped with a logged warning rather than crashing the whole
    chapter -- one bad visual must not lose an otherwise-good section.
    """
    from app.nodes.render import render_chart, render_diagram, render_table

    tables: list[str] = []
    visual_figures: list[Figure] = []

    for visual_index, visual in enumerate(section.visuals):
        try:
            if visual.kind == "table":
                tables.append(render_table(visual.data))
            elif visual.kind in ("diagram", "chart"):
                asset_path = (
                    output_dir
                    / "assets"
                    / video_id
                    / f"{visual.kind}_{section_index:02d}_{visual_index:02d}.png"
                )
                if visual.kind == "diagram":
                    render_diagram(visual.data, asset_path)
                else:
                    render_chart(visual.data, asset_path)
                relative_path = os.path.relpath(asset_path.resolve(), chapters_dir).replace(
                    "\\", "/"
                )
                caption = escape_latex(str(visual.data.get("title") or visual.kind.capitalize()))
                visual_figures.append(Figure(relative_path=relative_path, caption=caption))
        except Exception as error:  # noqa: BLE001 - one bad visual must not crash the chapter
            logger.warning(
                "skipping %s visual in chapter %s section %r: %s",
                visual.kind,
                video_id,
                section.heading,
                error,
            )

    return {
        "heading": section.heading,
        "paragraphs": section.paragraphs,
        "tables": tables,
        "visual_figures": visual_figures,
    }


def _insert_index_markup(rendered_sections: list[dict], index_terms: list[str] | None) -> None:
    """Insert \\index{term} at each term's first case-insensitive occurrence
    across this chapter's paragraphs, in section order -- only the first
    occurrence per term gets marked (sprints/v6 PRD.md). Mutates
    `rendered_sections` in place (each section's "paragraphs" list).
    """
    remaining = {term.lower(): term for term in (index_terms or [])}
    if not remaining:
        return

    for section in rendered_sections:
        if not remaining:
            break
        paragraphs = section["paragraphs"]
        for paragraph_index, paragraph in enumerate(paragraphs):
            if not remaining:
                break
            for key in list(remaining.keys()):
                escaped_term = escape_latex(remaining[key])
                match_pos = paragraph.lower().find(escaped_term.lower())
                if match_pos == -1:
                    continue
                insert_at = match_pos + len(escaped_term)
                paragraph = (
                    paragraph[:insert_at] + f"\\index{{{escaped_term}}}" + paragraph[insert_at:]
                )
                del remaining[key]
            paragraphs[paragraph_index] = paragraph


def render_chapter(
    video_id: str,
    title: str,
    markdown_notes: str,
    output_dir: str | Path,
    screenshots: list[dict] | None = None,
    index_terms: list[str] | None = None,
) -> Path:
    """Render Markdown notes into chapters/<video_id>.tex via the Jinja2 template.

    The output is an includable fragment (\\chapter{...} + \\section{...}s,
    no \\documentclass/\\begin{document}) meant to be \\input from
    main.tex.j2 (render_book) — it is not compilable on its own.

    `screenshots` (sprints/v4 PRD.md), if given, is a list of
    {"asset_path", "timestamp_seconds"} gathered from every chunk this
    chapter/topic covers; in timestamp order, they are split evenly across
    the chapter's sections and each slice is placed directly after that
    section's own text/visuals -- not dumped as one undifferentiated block
    after the whole chapter, which previously left screenshots looking
    disconnected from the content they illustrate. A chapter with no
    parsed sections (e.g. empty notes) falls back to one block at the end.
    Each section's parsed table/diagram/chart Visuals (sprints/v5 PRD.md)
    are rendered and placed directly after that section's paragraphs.
    `index_terms` (sprints/v6 PRD.md), if given, are subject-index terms
    marked with \\index{} at their first occurrence in this chapter, for
    main.tex.j2's \\printindex.
    """
    output_dir = Path(output_dir)
    sections = markdown_notes_to_sections(markdown_notes)

    chapters_dir = output_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    figures = _build_figures(screenshots, chapters_dir)
    distributed_figures = _distribute_figures(figures, len(sections))
    rendered_sections = [
        {
            **_render_section_visuals(section, index, video_id, output_dir, chapters_dir),
            "screenshot_figures": distributed_figures[index],
        }
        for index, section in enumerate(sections)
    ]
    _insert_index_markup(rendered_sections, index_terms)
    # Only non-empty when there were no sections to attach figures to
    # (distribute_figures returns [] in that case) -- the template's
    # trailing figures loop is the fallback for that edge case only.
    figures = figures if not sections else []

    # nosec B701 - this renders LaTeX, not HTML/XML; Jinja's HTML autoescape
    # would corrupt our own LaTeX escaping (e.g. "\&" -> "\&amp;"). Every
    # dynamic value passed to render() below is already escaped via
    # escape_latex() before it gets here, and the template file itself is
    # a trusted, static, checked-in file.
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)))  # nosec B701
    template = env.get_template("chapter.tex.j2")
    tex_source = template.render(
        title=escape_latex(title), sections=rendered_sections, figures=figures
    )

    tex_path = chapters_dir / f"{video_id}.tex"
    tex_path.write_text(tex_source, encoding="utf-8")
    return tex_path


def render_topic_index(chapters: list[dict], output_dir: str | Path) -> Path:
    """Render a structural topic index -- one line per chapter/topic title,
    in the given order -- as chapters/topic_index.tex (sprints/v6 PRD.md).

    No LLM call, no makeindex: built directly from the chapter list
    (outline.json order), distinct from the LLM-extracted, page-numbered
    subject index (Task 4). `chapters` is a list of {"title": ...}.
    """
    output_dir = Path(output_dir)
    entries = [escape_latex(chapter["title"]) for chapter in chapters]

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)))  # nosec B701
    template = env.get_template("topic_index.tex.j2")
    tex_source = template.render(entries=entries)

    chapters_dir = output_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    tex_path = chapters_dir / "topic_index.tex"
    tex_path.write_text(tex_source, encoding="utf-8")
    return tex_path


def render_glossary(entries: list[dict], output_dir: str | Path) -> Path:
    """Render chapters/glossary.tex: an unnumbered chapter listing each
    {"term", "definition"} entry (sprints/v6 PRD.md). `entries` is expected
    already sorted (book_pass.py's run_glossary sorts alphabetically).
    """
    output_dir = Path(output_dir)
    escaped_entries = [
        {
            "term": escape_latex(entry["term"]),
            "definition": _convert_markdown_emphasis(escape_latex(entry["definition"])),
        }
        for entry in entries
    ]

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)))  # nosec B701
    template = env.get_template("glossary.tex.j2")
    tex_source = template.render(entries=escaped_entries)

    chapters_dir = output_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    tex_path = chapters_dir / "glossary.tex"
    tex_path.write_text(tex_source, encoding="utf-8")
    return tex_path


def render_book(
    chapter_ids: list[str],
    output_dir: str | Path,
    preface_path: str | Path | None = None,
    glossary_entries: list[dict] | None = None,
    include_topic_index: bool = False,
    book_title: str = "Video2Book",
) -> Path:
    """Render chapters/main.tex, which \\input's each chapter fragment (in
    the given order) with a table of contents, via main.tex.j2.

    Assumes render_chapter() has already written chapters/<id>.tex for every
    id in chapter_ids, and render_topic_index() has already written
    chapters/topic_index.tex if include_topic_index is True; main.tex lives
    alongside them so \\input{<id>} resolves via LaTeX's default
    same-directory search path.

    `preface_path` (sprints/v6 PRD.md), if given, is a Markdown-paragraphs
    file (book_pass.py's run_preface output) rendered as an unnumbered
    Preface chapter before the TOC. `glossary_entries`, if given (and
    non-empty), are rendered via render_glossary() and \\input after the
    chapters. Order: title page -> preface -> TOC -> chapters -> glossary
    -> subject index (\\printindex) -> topic index.

    `book_title` (default "Video2Book", matching the previous hardcoded
    behavior) is the title page's \\title -- verified against a real book
    that this always showed "Video2Book" regardless of source video, since
    no caller ever had a title to pass.
    """
    output_dir = Path(output_dir)
    chapters_dir = output_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)

    preface_paragraphs = _load_preface_paragraphs(preface_path)
    has_glossary = bool(glossary_entries)
    if has_glossary:
        render_glossary(glossary_entries, output_dir)

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)))  # nosec B701
    template = env.get_template("main.tex.j2")
    tex_source = template.render(
        book_title=escape_latex(book_title),
        chapter_ids=chapter_ids,
        preface_paragraphs=preface_paragraphs,
        has_glossary=has_glossary,
        has_topic_index=include_topic_index,
    )

    main_tex_path = chapters_dir / "main.tex"
    main_tex_path.write_text(tex_source, encoding="utf-8")
    return main_tex_path


def _load_preface_paragraphs(preface_path: str | Path | None) -> list[str]:
    if preface_path is None:
        return []
    preface_text = Path(preface_path).read_text(encoding="utf-8")
    return [
        _convert_markdown_emphasis(escape_latex(paragraph.strip()))
        for paragraph in preface_text.split("\n\n")
        if paragraph.strip()
    ]


def split_into_volumes(chapters_with_hours: list[tuple[str, float]], volume_hours: float) -> list[list[str]]:
    """Greedily group chapter ids into volumes of at most volume_hours each
    (sprints/v6 PRD.md), preserving order. A single chapter longer than
    volume_hours gets its own volume rather than being split. Returns one
    group (no split) if everything already fits in volume_hours.
    """
    volumes: list[list[str]] = []
    current: list[str] = []
    current_hours = 0.0

    for chapter_id, hours in chapters_with_hours:
        if current and current_hours + hours > volume_hours:
            volumes.append(current)
            current = []
            current_hours = 0.0
        current.append(chapter_id)
        current_hours += hours

    if current:
        volumes.append(current)

    return volumes or [[]]


def render_book_volumes(
    chapter_groups: list[list[str]],
    output_dir: str | Path,
    preface_path: str | Path | None = None,
    glossary_entries: list[dict] | None = None,
    include_topic_index: bool = False,
    book_title: str = "Video2Book",
) -> list[Path]:
    """Render one chapters/main_vol<N>.tex per chapter group (sprints/v6
    PRD.md). Front matter (title + preface + TOC) appears in volume 1
    only; back matter (glossary + indexes) appears in the LAST volume
    only, so a reader gets one coherent front and one coherent back, not
    a glossary repeated in every volume. A single-group input still
    produces main_vol1.tex, not main.tex -- callers that always want a
    single book.pdf/main.tex should call render_book() instead.
    """
    output_dir = Path(output_dir)
    chapters_dir = output_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)

    preface_paragraphs = _load_preface_paragraphs(preface_path)
    has_glossary = bool(glossary_entries)
    if has_glossary:
        render_glossary(glossary_entries, output_dir)

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)))  # nosec B701
    template = env.get_template("main.tex.j2")

    volume_count = len(chapter_groups)
    paths: list[Path] = []
    for volume_index, group in enumerate(chapter_groups, start=1):
        is_first = volume_index == 1
        is_last = volume_index == volume_count
        tex_source = template.render(
            book_title=escape_latex(book_title),
            chapter_ids=group,
            preface_paragraphs=preface_paragraphs if is_first else [],
            has_glossary=has_glossary if is_last else False,
            has_topic_index=include_topic_index if is_last else False,
            volume_number=volume_index if volume_count > 1 else None,
        )
        main_tex_path = chapters_dir / f"main_vol{volume_index}.tex"
        main_tex_path.write_text(tex_source, encoding="utf-8")
        paths.append(main_tex_path)

    return paths


def compile_chapter(
    tex_path: str | Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    timeout: int = 120,
) -> Path:
    """Compile a .tex chapter to PDF via latexmk -lualatex, non-interactive."""
    tex_path = Path(tex_path)
    result = runner(
        [
            "latexmk",
            "-lualatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-output-directory=" + str(tex_path.parent),
            str(tex_path),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    pdf_path = tex_path.with_suffix(".pdf")
    if result.returncode != 0 or not pdf_path.exists():
        raise RuntimeError(
            f"latexmk failed for {tex_path} (exit {result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return pdf_path
