"""Unit tests for app.nodes.book_pass — glossary/index-term generation.

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


def test_index_terms_come_from_glossary_terms_in_the_chapter_and_its_bold_terms(tmp_path, monkeypatch):
    def fail(prompt, **kw):
        raise AssertionError("index terms must not call the LLM")

    monkeypatch.setattr(book_pass_node, "call_writer", fail)
    notes = (
        "## Training\n"
        "**Gradient descent** lowers the loss. Backpropagation computes it.\n"
        "- A **learning rate** that is too big overshoots.\n"
        "- **gradient descent** again, and a **very long bold sentence that is not a term**.\n"
    )

    terms = book_pass_node.run_index_terms(
        "vid1", notes, tmp_path, glossary_terms=["Backpropagation", "Softmax"]
    )

    assert terms == ["Backpropagation", "Gradient descent", "learning rate"]
    payload = json.loads(
        (tmp_path / "work" / "book_pass" / "index_terms_vid1.json").read_text(encoding="utf-8")
    )
    assert payload == terms


def _chapter(index, size=1000):
    return {"title": f"Chapter {index}", "notes": "x" * size}


def test_index_terms_are_capped_per_chapter():
    notes = " ".join(f"**Term {i}**" for i in range(30))

    assert len(book_pass_node.index_terms_from_notes(notes, [])) == 10


def test_glossary_batches_split_a_large_book_in_order_and_keep_small_ones_whole():
    small = [_chapter(i) for i in range(5)]
    assert book_pass_node._glossary_batches(small) == [small]

    big = [_chapter(i, size=25_000) for i in range(6)]  # 25k chars each, 60k per batch
    batches = book_pass_node._glossary_batches(big)

    assert [len(batch) for batch in batches] == [2, 2, 2]
    assert [c for batch in batches for c in batch] == big


def test_run_glossary_on_a_13_hour_book_makes_one_call_per_batch_and_merges_and_dedupes(
    tmp_path, monkeypatch
):
    chapters = [_chapter(i, size=25_000) for i in range(6)]
    prompts = []

    def fake_call_writer(prompt, **kw):
        prompts.append(prompt)
        batch_number = len(prompts)
        return json.dumps(
            [
                {"term": "Shared Term", "definition": f"from batch {batch_number}"},
                {"term": f"Term {batch_number}", "definition": "d"},
            ]
        )

    monkeypatch.setattr(book_pass_node, "call_writer", fake_call_writer)

    glossary = book_pass_node.run_glossary(chapters, tmp_path)

    assert len(prompts) == 3  # not one giant prompt with all 150k characters
    assert all(len(prompt) < 70_000 for prompt in prompts)
    terms = [entry["term"] for entry in glossary]
    assert terms.count("Shared Term") == 1
    assert {"Term 1", "Term 2", "Term 3"} <= set(terms)


def test_run_glossary_keeps_the_other_batches_when_one_batch_never_returns_json(
    tmp_path, monkeypatch
):
    chapters = [_chapter(i, size=40_000) for i in range(3)]  # 3 batches
    answers = iter(["not json", "still not json", '[{"term": "Kept", "definition": "d"}]'])
    monkeypatch.setattr(book_pass_node, "call_writer", lambda prompt, **kw: "not json" if "Chapter 0" in prompt else '[{"term": "Kept", "definition": "d"}]')

    glossary = book_pass_node.run_glossary(chapters, tmp_path)

    assert [entry["term"] for entry in glossary] == ["Kept"]
