"""Unit tests for app.nodes.book_pass — glossary/index-term/preface generation.

No real LLM calls: app.nodes.book_pass.call_writer is monkeypatched.
"""
import json

from app.nodes import book_pass as book_pass_node


def test_run_glossary_merges_and_dedupes_across_chapters(tmp_path, monkeypatch):
    chapters = [
        {"title": "Chapter One", "notes": "Gradient descent is an optimization algorithm."},
        {"title": "Chapter Two", "notes": "Gradient descent also appears here."},
    ]

    stubbed_response = json.dumps(
        [
            {
                "term": "Gradient Descent",
                "definition": "An optimization algorithm that iteratively adjusts parameters.",
            },
            {
                "term": "gradient descent",
                "definition": "A duplicate, worse definition that should be dropped.",
            },
            {"term": "Loss Function", "definition": "A function measuring prediction error."},
        ]
    )
    monkeypatch.setattr(book_pass_node, "call_writer", lambda prompt, **kw: stubbed_response)

    glossary = book_pass_node.run_glossary(chapters, tmp_path)

    terms = [entry["term"] for entry in glossary]
    assert len(terms) == 2
    assert "Gradient Descent" in terms

    gd_entry = next(entry for entry in glossary if entry["term"] == "Gradient Descent")
    assert "iteratively adjusts" in gd_entry["definition"]

    payload = json.loads(
        (tmp_path / "work" / "book_pass" / "glossary.json").read_text(encoding="utf-8")
    )
    assert payload == glossary


def test_run_glossary_prompt_includes_every_chapter(tmp_path, monkeypatch):
    chapters = [
        {"title": "Alpha Chapter", "notes": "UNIQUE_ALPHA_TEXT"},
        {"title": "Beta Chapter", "notes": "UNIQUE_BETA_TEXT"},
    ]

    captured = {}

    def fake_call_writer(prompt, **kw):
        captured["prompt"] = prompt
        return "[]"

    monkeypatch.setattr(book_pass_node, "call_writer", fake_call_writer)

    book_pass_node.run_glossary(chapters, tmp_path)

    assert "Alpha Chapter" in captured["prompt"]
    assert "UNIQUE_ALPHA_TEXT" in captured["prompt"]
    assert "Beta Chapter" in captured["prompt"]
    assert "UNIQUE_BETA_TEXT" in captured["prompt"]


def test_run_glossary_retries_then_degrades_to_empty_on_unparseable_response(
    tmp_path, monkeypatch
):
    call_count = {"n": 0}

    def always_fails(prompt, **kw):
        call_count["n"] += 1
        return "I cannot comply with this request."

    monkeypatch.setattr(book_pass_node, "call_writer", always_fails)

    glossary = book_pass_node.run_glossary([{"title": "T", "notes": "N"}], tmp_path)

    assert call_count["n"] == 2
    assert glossary == []


def test_run_index_terms_parses_and_writes_terms(tmp_path, monkeypatch):
    monkeypatch.setattr(
        book_pass_node,
        "call_writer",
        lambda prompt, **kw: json.dumps(["Gradient Descent", "Backpropagation"]),
    )

    terms = book_pass_node.run_index_terms("vid1", "Some chapter notes.", tmp_path)

    assert terms == ["Gradient Descent", "Backpropagation"]
    payload = json.loads(
        (tmp_path / "work" / "book_pass" / "index_terms_vid1.json").read_text(encoding="utf-8")
    )
    assert payload == terms


def test_run_index_terms_dedupes_case_insensitively(tmp_path, monkeypatch):
    monkeypatch.setattr(
        book_pass_node,
        "call_writer",
        lambda prompt, **kw: json.dumps(["Gradient Descent", "gradient descent"]),
    )

    terms = book_pass_node.run_index_terms("vid1", "notes", tmp_path)

    assert terms == ["Gradient Descent"]


def test_run_index_terms_degrades_to_empty_list_on_unparseable_response(tmp_path, monkeypatch):
    monkeypatch.setattr(book_pass_node, "call_writer", lambda prompt, **kw: "not json at all")

    terms = book_pass_node.run_index_terms("vid1", "notes", tmp_path)

    assert terms == []


def test_run_preface_writes_file_and_includes_every_chapter_title(tmp_path, monkeypatch):
    captured = {}

    def fake_call_writer(prompt, **kw):
        captured["prompt"] = prompt
        return "This book covers neural networks from the ground up."

    monkeypatch.setattr(book_pass_node, "call_writer", fake_call_writer)

    chapters = [{"title": "Vectors"}, {"title": "Gradient Descent"}]
    path = book_pass_node.run_preface(chapters, tmp_path)

    assert path == tmp_path / "work" / "book_pass" / "preface.md"
    assert path.exists()
    assert "Vectors" in captured["prompt"]
    assert "Gradient Descent" in captured["prompt"]
    assert "This book covers neural networks" in path.read_text(encoding="utf-8")
