"""Shared pytest fixtures for the unit test suite.

VIDEO_MODE defaults to captions_only for every unit test: graph.py's
_frames_node (sprints/v4) is real ffmpeg/yt-dlp work that must never run in
a unit test (root AGENTS.md: never call a real network/API in a unit
test). Tests that specifically exercise the frames node override this
locally with monkeypatch.setenv("VIDEO_MODE", "stream").

app.nodes.verify.call_writer defaults to an always-passing stub judge
response for every unit test: write.py's refine loop (sprints/v5) calls
run_verify() internally, which is a *separate* real LLM call from
write.py's own call_writer -- a test that only mocks write_module's
call_writer would otherwise leave the judge call unmocked and hit a real
API. Tests that specifically exercise the refine loop override this
locally with monkeypatch.setattr(verify_module, "call_writer", ...).

app.nodes.book_pass.call_writer defaults to an inert "[]" response for the
same reason: graph.py's book_pass node (sprints/v6) calls
run_glossary()/run_index_terms()/run_preface() internally, each a
*separate* real LLM call from write.py's/topics.py's own call_writer. "[]"
degrades glossary/index-terms to empty (harmless) and becomes the literal
preface text (harmless unless a test asserts specific preface content).
Tests that specifically exercise book_pass override this locally.

app.llm._last_call_at (sprints/v7 proactive rate-limit pacing) is reset
before every unit test: it's process-wide, mutable, module-level state, so
without a reset a fast-running earlier test could leave a provider's "last
call" timestamp close enough to "now" that a later test's call_writer call
triggers a real (or real-if-unmocked) pacing sleep -- test isolation, not a
behavior test in itself.
"""
import json

import pytest


@pytest.fixture(autouse=True)
def _default_captions_only_video_mode(monkeypatch):
    monkeypatch.setenv("VIDEO_MODE", "captions_only")


@pytest.fixture(autouse=True)
def _default_passing_judge(monkeypatch):
    from app.nodes import verify as verify_module

    monkeypatch.setattr(
        verify_module,
        "call_writer",
        lambda prompt, **kw: json.dumps({"score": 10, "feedback": "looks good"}),
    )


@pytest.fixture(autouse=True)
def _default_inert_book_pass(monkeypatch):
    from app.nodes import book_pass as book_pass_module

    monkeypatch.setattr(book_pass_module, "call_writer", lambda prompt, **kw: "[]")


@pytest.fixture(autouse=True)
def _reset_llm_rate_limit_pacing_state(monkeypatch):
    from app import llm as llm_module

    monkeypatch.setattr(llm_module, "_last_call_at", {})
