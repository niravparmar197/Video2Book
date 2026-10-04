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
_MD_HIGHLIGHT_RE = re.compile(r"==(.+?)==")
_MD_CODE_RE = re.compile(r"`([^`\n]+)`")
# A Markdown divider ("---", "***", "___") printed as a stray em dash.
_HRULE_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")

# "> Key point: ..." callout lines the notes prompt asks for -> a boxed
# callout (\notecallout in main.tex.j2). label -> (box title, border, fill).
_CALLOUT_RE = re.compile(
    r"^>\s*(?:\*\*)?(key point|remember|tip|note|example|watch out|warning|quote)(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.+)$",
    re.IGNORECASE,
)
# A "> ..." line with no label (the writer often drops "Example:" from its
# "> Think of it like ..." analogy) is still a callout, never a literal ">".
_QUOTE_RE = re.compile(r"^>\s*(.+)$")
_KEY_POINT_STYLE = ("Key Point", "V2BRule", "V2BCalloutGold")
_WARNING_STYLE = ("Watch Out", "V2BWarn", "V2BCalloutRed")
_CALLOUT_STYLES = {
    "key point": _KEY_POINT_STYLE,
    "remember": _KEY_POINT_STYLE,
    "tip": _KEY_POINT_STYLE,
    "note": _KEY_POINT_STYLE,
    "example": ("Example", "V2BAccent", "V2BCalloutTeal"),
    "watch out": _WARNING_STYLE,
    "warning": _WARNING_STYLE,
    "quote": ("Quote", "V2BQuote", "V2BCalloutPurple"),
}


def escape_latex(text: str) -> str:
    """Escape LaTeX special characters so model/transcript text never breaks a compile."""
    text = _UNSUPPORTED_UNICODE_SPACES_RE.sub(" ", text)
    return _LATEX_ESCAPE_RE.sub(lambda m: _LATEX_SPECIAL_CHARS[m.group()], text)


_TITLE_SEPARATORS = " -–—:,;|/"


def renderable_title(title: str, fallback: str) -> str:
    """`title` cut at its first non-Latin letter, or `fallback` if too little
    is left.

    The book's fonts (Latin Modern) have no glyphs for Devanagari, Cyrillic,
    CJK, ... -- a real Hindi video's title ("History of Russia -- 1500 ...")
    printed as dozens of "Missing character" errors in the page header, title
    page and table of contents. The notes themselves are always written in
    English, so only YouTube's own title can be affected.
    """
    for index, character in enumerate(title):
        if ord(character) > 0x24F and character.isalpha():
            prefix = title[:index].rstrip(_TITLE_SEPARATORS).strip()
            return prefix if sum(char.isalpha() for char in prefix) >= 3 else fallback
    return title


def _convert_markdown_emphasis(text: str) -> str:
    """Convert **bold**, *italic* and ==highlight== markdown emphasis into
    LaTeX \\textbf/\\textit/\\colorbox. Passed straight through, a compiled
    book showed literal asterisks (verified against a real book)."""
    # `code` spans: as typed they printed literal backtick marks in a real book.
    text = _MD_CODE_RE.sub(r"\\texttt{\1}", text)
    text = _MD_BOLD_RE.sub(r"\\textbf{\1}", text)
    text = _MD_ITALIC_RE.sub(r"\\textit{\1}", text)
    return _MD_HIGHLIGHT_RE.sub(r"\\colorbox{V2BHighlight}{\\strut \1}", text)


def _render_callout(label: str, body: str) -> str:
    title, border, fill = _CALLOUT_STYLES[label.lower()]
    body = body.strip()
    if label.lower() == "quote" and len(body) > 1 and body[0] == body[-1] == '"':
        # A straight " typesets as a closing mark at the start; use real ones.
        body = "“" + body[1:-1] + "”"
    text = _convert_markdown_emphasis(escape_latex(body))
    return f"\\notecallout{{{title}}}{{{border}}}{{{fill}}}{{{text}}}"


# The monospace font has no arrow glyphs (they silently vanished from a real
# book's hierarchy sketch), so spell them out.
_CODE_ARROWS = {"→": "->", "←": "<-", "↔": "<->", "⇒": "=>", "⇐": "<=", "↑": "^", "↓": "v"}


def _render_code_block(code_lines: list[str]) -> str:
    """A fenced block that is not a table/diagram/chart (e.g. a small class
    hierarchy the writer typed out) as an escaped monospace block that keeps
    line breaks and indentation, instead of running the lines together."""
    while code_lines and not code_lines[0].strip():
        code_lines = code_lines[1:]
    while code_lines and not code_lines[-1].strip():
        code_lines = code_lines[:-1]
    if not code_lines:
        return ""

    rendered = []
    for line in code_lines:
        for arrow, ascii_arrow in _CODE_ARROWS.items():
            line = line.replace(arrow, ascii_arrow)
        indent = len(line) - len(line.lstrip(" "))
        text = escape_latex(line.strip())
        rendered.append((f"\\hspace*{{{indent * 0.5}em}}" if indent else "") + text)
    return "\\begin{flushleft}\\ttfamily\\small\n" + " \\\\\n".join(rendered) + "\n\\end{flushleft}"


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
    # Where the screenshot was taken, for placing it by time ("" / -1 for
    # diagrams and charts, which have no video moment).
    video_id: str = ""
    timestamp_seconds: float = -1.0


def _watch_url(video_id: str, seconds: float) -> str:
    # youtu.be + ?t= keeps the URL free of "&", which LaTeX treats specially.
    return f"https://youtu.be/{video_id}?t={int(seconds)}"


def _clock(seconds: float) -> str:
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


_VISUAL_FENCE_RE = re.compile(r"^```(table|diagram|chart)\s*$")
# "- item", "* item", "• item", or "1. item" / "1) item".
_BULLET_RE = re.compile(r"^(?:[-*•]|\d+[.)])\s+(.+)$")
_VISUAL_KINDS = {"table", "diagram", "chart"}


def markdown_notes_to_sections(markdown_text: str) -> list[Section]:
    """Convert AI-written Markdown notes into escaped Sections for the template.

    Handles the subset of Markdown write_notes.md/write_topic_notes.md
    produce: `## heading` lines, blank-line-separated paragraphs, bullets,
    `> Key point: ...` callout lines, `==highlighted==` phrases, and
    ```table/```diagram/```chart fenced JSON blocks per section
    (sprints/v5 PRD.md). A malformed visual block is dropped with a
    logged warning rather than raising -- one bad block must not crash the
    whole write step.

    A heading line at any OTHER depth (`#`, `###`, `####`, ...) -- a habit
    the writer model falls into despite the prompt only ever asking for
    `##` -- is treated as a bolded sub-heading paragraph, not a literal
    "### Atomicity" dumped into the book's body text (verified against a
    real compiled book: that's exactly what used to happen, since only a
    `#`-escaping pass ran on it, not a markdown-heading pass).
    """
    sections: list[Section] = []
    current_heading: str | None = None
    current_paragraphs: list[str] = []
    current_visuals: list[Visual] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            text = " ".join(paragraph_lines).strip()
            if text:
                current_paragraphs.append(_convert_markdown_emphasis(escape_latex(text)))
            paragraph_lines.clear()

    def flush_list() -> None:
        # A real bulleted list, not "- a - b" run together into one
        # paragraph with literal dashes (how bullets rendered before).
        if list_items:
            items = "\n".join(
                r"\item " + _convert_markdown_emphasis(escape_latex(item)) for item in list_items
            )
            current_paragraphs.append("\\begin{itemize}\n" + items + "\n\\end{itemize}")
            list_items.clear()

    def flush_section() -> None:
        flush_paragraph()
        flush_list()
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
            flush_list()
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

        if stripped.startswith("```"):
            flush_paragraph()
            flush_list()
            inline = stripped[3:]
            if len(inline) > 3 and inline.endswith("```"):  # a one-line fence
                code_lines = [inline[:-3]]
            else:  # text after the opening ``` is a language tag, not content
                code_lines = []
                index += 1
                while index < len(lines) and not lines[index].strip().startswith("```"):
                    code_lines.append(lines[index])
                    index += 1
            index += 1  # skip the closing fence
            code_block = _render_code_block(code_lines)
            if code_block:
                current_paragraphs.append(code_block)
            continue

        if _HRULE_RE.match(stripped):
            flush_paragraph()
            flush_list()
            index += 1
            continue

        bullet_match = _BULLET_RE.match(stripped)
        callout_match = _CALLOUT_RE.match(stripped)
        quote_match = _QUOTE_RE.match(stripped)
        if callout_match or quote_match:
            flush_paragraph()
            flush_list()
            if callout_match:
                label, body = callout_match.groups()
            else:
                body = quote_match.group(1)
                label = "example" if body.lower().startswith("think of it like") else "key point"
            current_paragraphs.append(_render_callout(label, body))
        elif stripped.startswith("## "):
            flush_section()
            current_heading = stripped[3:].strip()
        elif bullet_match:
            flush_paragraph()
            list_items.append(bullet_match.group(1).strip())
        elif list_items and stripped and lines[index][:1].isspace():
            # An indented line right under a bullet continues that bullet.
            list_items[-1] = f"{list_items[-1]} {stripped}"
        elif stripped.startswith("#"):
            flush_paragraph()
            flush_list()
            subheading_text = stripped.lstrip("#").strip()
            if subheading_text:
                # A highlighter-style tint behind the text, not just bold --
                # this is the chapter's own "main point" marker, and should
                # read as a highlight at a glance, not just another bolded
                # word among others. V2BRule!25 = that accent mixed 25% into
                # white, a light tint rather than a solid block of color.
                current_paragraphs.append(
                    f"\\colorbox{{V2BRule!25}}{{\\textbf{{\\color{{V2BPrimary}}"
                    f"{_convert_markdown_emphasis(escape_latex(subheading_text))}}}}}"
                )
        elif stripped == "":
            flush_paragraph()
        else:
            flush_list()
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
        # Saved as assets/<video_id>/<chunk>_<n>.jpg by app.nodes.frames.
        video_id = asset_path.parent.name
        timestamp = float(shot["timestamp_seconds"])
        # The caption links to that exact moment on YouTube.
        caption = (
            f"\\href{{{_watch_url(video_id, timestamp)}}}"
            f"{{Screenshot at {_clock(timestamp)} -- watch on YouTube}}"
        )
        figures.append(
            Figure(
                relative_path=relative_path,
                caption=caption,
                video_id=video_id,
                timestamp_seconds=timestamp,
            )
        )
    return figures


def _figures_by_section_time(
    figures: list[Figure], section_times: list[tuple[str, float] | None]
) -> list[list[Figure]] | None:
    """Put each screenshot in the section whose spoken time it falls in (the
    latest section of the same video starting at or before it). None when no
    section has a time -- the caller then spreads them evenly."""
    timed = sorted(
        (start, index, video_id)
        for index, entry in enumerate(section_times)
        if entry is not None
        for video_id, start in [entry]
    )
    if not timed:
        return None
    slices: list[list[Figure]] = [[] for _ in section_times]
    for figure in figures:
        same_video = [item for item in timed if item[2] == figure.video_id] or timed
        before = [item for item in same_video if item[0] <= figure.timestamp_seconds]
        _, index, _ = before[-1] if before else same_video[0]
        slices[index].append(figure)
    return slices


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


_TEST_YOURSELF_RE = re.compile(
    r"^##\s+Test Yourself\s*$(.*?)(?=^##\s|\Z)", re.IGNORECASE | re.MULTILINE | re.DOTALL
)
_QA_RE = re.compile(
    r"^\s*(?:[-*]\s*)?\**Q\d*\**\s*[:.]\**\s*(.+?)\s*\n\s*(?:[-*]\s*)?\**A\d*\**\s*[:.]\**\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _split_test_yourself(markdown_notes: str) -> tuple[str, list[str]]:
    """Turn a `## Test Yourself` block of "Q: ... / A: ..." pairs into a
    numbered question list and return the answers separately (for the
    Answers section at the back of the book). Notes without the block, or
    without well-formed pairs, are returned unchanged with no answers."""
    match = _TEST_YOURSELF_RE.search(markdown_notes)
    if match is None:
        return markdown_notes, []
    pairs = _QA_RE.findall(match.group(1))
    if not pairs:
        return markdown_notes, []
    questions = "\n".join(f"- **Q{number}.** {question}" for number, (question, _) in enumerate(pairs, 1))
    block = f"## Test Yourself\n{questions}\n\n*Answers are at the back of the book.*\n\n"
    rewritten = markdown_notes[: match.start()] + block + markdown_notes[match.end() :]
    return rewritten, [answer for _, answer in pairs]


def _load_answers(chapter_ids: list[str], chapters_dir: Path) -> list[dict]:
    """[{title, answers: [escaped answer, ...]}] for the chapters (in order)
    that have Test Yourself answers."""
    answer_sets = []
    for chapter_id in chapter_ids:
        path = chapters_dir / f"{chapter_id}.answers.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            answer_sets.append(
                {
                    "title": escape_latex(renderable_title(payload["title"], "Chapter")),
                    "answers": [
                        _convert_markdown_emphasis(escape_latex(answer)) for answer in payload["answers"]
                    ],
                }
            )
    return answer_sets


def render_chapter(
    video_id: str,
    title: str,
    markdown_notes: str,
    output_dir: str | Path,
    screenshots: list[dict] | None = None,
    index_terms: list[str] | None = None,
    section_times: list[tuple[str, float] | None] | None = None,
) -> Path:
    """Render Markdown notes into chapters/<video_id>.tex via the Jinja2 template.

    `section_times` (app.nodes.align), if given, is where each `##` section
    is spoken: screenshots are then placed by time instead of spread evenly,
    and each timed section gets a "watch on YouTube" link to that moment.

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
    markdown_notes, answers = _split_test_yourself(markdown_notes)
    sections = markdown_notes_to_sections(markdown_notes)

    chapters_dir = output_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    # Answers to the chapter's "Test Yourself" questions go to the back of the
    # book (render_book), so the reader can try them first.
    answers_path = chapters_dir / f"{video_id}.answers.json"
    if answers:
        answers_path.write_text(
            json.dumps({"title": title, "answers": answers}, ensure_ascii=False), encoding="utf-8"
        )
    else:
        answers_path.unlink(missing_ok=True)
    chapters_dir.mkdir(parents=True, exist_ok=True)
    figures = _build_figures(screenshots, chapters_dir)
    times = list(section_times or [])
    times = times if len(times) == len(sections) else [None] * len(sections)
    distributed_figures = _figures_by_section_time(figures, times) or _distribute_figures(
        figures, len(sections)
    )
    rendered_sections = [
        {
            **_render_section_visuals(section, index, video_id, output_dir, chapters_dir),
            "screenshot_figures": distributed_figures[index],
            "watch_link": (
                f"\\href{{{_watch_url(*times[index])}}}"
                f"{{Watch this part on YouTube from {_clock(times[index][1])}}}"
                if times[index] is not None
                else None
            ),
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
        title=escape_latex(renderable_title(title, "Notes")), sections=rendered_sections, figures=figures
    )

    tex_path = chapters_dir / f"{video_id}.tex"
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
    glossary_entries: list[dict] | None = None,
    book_title: str = "Video2Book",
    book_kind: str = "Study Notes",
) -> Path:
    """Render chapters/main.tex, which \\input's each chapter fragment (in
    the given order) with a table of contents, via main.tex.j2.

    Assumes render_chapter() has already written chapters/<id>.tex for every
    id in chapter_ids; main.tex lives alongside them so \\input{<id>}
    resolves via LaTeX's default same-directory search path.

    `glossary_entries`, if given (and non-empty), are rendered via
    render_glossary() and \\input after the chapters. Order: title page ->
    TOC -> chapters -> glossary -> subject index (\\printindex).

    `book_title` (default "Video2Book", matching the previous hardcoded
    behavior) is the title page's \\title -- verified against a real book
    that this always showed "Video2Book" regardless of source video, since
    no caller ever had a title to pass.
    """
    output_dir = Path(output_dir)
    chapters_dir = output_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)

    has_glossary = bool(glossary_entries)
    if has_glossary:
        render_glossary(glossary_entries, output_dir)

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)))  # nosec B701
    template = env.get_template("main.tex.j2")
    tex_source = template.render(
        book_title=escape_latex(renderable_title(book_title, "Video Notes")),
        book_kind=escape_latex(book_kind),
        chapter_ids=chapter_ids,
        answer_sets=_load_answers(chapter_ids, chapters_dir),
        has_glossary=has_glossary,
    )

    main_tex_path = chapters_dir / "main.tex"
    main_tex_path.write_text(tex_source, encoding="utf-8")
    return main_tex_path


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
    glossary_entries: list[dict] | None = None,
    book_title: str = "Video2Book",
    book_kind: str = "Study Notes",
) -> list[Path]:
    """Render one chapters/main_vol<N>.tex per chapter group (sprints/v6
    PRD.md). Front matter (title + TOC) appears in volume 1
    only; back matter (glossary + indexes) appears in the LAST volume
    only, so a reader gets one coherent front and one coherent back, not
    a glossary repeated in every volume. A single-group input still
    produces main_vol1.tex, not main.tex -- callers that always want a
    single book.pdf/main.tex should call render_book() instead.
    """
    output_dir = Path(output_dir)
    chapters_dir = output_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)

    has_glossary = bool(glossary_entries)
    if has_glossary:
        render_glossary(glossary_entries, output_dir)

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)))  # nosec B701
    template = env.get_template("main.tex.j2")

    volume_count = len(chapter_groups)
    paths: list[Path] = []
    for volume_index, group in enumerate(chapter_groups, start=1):
        is_last = volume_index == volume_count
        tex_source = template.render(
            book_title=escape_latex(renderable_title(book_title, "Video Notes")),
            book_kind=escape_latex(book_kind),
            chapter_ids=group,
            answer_sets=_load_answers(group, chapters_dir),
            has_glossary=has_glossary if is_last else False,
            volume_number=volume_index if volume_count > 1 else None,
        )
        main_tex_path = chapters_dir / f"main_vol{volume_index}.tex"
        main_tex_path.write_text(tex_source, encoding="utf-8")
        paths.append(main_tex_path)

    return paths


def _latex_error_summary(output: str) -> str:
    """The first real LaTeX error ("! LaTeX Error: Too many unprocessed
    floats.") from latexmk's output. The raw output is thousands of lines of
    package loading, so the cause used to be buried or cut off in the stored
    error message."""
    for line in output.splitlines():
        if line.startswith("!"):
            return line.strip()
    return "no '!' error line found; see the full output below"


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
            # -g: rebuild even if latexmk thinks nothing changed. After a failed
            # run it otherwise answers "Nothing to do ... gave an error in
            # previous invocation" and every retry just repeats the old error.
            "-g",
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
            f"latexmk failed for {tex_path} (exit {result.returncode}): "
            f"{_latex_error_summary(result.stdout)}\n{result.stdout}\n{result.stderr}"
        )
    return pdf_path
