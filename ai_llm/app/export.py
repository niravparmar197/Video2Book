"""Extra book formats next to book.pdf: book.md (Markdown) and book.epub.

The PDF is for print; an EPUB reflows on phones and e-readers, and the
Markdown file is easy to edit or paste anywhere. Both are built from the
same final chapter notes, with no extra dependency: the notes' own markup
(```table / ```diagram / ```chart JSON blocks, "> Key point:" callouts,
==highlights==) is turned into plain Markdown, and the EPUB is a standard
EPUB 3 zip of XHTML pages made with the `markdown` package.
"""
from __future__ import annotations

import html
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import markdown

_FENCE_RE = re.compile(r"```(table|diagram|chart)[ \t]*\n(.*?)\n[ \t]*```", re.DOTALL)
_CALLOUT_RE = re.compile(
    r"^>\s*\**(key point|remember|tip|note|example|watch out|warning|quote)\**\s*:\s*\**\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_HIGHLIGHT_RE = re.compile(r"==(.+?)==")


def _cell(value: object) -> str:
    return str(value).replace("|", "/").replace("\n", " ").strip()


def _visual_to_markdown(match: re.Match) -> str:
    kind, body = match.groups()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return ""
    if kind == "table":
        headers = [_cell(header) for header in data.get("headers", [])]
        rows = [[_cell(cell) for cell in row] for row in data.get("rows", [])]
        if not headers:
            return ""
        lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
        lines += ["| " + " | ".join(row) + " |" for row in rows]
        return "\n".join(lines)
    if kind == "chart":
        pairs = zip(data.get("categories", []), data.get("values", []))
        title = data.get("title") or "Chart"
        rows = "\n".join(f"| {_cell(category)} | {_cell(value)} |" for category, value in pairs)
        return f"**{title}**\n\n| Item | Value |\n|---|---|\n{rows}"
    # diagram: its arrows, one per line
    title = data.get("title") or "Diagram"
    arrows = []
    for edge in data.get("edges", []):
        if len(edge) >= 2:
            label = f" ({edge[2]})" if len(edge) > 2 and str(edge[2]).strip() else ""
            arrows.append(f"- {edge[0]} → {edge[1]}{label}")
    return f"**{title}**\n\n" + "\n".join(arrows) if arrows else ""


def portable_markdown(notes: str) -> str:
    """The notes in plain Markdown that any viewer understands."""
    notes = _FENCE_RE.sub(_visual_to_markdown, notes)
    notes = _CALLOUT_RE.sub(lambda m: f"> **{m.group(1).capitalize()}:** {m.group(2)}", notes)
    return _HIGHLIGHT_RE.sub(r"<mark>\1</mark>", notes)


def write_markdown_book(chapters: list[dict], path: str | Path, title: str) -> Path:
    """`chapters`: [{title, notes}] in book order."""
    parts = [f"# {title}\n"]
    for chapter in chapters:
        notes = portable_markdown(chapter["notes"]).strip()
        parts.append(f"# {chapter['title']}\n\n{notes}\n")
    path = Path(path)
    path.write_text("\n\n".join(parts), encoding="utf-8")
    return path


_XHTML = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en">
<head><meta charset="utf-8"/><title>{title}</title>
<style>body{{font-family:serif;line-height:1.5}} mark{{background:#fff08a}}
blockquote{{border-left:4px solid #c9a24b;margin:1em 0;padding:.3em .8em;background:#fbf3dc}}
table{{border-collapse:collapse}} td,th{{border:1px solid #999;padding:.2em .5em}}</style></head>
<body>{body}</body></html>
"""


def write_epub(chapters: list[dict], path: str | Path, title: str, book_kind: str) -> Path:
    """A minimal valid EPUB 3: mimetype (stored first, uncompressed),
    container.xml, package document, navigation page, one XHTML per chapter."""
    path = Path(path)
    book_id = f"urn:uuid:{uuid.uuid4()}"
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    safe_title = html.escape(title)

    pages = []
    for index, chapter in enumerate(chapters, start=1):
        body_html = markdown.markdown(
            portable_markdown(chapter["notes"]), extensions=["tables"], output_format="xhtml"
        )
        heading = html.escape(chapter["title"])
        pages.append(
            (f"chapter{index:03d}.xhtml", heading, _XHTML.format(title=heading, body=f"<h1>{heading}</h1>\n{body_html}"))
        )

    nav_items = "\n".join(f'<li><a href="{name}">{heading}</a></li>' for name, heading, _ in pages)
    nav = _XHTML.format(
        title="Contents",
        body=f'<nav epub:type="toc" id="toc"><h1>{safe_title}</h1><p>{html.escape(book_kind)}</p><ol>{nav_items}</ol></nav>',
    )
    manifest = "\n".join(
        f'<item id="c{i}" href="{name}" media-type="application/xhtml+xml"/>' for i, (name, _, _) in enumerate(pages, 1)
    )
    spine = "\n".join(f'<itemref idref="c{i}"/>' for i in range(1, len(pages) + 1))
    package = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="bookid">{book_id}</dc:identifier>
<dc:title>{safe_title}</dc:title>
<dc:language>en</dc:language>
<dc:creator>Video2Book</dc:creator>
<meta property="dcterms:modified">{modified}</meta>
</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
{manifest}
</manifest>
<spine>
<itemref idref="nav"/>
{spine}
</spine>
</package>
"""
    container = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        epub.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
        epub.writestr("OEBPS/content.opf", package, compress_type=zipfile.ZIP_DEFLATED)
        epub.writestr("OEBPS/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
        for name, _, page in pages:
            epub.writestr(f"OEBPS/{name}", page, compress_type=zipfile.ZIP_DEFLATED)
    return path
