"""Outline node: the book plan (outline.json + outline.md), both BOOK_ORDER modes.

`run_outline` (BOOK_ORDER=video, v2): chapters stay in playlist order, one
chapter per video. `run_topic_outline` (BOOK_ORDER=topic, v3): chapters are
merged topics (app.nodes.plan + app.nodes.order), already sorted by
needs/level. Both build stable ids (`chapter:<video_id>` /
`chapter:<topic-slug>`) so re-running never breaks a manual edit's identity
(root AGENTS.md: "reordering never breaks cross-references"), and both
preserve any existing skip/locked flags via the same `_preserve_flags`
helper, so a manual review edit is never clobbered by re-running this node
(e.g. on --resume after --plan-only). Review flow: --plan-only stops after
this node writes outline.json/outline.md; a human edits outline.json's
skip/locked flags, then the run continues. Manual edits always win over the
auto-generated defaults on every re-run.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def outline_json_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "outline.json"


def outline_md_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "outline.md"


def _load_existing_chapters(output_dir: Path) -> dict[str, dict]:
    path = outline_json_path(output_dir)
    if not path.exists():
        return {}
    existing = json.loads(path.read_text(encoding="utf-8"))
    return {chapter["id"]: chapter for chapter in existing}


def _preserve_flags(existing: dict[str, dict], chapter_id: str) -> tuple[bool, bool]:
    prior = existing.get(chapter_id, {})
    return prior.get("skip", False), prior.get("locked", False)


def run_outline(videos: list[dict], output_dir: str | Path) -> list[dict]:
    """Build/update the video-order chapter plan and write outline.json/md.

    `videos` is the playlist's video list in playlist order (each a dict
    with at least video_id/title, e.g. from videos.json).
    """
    output_dir = Path(output_dir)
    existing = _load_existing_chapters(output_dir)

    chapters = []
    for index, video in enumerate(videos, start=1):
        chapter_id = f"chapter:{video['video_id']}"
        skip, locked = _preserve_flags(existing, chapter_id)
        chapters.append(
            {
                "id": chapter_id,
                "video_id": video["video_id"],
                "title": video["title"],
                "order": index,
                "skip": skip,
                "locked": locked,
                "detail": video["video_id"],
            }
        )

    _write_outline_json(output_dir, chapters)
    _write_outline_md(output_dir, chapters)
    return chapters


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "topic"


def _unique_slug(title: str, used_slugs: set[str]) -> str:
    base = _slugify(title)
    slug = base
    suffix = 2
    while slug in used_slugs:
        slug = f"{base}-{suffix}"
        suffix += 1
    used_slugs.add(slug)
    return slug


def run_topic_outline(ordered_topics: list[dict], output_dir: str | Path) -> list[dict]:
    """Build/update the topic-order chapter plan (BOOK_ORDER=topic).

    `ordered_topics` is app.nodes.order.order_topics's output: merged
    topics already sorted by needs/level. Chapter ids are slugified from
    each topic's title, deduped on collision.
    """
    output_dir = Path(output_dir)
    existing = _load_existing_chapters(output_dir)

    used_slugs: set[str] = set()
    chapters = []
    for index, topic in enumerate(ordered_topics, start=1):
        slug = _unique_slug(topic["title"], used_slugs)
        chapter_id = f"chapter:{slug}"
        skip, locked = _preserve_flags(existing, chapter_id)
        video_ids = sorted({source["video_id"] for source in topic.get("sources", [])})
        chapters.append(
            {
                "id": chapter_id,
                "slug": slug,
                "title": topic["title"],
                "order": index,
                "skip": skip,
                "locked": locked,
                "level": topic.get("level", 1),
                "needs": topic.get("needs", []),
                "sources": topic.get("sources", []),
                "covers": topic.get("covers", []),
                "detail": f"level {topic.get('level', 1)}; sources: {', '.join(video_ids) or 'none'}",
            }
        )

    _write_outline_json(output_dir, chapters)
    _write_outline_md(output_dir, chapters)
    return chapters


def _write_outline_json(output_dir: Path, chapters: list[dict]) -> None:
    outline_json_path(output_dir).write_text(
        json.dumps(chapters, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _write_outline_md(output_dir: Path, chapters: list[dict]) -> None:
    lines = ["# Book Outline", ""]
    for chapter in chapters:
        tags = []
        if chapter["skip"]:
            tags.append("[skip]")
        if chapter["locked"]:
            tags.append("[locked]")
        tag_suffix = f" {' '.join(tags)}" if tags else ""
        lines.append(f"{chapter['order']}. {chapter['title']} ({chapter['detail']}){tag_suffix}")
    lines.append("")
    outline_md_path(output_dir).write_text("\n".join(lines), encoding="utf-8")
