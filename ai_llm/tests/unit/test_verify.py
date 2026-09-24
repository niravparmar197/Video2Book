"""Unit tests for app.nodes.verify — judge score for a written section.

No real LLM calls: app.nodes.verify.call_writer is monkeypatched.
"""
import json

from app.nodes import verify as verify_node


def test_run_verify_parses_a_passing_score(monkeypatch):
    monkeypatch.setattr(
        verify_node,
        "call_writer",
        lambda prompt, **kw: json.dumps({"score": 9, "feedback": "Great section."}),
    )

    result = verify_node.run_verify("transcript text", "notes text")

    assert result.score == 9
    assert result.feedback == "Great section."


def test_run_verify_parses_a_failing_score(monkeypatch):
    monkeypatch.setattr(
        verify_node,
        "call_writer",
        lambda prompt, **kw: json.dumps({"score": 4, "feedback": "Missing key facts."}),
    )

    result = verify_node.run_verify("transcript text", "notes text")

    assert result.score == 4
    assert result.feedback == "Missing key facts."


def test_run_verify_includes_transcript_and_notes_in_prompt(monkeypatch):
    captured = {}

    def fake_call_writer(prompt, **kw):
        captured["prompt"] = prompt
        return json.dumps({"score": 8, "feedback": "ok"})

    monkeypatch.setattr(verify_node, "call_writer", fake_call_writer)

    verify_node.run_verify("UNIQUE_TRANSCRIPT_TEXT", "UNIQUE_NOTES_TEXT")

    assert "UNIQUE_TRANSCRIPT_TEXT" in captured["prompt"]
    assert "UNIQUE_NOTES_TEXT" in captured["prompt"]


def test_run_verify_degrades_to_borderline_score_on_malformed_response(monkeypatch):
    monkeypatch.setattr(verify_node, "call_writer", lambda prompt, **kw: "I cannot comply.")

    result = verify_node.run_verify("transcript", "notes")

    assert result.score < 7  # below default PASS_SCORE, triggers a refine attempt
    assert result.feedback


def test_run_verify_extracts_json_from_surrounding_prose(monkeypatch):
    response = 'Here is my evaluation: {"score": 6, "feedback": "Decent but thin."} Hope that helps.'
    monkeypatch.setattr(verify_node, "call_writer", lambda prompt, **kw: response)

    result = verify_node.run_verify("transcript", "notes")

    assert result.score == 6
    assert result.feedback == "Decent but thin."
