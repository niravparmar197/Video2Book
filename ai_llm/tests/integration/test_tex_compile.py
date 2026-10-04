"""Integration test: a real latexmk -lualatex compile, no mocking.

Skipped automatically if latexmk isn't on PATH. This is the one place in the
test suite allowed to shell out to a real local binary (not a network call,
not an LLM) — see tests/unit/test_tex.py for the mocked unit tests.
"""
import shutil

import pytest
from PIL import Image

from app.latex.tex import compile_chapter, render_book, render_chapter

pytestmark = pytest.mark.skipif(
    shutil.which("latexmk") is None, reason="latexmk not installed on PATH"
)

SAMPLE_NOTES = """## Neural Networks

A neural network is made of layers of neurons.

## Gradient Descent

Gradient descent minimizes the loss function using 50% momentum & a $0.01 rate.
"""

SAMPLE_NOTES_2 = """## Backpropagation

Backpropagation computes gradients via the chain rule.
"""

SAMPLE_NOTES_WITH_VISUALS = """## Network Size

The network has three layers with 784, 16, and 10 neurons respectively.

```chart
{"type": "bar", "title": "Neurons per layer", "categories": ["Input", "Hidden", "Output"], "values": [784, 16, 10]}
```

## Layer Structure

Data flows from the input layer through the hidden layer to the output layer.

```diagram
{"nodes": ["Input", "Hidden", "Output"], "edges": [["Input", "Hidden"], ["Hidden", "Output"]]}
```

## Layer Comparison

```table
{"headers": ["Layer", "Neurons"], "rows": [["Input", "784"], ["Hidden", "16"], ["Output", "10"]]}
```
"""


def test_render_and_compile_produces_a_real_multi_chapter_pdf(tmp_path):
    render_chapter("chapter1", "But what is a neural network?", SAMPLE_NOTES, tmp_path)
    render_chapter("chapter2", "Gradient descent, how neural networks learn", SAMPLE_NOTES_2, tmp_path)

    main_tex_path = render_book(["chapter1", "chapter2"], tmp_path)
    pdf_path = compile_chapter(main_tex_path)

    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert pdf_path.stat().st_size > 0


def test_render_and_compile_with_a_real_embedded_screenshot(tmp_path):
    assets_dir = tmp_path / "assets" / "chapter1"
    assets_dir.mkdir(parents=True)
    image_path = assets_dir / "000_00.jpg"
    Image.new("RGB", (320, 180), color=(60, 90, 120)).save(image_path)

    render_chapter(
        "chapter1",
        "But what is a neural network?",
        SAMPLE_NOTES,
        tmp_path,
        screenshots=[{"asset_path": str(image_path), "timestamp_seconds": 42.0}],
    )
    main_tex_path = render_book(["chapter1"], tmp_path)
    pdf_path = compile_chapter(main_tex_path)

    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF")
    # A real image roughly doubles a text-only chapter's PDF size.
    assert pdf_path.stat().st_size > 5000


@pytest.mark.skipif(shutil.which("dot") is None, reason="Graphviz dot not installed on PATH")
def test_render_and_compile_with_real_table_diagram_and_chart(tmp_path):
    render_chapter("chapter1", "Neural Network Sizing", SAMPLE_NOTES_WITH_VISUALS, tmp_path)
    main_tex_path = render_book(["chapter1"], tmp_path)
    pdf_path = compile_chapter(main_tex_path)

    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert pdf_path.stat().st_size > 5000

    assets_dir = tmp_path / "assets" / "chapter1"
    assert (assets_dir / "chart_00_00.png").exists()
    assert (assets_dir / "diagram_01_00.png").exists()


def test_render_and_compile_with_a_real_subject_index(tmp_path):
    # Both terms must actually appear in SAMPLE_NOTES' paragraph body text
    # (not just a section heading) -- index markup is only inserted into
    # paragraphs, matching real usage.
    render_chapter(
        "chapter1",
        "Neural Network Basics",
        SAMPLE_NOTES,
        tmp_path,
        index_terms=["Gradient Descent", "neural network"],
    )
    main_tex_path = render_book(["chapter1"], tmp_path)
    pdf_path = compile_chapter(main_tex_path)

    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF")

    # latexmk auto-runs makeindex when it detects \makeindex in the source
    # (no manual makeindex subprocess call needed in this codebase); a
    # non-empty .ind file is direct proof it actually ran and found entries.
    index_file = main_tex_path.with_suffix(".ind")
    assert index_file.exists()
    index_content = index_file.read_text(encoding="utf-8")
    assert "Gradient Descent" in index_content
    assert "neural network" in index_content


def test_render_and_compile_full_book_with_glossary_and_callouts(tmp_path):
    callouts = (
        "\n> Key point: A ==layered== model.\n"
        "> Example: One hidden layer.\n"
        "> Watch out: Overfitting & 50% noise.\n"
    )
    render_chapter(
        "chapter1",
        "Chapter One",
        SAMPLE_NOTES + callouts,
        tmp_path,
        index_terms=["Gradient Descent"],
    )

    main_tex_path = render_book(
        ["chapter1"],
        tmp_path,
        glossary_entries=[
            {"term": "Neural Network", "definition": "A layered computational model."}
        ],
    )
    pdf_path = compile_chapter(main_tex_path)

    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert pdf_path.stat().st_size > 5000


def test_a_chapter_with_dozens_of_screenshots_in_one_section_still_compiles(tmp_path):
    # A real 27-minute lecture produced 153 screenshots; with [h] placement
    # LaTeX died with "Too many unprocessed floats" after all the LLM work.
    from PIL import Image

    shots = []
    for index in range(60):
        path = tmp_path / "assets" / f"s{index}.jpg"
        path.parent.mkdir(exist_ok=True)
        Image.new("RGB", (320, 180), (index * 4 % 255, 90, 160)).save(path)
        shots.append({"asset_path": str(path), "timestamp_seconds": index * 20})

    render_chapter("c1", "Many screenshots", "## One section\nText.\n", tmp_path, screenshots=shots)
    pdf_path = compile_chapter(render_book(["c1"], tmp_path))

    assert pdf_path.read_bytes().startswith(b"%PDF")


def test_youtube_links_in_screenshot_captions_and_sections_compile_and_are_clickable(tmp_path):
    import fitz
    from PIL import Image

    shot = tmp_path / "assets" / "a_b-C_d-E1" / "000_00.jpg"
    shot.parent.mkdir(parents=True)
    Image.new("RGB", (320, 180), (40, 90, 160)).save(shot)

    render_chapter(
        "c1",
        "Links",
        "## Intro\nText.\n",
        tmp_path,
        screenshots=[{"asset_path": str(shot), "timestamp_seconds": 75}],
        section_times=[("a_b-C_d-E1", 60.0)],
    )
    pdf_path = compile_chapter(render_book(["c1"], tmp_path))

    uris = {link.get("uri") for page in fitz.open(pdf_path) for link in page.get_links()}
    assert "https://youtu.be/a_b-C_d-E1?t=60" in uris
    assert "https://youtu.be/a_b-C_d-E1?t=75" in uris
