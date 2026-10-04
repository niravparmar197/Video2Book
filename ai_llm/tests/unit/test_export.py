"""Unit tests for app.export -- book.md and book.epub."""
import xml.etree.ElementTree as ET
import zipfile

from app import export

_NOTES = """## Caching
> Key point: A ==cache== keeps hot data close.
- Reads get **faster**.

```table
{"headers": ["Kind", "Speed"], "rows": [["Memory", "fast"], ["Disk | SSD", "slow"]]}
```

```diagram
{"title": "Read path", "nodes": ["App", "Cache", "DB"], "edges": [["App", "Cache"], ["Cache", "DB", "on miss"]]}
```

```chart
{"type": "bar", "title": "Latency", "categories": ["RAM", "SSD"], "values": [1, 100]}
```
"""


def test_portable_markdown_turns_custom_blocks_into_plain_markdown():
    text = export.portable_markdown(_NOTES)

    assert "> **Key point:** A <mark>cache</mark> keeps hot data close." in text
    assert "| Kind | Speed |" in text and "| Disk / SSD | slow |" in text
    assert "- App → Cache" in text and "- Cache → DB (on miss)" in text
    assert "| RAM | 1 |" in text
    assert "```" not in text


def test_write_markdown_book_has_title_and_chapters(tmp_path):
    path = export.write_markdown_book([{"title": "Caching", "notes": _NOTES}], tmp_path / "book.md", "My Book")

    text = path.read_text(encoding="utf-8")
    assert text.startswith("# My Book")
    assert "# Caching" in text


def test_write_epub_is_a_valid_epub3_zip_with_wellformed_pages(tmp_path):
    chapters = [{"title": "Caching & Speed", "notes": _NOTES}, {"title": "Two", "notes": "## Next\nMore."}]

    path = export.write_epub(chapters, tmp_path / "book.epub", "My <Book>", "Study Notes")

    with zipfile.ZipFile(path) as epub:
        first = epub.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
        assert epub.read("mimetype") == b"application/epub+zip"
        names = set(epub.namelist())
        assert {"META-INF/container.xml", "OEBPS/content.opf", "OEBPS/nav.xhtml"} <= names
        assert {"OEBPS/chapter001.xhtml", "OEBPS/chapter002.xhtml"} <= names
        for name in names - {"mimetype"}:
            ET.fromstring(epub.read(name))  # every XML/XHTML file is well-formed
        page = epub.read("OEBPS/chapter001.xhtml").decode("utf-8")
        assert "<table>" in page and "<mark>cache</mark>" in page
        assert "My &lt;Book&gt;" in epub.read("OEBPS/content.opf").decode("utf-8")
