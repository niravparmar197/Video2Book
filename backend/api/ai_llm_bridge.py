"""Imports ai_llm's standalone `app.graph` module.

ai_llm/ is a standalone CLI project whose internal package is named `app`
(ai_llm/app/graph.py etc.) and is intentionally not pip-installed as a
package -- root AGENTS.md requires it keep working standalone from the CLI.
This project's own package is named `api` specifically so it never imports
anything named `app` itself, which lets us add ai_llm/ to sys.path just
long enough to import its `app.graph` module without a name collision.
"""

import importlib
import sys
from pathlib import Path

_AI_LLM_ROOT = Path(__file__).resolve().parents[2] / "ai_llm"


def _import_graph():
    root_str = str(_AI_LLM_ROOT)
    inserted = root_str not in sys.path
    if inserted:
        sys.path.insert(0, root_str)
    try:
        return importlib.import_module("app.graph")
    finally:
        if inserted:
            sys.path.remove(root_str)


_graph = _import_graph()
run_book = _graph.run_book
run_plan = _graph.run_plan
resume_book = _graph.resume_book
get_progress = _graph.get_progress
