"""Unit tests for app.latex.tex — Markdown notes -> .tex chapter.

No real latexmk invocation here: compile_chapter's subprocess runner is
replaced with a fake. See tests/integration/test_tex_compile.py for a real
end-to-end latexmk compile.
"""
from pathlib import Path

import pytest

from app.latex.tex import (
    Section,
    Visual,
    compile_chapter,
    escape_latex,
    markdown_notes_to_sections,
    render_book,
    render_book_volumes,
    render_chapter,
    render_glossary,
    render_topic_index,
    split_into_volumes,
)

SAMPLE_NOTES = """## Neural Networks

A neural network is made of layers of neurons.

It learns by adjusting weights.

## Gradient Descent

Gradient descent minimizes the loss function.
"""


def test_escape_latex_escapes_special_characters():
    assert escape_latex("100% & $5 #1 {a} ~b ^c \\d") == (
        r"100\% \& \$5 \#1 \{a\} \textasciitilde{}b "
        r"\textasciicircum{}c \textbackslash{}d"
    )


def test_escape_latex_leaves_plain_text_untouched():
    assert escape_latex("plain text with no special chars") == "plain text with no special chars"


def test_escape_latex_normalizes_unusual_unicode_spaces():
    # Latin Modern (LuaLaTeX's default font) has no glyph for these --
    # verified against a real compiled book where a narrow no-break space
    # (U+202F) before "T1" rendered as a broken character.
    assert escape_latex("transaction T1") == "transaction T1"
    assert escape_latex("a b c d") == "a b c d"


def test_markdown_notes_to_sections_converts_bold_and_italic_emphasis():
    sections = markdown_notes_to_sections(
        "## Isolation\n\nThe **serializable** level is *strict*.\n"
    )

    assert sections[0].paragraphs == [r"The \textbf{serializable} level is \textit{strict}."]


def test_markdown_notes_to_sections_parses_headings_and_paragraphs():
    sections = markdown_notes_to_sections(SAMPLE_NOTES)

    assert len(sections) == 2
    assert sections[0].heading == "Neural Networks"
    assert sections[0].paragraphs == [
        "A neural network is made of layers of neurons.",
        "It learns by adjusting weights.",
    ]
    assert sections[1].heading == "Gradient Descent"
    assert sections[1].paragraphs == ["Gradient descent minimizes the loss function."]


def test_markdown_notes_to_sections_escapes_special_chars_in_content():
    sections = markdown_notes_to_sections("## 50% Progress\n\nCost is $5 & rising.\n")

    assert sections[0].heading == r"50\% Progress"
    assert sections[0].paragraphs == [r"Cost is \$5 \& rising."]


def test_markdown_notes_to_sections_parses_a_chart_block():
    notes = (
        "## Network Size\n\n"
        "The network has three layers.\n\n"
        "```chart\n"
        '{"type": "bar", "title": "Neurons per layer", '
        '"categories": ["Input", "Hidden", "Output"], "values": [784, 16, 10]}\n'
        "```\n"
    )

    sections = markdown_notes_to_sections(notes)

    assert len(sections) == 1
    assert sections[0].paragraphs == ["The network has three layers."]
    assert len(sections[0].visuals) == 1
    visual = sections[0].visuals[0]
    assert visual.kind == "chart"
    assert visual.data["categories"] == ["Input", "Hidden", "Output"]
    assert visual.data["values"] == [784, 16, 10]


def test_markdown_notes_to_sections_parses_table_and_diagram_blocks():
    notes = (
        "## Comparison\n\n"
        "```table\n"
        '{"headers": ["Layer", "Size"], "rows": [["Input", "784"], ["Output", "10"]]}\n'
        "```\n\n"
        "## Architecture\n\n"
        "```diagram\n"
        '{"nodes": ["Input", "Hidden", "Output"], "edges": [["Input", "Hidden"], ["Hidden", "Output"]]}\n'
        "```\n"
    )

    sections = markdown_notes_to_sections(notes)

    assert len(sections) == 2
    assert sections[0].visuals[0].kind == "table"
    assert sections[0].visuals[0].data["headers"] == ["Layer", "Size"]
    assert sections[1].visuals[0].kind == "diagram"
    assert sections[1].visuals[0].data["nodes"] == ["Input", "Hidden", "Output"]


def test_markdown_notes_to_sections_no_visuals_when_no_fenced_block():
    sections = markdown_notes_to_sections(SAMPLE_NOTES)

    assert sections[0].visuals == []
    assert sections[1].visuals == []


def test_markdown_notes_to_sections_ignores_malformed_visual_block():
    notes = "## Topic\n\nSome prose.\n\n```chart\nnot valid json\n```\n"

    sections = markdown_notes_to_sections(notes)

    assert sections[0].paragraphs == ["Some prose."]
    assert sections[0].visuals == []


def test_render_chapter_writes_tex_file(tmp_path):
    tex_path = render_chapter("aircAruvnKk", "But what is a neural network?", SAMPLE_NOTES, tmp_path)

    assert tex_path == tmp_path / "chapters" / "aircAruvnKk.tex"
    assert tex_path.exists()
    content = tex_path.read_text(encoding="utf-8")
    assert r"\chapter{But what is a neural network?}" in content
    assert r"\section{Neural Networks}" in content
    assert r"\section{Gradient Descent}" in content
    assert "A neural network is made of layers of neurons." in content
    # A chapter is now an includable fragment (\input from main.tex.j2), not
    # a standalone document — see sprints/v2/PRD.md multi-chapter compile.
    assert r"\documentclass" not in content
    assert r"\begin{document}" not in content


def test_render_chapter_never_contains_unescaped_model_text(tmp_path):
    notes = "## Costs\n\nThe course costs $100 & takes 50% longer.\n"
    tex_path = render_chapter("vid", "Title", notes, tmp_path)
    content = tex_path.read_text(encoding="utf-8")
    assert r"\$100" in content
    assert r"\&" in content
    assert r"\%" in content


def test_render_book_writes_main_tex_with_toc_and_ordered_inputs(tmp_path):
    render_chapter("vid1", "Chapter One", SAMPLE_NOTES, tmp_path)
    render_chapter("vid2", "Chapter Two", SAMPLE_NOTES, tmp_path)

    main_tex_path = render_book(["vid1", "vid2"], tmp_path)

    assert main_tex_path == tmp_path / "chapters" / "main.tex"
    content = main_tex_path.read_text(encoding="utf-8")
    assert r"\tableofcontents" in content
    assert r"\input{vid1}" in content
    assert r"\input{vid2}" in content
    assert content.index(r"\input{vid1}") < content.index(r"\input{vid2}")


def test_render_book_uses_given_book_title(tmp_path):
    main_tex_path = render_book([], tmp_path, book_title="ACID Properties in Databases")

    content = main_tex_path.read_text(encoding="utf-8")
    assert r"\title{ACID Properties in Databases}" in content


def test_render_book_defaults_title_to_video2book(tmp_path):
    main_tex_path = render_book([], tmp_path)

    content = main_tex_path.read_text(encoding="utf-8")
    assert r"\title{Video2Book}" in content


def test_render_book_empty_chapter_list_still_writes_valid_shell(tmp_path):
    main_tex_path = render_book([], tmp_path)

    content = main_tex_path.read_text(encoding="utf-8")
    assert r"\begin{document}" in content
    assert r"\end{document}" in content
    assert r"\input{" not in content


class _FakeCompletedProcess:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_compile_chapter_invokes_latexmk_with_expected_args(tmp_path):
    tex_path = tmp_path / "chapters" / "vid.tex"
    tex_path.parent.mkdir(parents=True)
    tex_path.write_text("\\documentclass{article}\\begin{document}x\\end{document}")

    captured_args = {}

    def fake_runner(args, **kwargs):
        captured_args["args"] = args
        # Simulate latexmk producing a PDF next to the .tex file.
        tex_path.with_suffix(".pdf").write_bytes(b"%PDF-fake")
        return _FakeCompletedProcess(returncode=0)

    pdf_path = compile_chapter(tex_path, runner=fake_runner)

    assert pdf_path == tex_path.with_suffix(".pdf")
    assert pdf_path.exists()
    args = captured_args["args"]
    assert "latexmk" in args[0]
    assert "-lualatex" in args
    assert "-halt-on-error" in args
    assert str(tex_path) in args


def test_compile_chapter_raises_on_latexmk_failure(tmp_path):
    tex_path = tmp_path / "chapters" / "vid.tex"
    tex_path.parent.mkdir(parents=True)
    tex_path.write_text("broken")

    def fake_runner(args, **kwargs):
        return _FakeCompletedProcess(returncode=1, stdout="! Undefined control sequence.")

    with pytest.raises(RuntimeError, match="latexmk failed"):
        compile_chapter(tex_path, runner=fake_runner)


def test_render_chapter_embeds_screenshots_as_figures_in_timestamp_order(tmp_path):
    assets_dir = tmp_path / "assets" / "vid1"
    assets_dir.mkdir(parents=True)
    shot_a = assets_dir / "000_00.jpg"
    shot_b = assets_dir / "000_01.jpg"
    shot_a.write_bytes(b"fake-jpeg-a")
    shot_b.write_bytes(b"fake-jpeg-b")

    screenshots = [
        {"asset_path": str(shot_b), "timestamp_seconds": 90.0},
        {"asset_path": str(shot_a), "timestamp_seconds": 12.0},
    ]

    tex_path = render_chapter("vid1", "Title", SAMPLE_NOTES, tmp_path, screenshots=screenshots)
    content = tex_path.read_text(encoding="utf-8")

    assert content.count(r"\includegraphics") == 2
    # Timestamp order: shot_a (12s) before shot_b (90s), regardless of the
    # order screenshots were passed in.
    assert content.index("000_00.jpg") < content.index("000_01.jpg")
    assert "../assets/vid1/000_00.jpg" in content
    assert "Screenshot at 00:12" in content
    assert "Screenshot at 01:30" in content
    # Screenshots are split across the chapter's two sections (one each)
    # and placed right after their own section, not dumped together after
    # the whole chapter -- shot_a lands with the first section (before the
    # second section's heading), shot_b with the second (after its text).
    assert content.index("000_00.jpg") < content.index("Gradient Descent")
    assert content.index("Gradient descent minimizes") < content.index("000_01.jpg")


def test_render_chapter_with_no_screenshots_has_no_figures(tmp_path):
    tex_path = render_chapter("vid1", "Title", SAMPLE_NOTES, tmp_path)
    content = tex_path.read_text(encoding="utf-8")

    assert r"\includegraphics" not in content


def test_render_chapter_renders_visuals_after_their_own_section(tmp_path, monkeypatch):
    import app.nodes.render as render_module

    monkeypatch.setattr(
        render_module, "render_table", lambda data: r"\begin{tabular}{l}FAKE\end{tabular}"
    )

    def fake_render_image(data, output_path):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-png")
        return output_path

    monkeypatch.setattr(render_module, "render_diagram", fake_render_image)
    monkeypatch.setattr(render_module, "render_chart", fake_render_image)

    notes = (
        "## Chart Section\n\n"
        "Some prose.\n\n"
        "```chart\n"
        '{"type": "bar", "title": "My Chart", "categories": ["A"], "values": [1]}\n'
        "```\n\n"
        "## Table Section\n\n"
        "```table\n"
        '{"headers": ["H"], "rows": [["R"]]}\n'
        "```\n"
    )

    tex_path = render_chapter("vid1", "Title", notes, tmp_path)
    content = tex_path.read_text(encoding="utf-8")

    assert content.index("Chart Section") < content.index(r"\includegraphics")
    assert "My Chart" in content
    assert content.index("Table Section") < content.index("FAKE")
    assert r"\begin{tabular}{l}FAKE\end{tabular}" in content


def test_render_chapter_skips_a_visual_that_fails_to_render(tmp_path, monkeypatch):
    import app.nodes.render as render_module

    def failing_render_chart(data, output_path):
        raise RuntimeError("boom")

    monkeypatch.setattr(render_module, "render_chart", failing_render_chart)

    notes = (
        "## Section\n\nSome prose.\n\n```chart\n"
        '{"type": "bar", "categories": [], "values": []}\n```\n'
    )

    # Must not raise -- a bad visual is skipped, not fatal to the chapter.
    tex_path = render_chapter("vid1", "Title", notes, tmp_path)
    content = tex_path.read_text(encoding="utf-8")

    assert "Some prose." in content
    assert r"\includegraphics" not in content


def test_render_chapter_inserts_index_markup_at_first_occurrence_only(tmp_path):
    notes = (
        "## Section One\n\n"
        "Gradient descent is an optimization method. Gradient descent is popular.\n\n"
        "## Section Two\n\n"
        "Backpropagation computes gradients.\n"
    )

    tex_path = render_chapter(
        "vid1", "Title", notes, tmp_path, index_terms=["Gradient Descent", "Backpropagation"]
    )
    content = tex_path.read_text(encoding="utf-8")

    assert content.count(r"\index{Gradient Descent}") == 1
    assert r"\index{Backpropagation}" in content

    first_occurrence = content.index("Gradient descent")
    index_mark_pos = content.index(r"\index{Gradient Descent}")
    second_occurrence = content.index("Gradient descent is popular")
    assert first_occurrence < index_mark_pos < second_occurrence


def test_render_chapter_with_no_index_terms_has_no_index_markup(tmp_path):
    tex_path = render_chapter("vid1", "Title", SAMPLE_NOTES, tmp_path)
    content = tex_path.read_text(encoding="utf-8")

    assert r"\index{" not in content


def test_render_chapter_skips_a_term_not_present_in_the_chapter(tmp_path):
    tex_path = render_chapter(
        "vid1", "Title", SAMPLE_NOTES, tmp_path, index_terms=["Nonexistent Term"]
    )
    content = tex_path.read_text(encoding="utf-8")

    assert r"\index{" not in content


def test_render_topic_index_lists_titles_in_order(tmp_path):
    chapters = [{"title": "Vectors"}, {"title": "Gradient Descent"}, {"title": "Backpropagation"}]

    tex_path = render_topic_index(chapters, tmp_path)

    assert tex_path == tmp_path / "chapters" / "topic_index.tex"
    content = tex_path.read_text(encoding="utf-8")
    assert (
        content.index("Vectors")
        < content.index("Gradient Descent")
        < content.index("Backpropagation")
    )


def test_render_topic_index_escapes_special_characters(tmp_path):
    tex_path = render_topic_index([{"title": "50% Progress & More"}], tmp_path)
    content = tex_path.read_text(encoding="utf-8")

    assert r"50\% Progress \& More" in content


def test_render_glossary_writes_escaped_entries(tmp_path):
    entries = [
        {"term": "Gradient Descent", "definition": "An optimization method."},
        {"term": "50% Rule", "definition": "Uses $ signs & percentages."},
    ]

    tex_path = render_glossary(entries, tmp_path)

    assert tex_path == tmp_path / "chapters" / "glossary.tex"
    content = tex_path.read_text(encoding="utf-8")
    assert "Gradient Descent" in content
    assert "An optimization method." in content
    assert r"50\% Rule" in content
    assert r"\$ signs \& percentages" in content


def test_render_book_assembles_front_and_back_matter_in_order(tmp_path):
    render_chapter("chapter1", "Chapter One", SAMPLE_NOTES, tmp_path)
    render_topic_index([{"title": "Chapter One"}], tmp_path)

    preface_path = tmp_path / "preface.md"
    preface_path.write_text("This book covers the basics.\n\nEnjoy!\n", encoding="utf-8")

    main_tex_path = render_book(
        ["chapter1"],
        tmp_path,
        preface_path=preface_path,
        glossary_entries=[{"term": "Term", "definition": "Definition."}],
        include_topic_index=True,
    )
    content = main_tex_path.read_text(encoding="utf-8")

    title_pos = content.index(r"\begin{titlepage}")
    preface_pos = content.index("This book covers the basics.")
    toc_pos = content.index(r"\tableofcontents")
    chapter_pos = content.index(r"\input{chapter1}")
    glossary_pos = content.index(r"\input{glossary}")
    index_pos = content.index(r"\printindex")
    topic_index_pos = content.index(r"\input{topic_index}")

    assert (
        title_pos
        < preface_pos
        < toc_pos
        < chapter_pos
        < glossary_pos
        < index_pos
        < topic_index_pos
    )


def test_render_book_without_optional_matter_omits_those_sections(tmp_path):
    render_chapter("chapter1", "Chapter One", SAMPLE_NOTES, tmp_path)

    main_tex_path = render_book(["chapter1"], tmp_path)
    content = main_tex_path.read_text(encoding="utf-8")

    assert "Preface" not in content
    assert r"\input{glossary}" not in content
    assert r"\input{topic_index}" not in content
    assert r"\printindex" in content  # always present, harmless when empty


def test_split_into_volumes_fits_in_one_when_under_threshold(tmp_path):
    chapters = [("vid1", 2.0), ("vid2", 3.0)]

    volumes = split_into_volumes(chapters, volume_hours=10.0)

    assert volumes == [["vid1", "vid2"]]


def test_split_into_volumes_splits_over_threshold_preserving_order(tmp_path):
    chapters = [("vid1", 6.0), ("vid2", 6.0), ("vid3", 6.0), ("vid4", 6.0)]

    volumes = split_into_volumes(chapters, volume_hours=10.0)

    # vid1(6)+vid2(6)=12 > 10, so vid2 starts a new volume.
    assert volumes == [["vid1"], ["vid2"], ["vid3"], ["vid4"]]


def test_split_into_volumes_never_splits_a_single_long_chapter(tmp_path):
    chapters = [("vid1", 25.0)]

    volumes = split_into_volumes(chapters, volume_hours=10.0)

    assert volumes == [["vid1"]]


def test_render_book_volumes_produces_one_file_per_group(tmp_path):
    render_chapter("vid1", "Video One", SAMPLE_NOTES, tmp_path)
    render_chapter("vid2", "Video Two", SAMPLE_NOTES, tmp_path)

    paths = render_book_volumes([["vid1"], ["vid2"]], tmp_path)

    assert paths == [
        tmp_path / "chapters" / "main_vol1.tex",
        tmp_path / "chapters" / "main_vol2.tex",
    ]
    vol1 = paths[0].read_text(encoding="utf-8")
    vol2 = paths[1].read_text(encoding="utf-8")
    assert r"\input{vid1}" in vol1
    assert r"\input{vid2}" not in vol1
    assert r"\input{vid2}" in vol2
    assert "Volume 1" in vol1
    assert "Volume 2" in vol2


def test_render_book_volumes_puts_preface_in_first_and_back_matter_in_last(tmp_path):
    render_chapter("vid1", "Video One", SAMPLE_NOTES, tmp_path)
    render_chapter("vid2", "Video Two", SAMPLE_NOTES, tmp_path)
    render_topic_index([{"title": "Video One"}, {"title": "Video Two"}], tmp_path)

    preface_path = tmp_path / "preface.md"
    preface_path.write_text("This book covers two videos.\n", encoding="utf-8")

    paths = render_book_volumes(
        [["vid1"], ["vid2"]],
        tmp_path,
        preface_path=preface_path,
        glossary_entries=[{"term": "Term", "definition": "Def."}],
        include_topic_index=True,
    )
    vol1 = paths[0].read_text(encoding="utf-8")
    vol2 = paths[1].read_text(encoding="utf-8")

    assert "This book covers two videos." in vol1
    assert "This book covers two videos." not in vol2
    assert r"\input{glossary}" not in vol1
    assert r"\input{glossary}" in vol2
    assert r"\input{topic_index}" not in vol1
    assert r"\input{topic_index}" in vol2
