"""Imports ai_llm's standalone `app` modules (`app.graph`, `app.estimate`,
`app.config`).

ai_llm/ is a standalone CLI project whose internal package is named `app`
(ai_llm/app/graph.py etc.) and is intentionally not pip-installed as a
package -- root AGENTS.md requires it keep working standalone from the CLI.
This project's own package is named `api` specifically so it never imports
anything named `app` itself, which lets us add ai_llm/ to sys.path just
long enough to import its `app.*` modules without a name collision.
"""

import importlib
import sys
from pathlib import Path

_AI_LLM_ROOT = Path(__file__).resolve().parents[2] / "ai_llm"


def _import(name: str):
    root_str = str(_AI_LLM_ROOT)
    inserted = root_str not in sys.path
    if inserted:
        sys.path.insert(0, root_str)
    try:
        return importlib.import_module(name)
    finally:
        if inserted:
            sys.path.remove(root_str)


_graph = _import("app.graph")
run_book = _graph.run_book
run_plan = _graph.run_plan
resume_book = _graph.resume_book
get_progress = _graph.get_progress
get_chapter_progress = _graph.get_chapter_progress
get_warnings = _graph.get_warnings
get_timings = _graph.get_timings

_genre = _import("app.nodes.genre")
save_genre = _genre.save_genre
load_genre = _genre.load_genre
decided_book_kind = _genre.decided_book_kind

_youtube = _import("app.youtube")
VideoUnavailableError = _youtube.VideoUnavailableError

_estimate = _import("app.estimate")
_config = _import("app.config")
estimate_playlist = _estimate.estimate_playlist
# A function reference, not a value baked in at import time (sprints/v8) --
# same reason run_book/run_plan aren't called eagerly here -- so a
# monkeypatched env var takes effect on the next call without reimporting
# anything, and the backend never carries its own copy of
# MAX_BOOK_HOURS/MAX_BOOK_COST_USD that could drift from ai_llm's.
load_settings = _config.load_settings
