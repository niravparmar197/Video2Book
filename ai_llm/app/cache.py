"""Cache: skip a pipeline step whose output already exists on disk.

See root AGENTS.md crash safety: every step saves to disk so a crash or a
plain re-run never redoes completed work — in particular, never re-calls a
free-tier LLM for output that's already there.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable


def run_cached(output_path: str | Path, compute: Callable[[], None]) -> Path:
    """Call compute() only if output_path doesn't exist yet.

    compute() is expected to write output_path itself (each node owns its
    own serialization); this function only decides whether to call it.
    Returns output_path either way.
    """
    output_path = Path(output_path)
    if not output_path.exists():
        compute()
    return output_path
