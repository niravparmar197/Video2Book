"""Order node: topological sort of merged topics by needs/level (BOOK_ORDER=topic).

A topic never appears before a topic it needs; among topics free to place,
easier topics (lower level) come first, ties broken by earliest source
appearance (original playlist video order, then chunk index). Cycles in
needs are broken automatically -- the lowest-level stuck topic is forced
through by dropping its remaining unresolved needs -- and every removal is
logged to order_log.txt, never silently dropped. See root AGENTS.md order.py
rules.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.nodes.plan import plan_json_path


def order_log_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "order_log.txt"


def ordered_plan_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "ordered_plan.json"


def _earliest_source_key(topic: dict, video_order: dict[str, int]) -> tuple[int, int]:
    sources = topic.get("sources", [])
    if not sources:
        return (len(video_order), 0)
    video_rank = min(video_order.get(source["video_id"], len(video_order)) for source in sources)
    chunk_rank = min(source["chunk_index"] for source in sources)
    return (video_rank, chunk_rank)


def order_topics(
    merged_topics: list[dict],
    video_order: dict[str, int] | None = None,
) -> tuple[list[dict], list[str]]:
    """Topological sort by needs, ties broken by level then earliest source.

    Returns (ordered_topics, log_lines): log_lines documents every needs
    edge that had to be removed to break a cycle (empty if there was no
    cycle). Never raises on a cycle.
    """
    video_order = video_order or {}

    by_title: dict[str, dict] = {}
    for topic in merged_topics:
        by_title.setdefault(topic["title"], topic)

    needs: dict[str, set[str]] = {}
    dependents: dict[str, set[str]] = {title: set() for title in by_title}
    for title, topic in by_title.items():
        resolved = {need for need in topic.get("needs", []) if need in by_title and need != title}
        needs[title] = resolved
        for need in resolved:
            dependents[need].add(title)

    def sort_key(title: str) -> tuple:
        topic = by_title[title]
        return (topic.get("level", 1), _earliest_source_key(topic, video_order), title)

    log_lines: list[str] = []
    ordered_titles: list[str] = []
    remaining = set(by_title)

    while remaining:
        ready = [title for title in remaining if not needs[title]]

        if not ready:
            stuck = min(remaining, key=sort_key)
            for need in sorted(needs[stuck]):
                log_lines.append(
                    f"Cycle detected: removed '{stuck}' needing '{need}' to break the "
                    f"loop; '{stuck}' (level {by_title[stuck].get('level', 1)}) placed "
                    f"without waiting on it."
                )
                dependents[need].discard(stuck)
            needs[stuck] = set()
            ready = [stuck]

        next_title = min(ready, key=sort_key)
        ordered_titles.append(next_title)
        remaining.discard(next_title)
        for dependent in dependents[next_title]:
            needs[dependent].discard(next_title)

    ordered_topics = [
        dict(by_title[title], order=index) for index, title in enumerate(ordered_titles, start=1)
    ]
    return ordered_topics, log_lines


def run_order_topics(output_dir: str | Path) -> list[dict]:
    """Load plan.json, order it, and write ordered_plan.json + order_log.txt."""
    output_dir = Path(output_dir)
    plan = json.loads(plan_json_path(output_dir).read_text(encoding="utf-8"))

    video_order: dict[str, int] = {}
    videos_json_path = output_dir / "videos.json"
    if videos_json_path.exists():
        videos = json.loads(videos_json_path.read_text(encoding="utf-8"))
        video_order = {
            video["video_id"]: video.get("playlist_index", index)
            for index, video in enumerate(videos, start=1)
        }

    ordered, log_lines = order_topics(plan, video_order)

    if log_lines:
        with order_log_path(output_dir).open("a", encoding="utf-8") as log_file:
            for line in log_lines:
                log_file.write(line + "\n")

    ordered_plan_path(output_dir).write_text(
        json.dumps(ordered, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return ordered
