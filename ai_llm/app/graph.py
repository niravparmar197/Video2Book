"""Book graph: fetch -> chunk -> topics -> [plan] -> write -> render -> compile.

LangGraph + SqliteSaver checkpoints the run so --resume (app/cli.py) can
continue after a crash. Independently of that, each expensive (LLM-calling)
step also checks app/cache.py before running, so a plain re-run of the same
playlist never re-calls the LLM for a chunk whose topics/notes already exist
on disk. See root AGENTS.md workflow phases A-E.

The understand phase (fetch/chunk/topics) loops over every video in the
playlist and is shared by both BOOK_ORDER modes (sprints/v2/v3 PRD.md).
`load_settings().book_order` then picks which graph gets built:

- `video` (v2): write -> outline -> render. One chapter per video, in
  playlist order.
- `topic` (v3): plan -> order -> outline -> write -> render. A new LLM call
  (plan.py) merges repeated topics across the whole playlist; order.py
  topologically sorts them by needs/level; outline.py's topic variant
  builds `chapter:<topic-slug>` chapters; write.py's topic variant
  synthesizes ONE section per merged topic from every source video that
  covers it.

Both converge on the same render step: every non-skipped chapter (a manual
`skip: true` edit in outline.json always wins) is rendered and \\input into
one main.tex with a table of contents (render_book, main.tex.j2) and
compiled to book.pdf.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from app.cache import run_cached
from app.config import load_settings
from app.latex.tex import (
    compile_chapter,
    render_book,
    render_book_volumes,
    render_chapter,
    render_topic_index,
    split_into_volumes,
)
from app.nodes.book_pass import (
    glossary_json_path,
    index_terms_json_path,
    preface_path as preface_file_path_for,
    run_glossary,
    run_index_terms,
    run_preface,
)
from app.nodes.chunk import run_chunk
from app.nodes.fetch import run_fetch_playlist
from app.nodes.frames import load_screenshots_for_sources, load_video_screenshots, run_frames
from app.nodes.order import run_order_topics
from app.nodes.outline import run_outline, run_topic_outline
from app.nodes.plan import run_plan_topics
from app.nodes.topics import run_topics, topics_output_path
from app.nodes.write import notes_output_path, run_write, run_write_topic


class VideoRef(TypedDict):
    video_id: str
    title: str
    url: str
    captions_path: str
    duration_seconds: int


class BookState(TypedDict, total=False):
    url: str
    output_dir: str
    force: bool
    videos: list[VideoRef]
    chunk_paths: dict[str, list[str]]
    notes_paths: dict[str, str]
    ordered_topics: list[dict]
    chapters: list[dict]
    book_pass: dict
    tex_path: str
    pdf_path: str


def _fetch_node(state: BookState) -> dict:
    videos = run_fetch_playlist(state["url"], state["output_dir"])
    return {
        "videos": [
            {
                "video_id": video.video_id,
                "title": video.title,
                "url": video.url,
                "captions_path": video.captions_path,
                "duration_seconds": video.duration_seconds,
            }
            for video in videos
        ]
    }


class BudgetExceededError(RuntimeError):
    """Raised when a playlist's total duration or estimated cost exceeds
    the configured budget (MAX_BOOK_HOURS / MAX_BOOK_COST_USD, sprints/v7
    PRD.md) and --force wasn't passed.
    """


def _estimate_total_cost_usd(videos: list[dict]) -> float:
    """Rough total cost across all videos -- always $0.00 today since both
    providers (NVIDIA, Gemini) are free tiers, per root AGENTS.md. Kept as
    its own function so a future paid-tier cost model has one place to
    plug in, and so the MAX_BOOK_COST_USD gate is testable without a real
    paid provider (tests monkeypatch this function directly).
    """
    return 0.0


def _check_budget_node(state: BookState) -> dict:
    """Refuse to proceed past fetch if the playlist is over budget, unless
    --force was passed. Runs right after fetch so it can use each video's
    real duration_seconds (no extra network round-trip beyond the fetch
    that was going to happen anyway).
    """
    if state.get("force"):
        return {}

    settings = load_settings()
    total_hours = sum(video["duration_seconds"] for video in state["videos"]) / 3600
    if total_hours > settings.max_book_hours:
        raise BudgetExceededError(
            f"playlist total duration ({total_hours:.2f}h) exceeds MAX_BOOK_HOURS "
            f"({settings.max_book_hours}h) -- pass --force to proceed anyway"
        )

    total_cost_usd = _estimate_total_cost_usd(state["videos"])
    if total_cost_usd > settings.max_book_cost_usd:
        raise BudgetExceededError(
            f"playlist estimated cost (${total_cost_usd:.2f}) exceeds MAX_BOOK_COST_USD "
            f"(${settings.max_book_cost_usd:.2f}) -- pass --force to proceed anyway"
        )

    return {}


def _chunk_node(state: BookState) -> dict:
    chunk_paths: dict[str, list[str]] = {}
    for video in state["videos"]:
        paths = run_chunk(video["video_id"], video["captions_path"], state["output_dir"])
        chunk_paths[video["video_id"]] = [str(path) for path in paths]
    return {"chunk_paths": chunk_paths}


def _frames_node(state: BookState) -> dict:
    """Screenshots per chunk (sprints/v4 PRD.md). Skipped entirely when
    VIDEO_MODE=captions_only. run_frames() is self-cache-skippable, so no
    run_cached() wrapper is needed here.
    """
    if load_settings().video_mode == "captions_only":
        return {}

    videos_by_id = {video["video_id"]: video for video in state["videos"]}
    for video_id, chunk_paths in state["chunk_paths"].items():
        video_url = videos_by_id[video_id]["url"]
        for chunk_path in chunk_paths:
            chunk = json.loads(Path(chunk_path).read_text(encoding="utf-8"))
            run_frames(video_id, video_url, chunk, state["output_dir"])
    return {}


def _topics_node(state: BookState) -> dict:
    for video_chunk_paths in state["chunk_paths"].values():
        for chunk_path in video_chunk_paths:
            chunk = json.loads(Path(chunk_path).read_text(encoding="utf-8"))
            output_path = topics_output_path(chunk, state["output_dir"])
            run_cached(output_path, lambda cp=chunk_path: run_topics(cp, state["output_dir"]))
    return {}


def _write_node(state: BookState) -> dict:
    notes_paths: dict[str, str] = {}
    for video in state["videos"]:
        video_id = video["video_id"]
        output_path = notes_output_path(video_id, state["output_dir"])
        run_cached(output_path, lambda vid=video_id: run_write(vid, state["output_dir"]))
        notes_paths[video_id] = str(output_path)
    return {"notes_paths": notes_paths}


def _outline_node(state: BookState) -> dict:
    chapters = run_outline(state["videos"], state["output_dir"])
    return {"chapters": chapters}


def _run_book_pass(chapters: list[dict], output_dir: str) -> dict:
    """Shared book_pass orchestration (sprints/v6 PRD.md): subject-index
    terms per chapter, a merged glossary, and a preface -- all grounded in
    the chapters' own final notes. `chapters` is a mode-agnostic list of
    {file_key, title, notes_path} (non-skipped chapters only). Each
    underlying LLM call is cache-skipped via run_cached, matching every
    other step's crash-safety rule.
    """
    output_dir_path = Path(output_dir)
    chapters_with_notes = []
    index_terms_by_file_key: dict[str, list[str]] = {}

    for chapter in chapters:
        notes = Path(chapter["notes_path"]).read_text(encoding="utf-8")
        chapters_with_notes.append({"title": chapter["title"], "notes": notes})

        terms_path = index_terms_json_path(chapter["file_key"], output_dir)
        run_cached(
            terms_path,
            lambda file_key=chapter["file_key"], n=notes: run_index_terms(file_key, n, output_dir),
        )
        index_terms_by_file_key[chapter["file_key"]] = json.loads(
            terms_path.read_text(encoding="utf-8")
        )

    glossary_path = glossary_json_path(output_dir)
    run_cached(glossary_path, lambda: run_glossary(chapters_with_notes, output_dir))
    glossary = json.loads(glossary_path.read_text(encoding="utf-8"))

    preface_file_path = preface_file_path_for(output_dir)
    run_cached(
        preface_file_path,
        lambda: run_preface([{"title": chapter["title"]} for chapter in chapters], output_dir),
    )

    return {
        "glossary": glossary,
        "preface_path": str(preface_file_path),
        "index_terms_by_file_key": index_terms_by_file_key,
    }


def _render_chapters(
    chapters: list[dict],
    output_dir: str,
    preface_path: str | None = None,
    glossary_entries: list[dict] | None = None,
    topic_index_chapters: list[dict] | None = None,
) -> tuple[str, str]:
    """Render + compile a mode-agnostic chapter list into book.pdf (or
    book_vol<N>.pdf when the playlist crosses VOLUME_HOURS, sprints/v6
    PRD.md).

    Each chapter is {file_key, title, notes_path, screenshots, hours,
    index_terms}: file_key names the chapters/<file_key>.tex fragment
    (video_id in video mode, topic slug in topic mode); screenshots
    (sprints/v4 PRD.md) is that chapter's deduped frames, appended as
    figures; hours is that chapter's approximate source-video duration,
    used only to decide the volume split; index_terms (sprints/v6 PRD.md)
    are marked with \\index{} at their first occurrence. `preface_path`/
    `glossary_entries`/`topic_index_chapters` (sprints/v6 PRD.md), if
    given, assemble the book's front/back matter -- omitted entirely (as
    they are when `book_pass` never ran, e.g. before Task 8 wired it in)
    reproduces the exact pre-v6 chapters-only book. Everything downstream
    of this point (render_chapter, render_book, compile_chapter) doesn't
    need to know which mode built the list. Shared by both BOOK_ORDER
    modes' render nodes.
    """
    file_keys: list[str] = []
    for chapter in chapters:
        notes = Path(chapter["notes_path"]).read_text(encoding="utf-8")
        render_chapter(
            chapter["file_key"],
            chapter["title"],
            notes,
            output_dir,
            chapter.get("screenshots"),
            chapter.get("index_terms"),
        )
        file_keys.append(chapter["file_key"])

    include_topic_index = topic_index_chapters is not None
    if include_topic_index:
        render_topic_index(topic_index_chapters, output_dir)

    total_hours = sum(chapter.get("hours", 0.0) for chapter in chapters)
    volume_hours = load_settings().volume_hours

    if total_hours <= volume_hours:
        main_tex_path = render_book(
            file_keys,
            output_dir,
            preface_path=preface_path,
            glossary_entries=glossary_entries,
            include_topic_index=include_topic_index,
        )
        pdf_path = compile_chapter(main_tex_path)
        book_pdf_path = Path(output_dir) / "book.pdf"
        shutil.copyfile(pdf_path, book_pdf_path)
        return str(main_tex_path), str(book_pdf_path)

    chapters_with_hours = [
        (chapter["file_key"], chapter.get("hours", 0.0)) for chapter in chapters
    ]
    chapter_groups = split_into_volumes(chapters_with_hours, volume_hours)
    volume_tex_paths = render_book_volumes(
        chapter_groups,
        output_dir,
        preface_path=preface_path,
        glossary_entries=glossary_entries,
        include_topic_index=include_topic_index,
    )

    last_pdf_path = None
    for volume_index, main_tex_path in enumerate(volume_tex_paths, start=1):
        pdf_path = compile_chapter(main_tex_path)
        volume_pdf_path = Path(output_dir) / f"book_vol{volume_index}.pdf"
        shutil.copyfile(pdf_path, volume_pdf_path)
        last_pdf_path = volume_pdf_path

    return str(volume_tex_paths[-1]), str(last_pdf_path)


def _book_pass_node(state: BookState) -> dict:
    videos_by_id = {video["video_id"]: video for video in state["videos"]}
    chapters = [
        {
            "file_key": chapter["video_id"],
            "title": videos_by_id[chapter["video_id"]]["title"],
            "notes_path": state["notes_paths"][chapter["video_id"]],
        }
        for chapter in state["chapters"]
        if not chapter["skip"]
    ]
    return {"book_pass": _run_book_pass(chapters, state["output_dir"])}


def _render_node(state: BookState) -> dict:
    videos_by_id = {video["video_id"]: video for video in state["videos"]}
    book_pass = state.get("book_pass", {})
    index_terms_by_file_key = book_pass.get("index_terms_by_file_key", {})

    chapters = [
        {
            "file_key": chapter["video_id"],
            "title": videos_by_id[chapter["video_id"]]["title"],
            "notes_path": state["notes_paths"][chapter["video_id"]],
            "screenshots": load_video_screenshots(chapter["video_id"], state["output_dir"]),
            "hours": videos_by_id[chapter["video_id"]]["duration_seconds"] / 3600,
            "index_terms": index_terms_by_file_key.get(chapter["video_id"], []),
        }
        for chapter in state["chapters"]
        if not chapter["skip"]
    ]
    tex_path, pdf_path = _render_chapters(
        chapters,
        state["output_dir"],
        preface_path=book_pass.get("preface_path"),
        glossary_entries=book_pass.get("glossary"),
        topic_index_chapters=(
            [{"title": chapter["title"]} for chapter in chapters] if book_pass else None
        ),
    )
    return {"tex_path": tex_path, "pdf_path": pdf_path}


# --- BOOK_ORDER=topic nodes (v3) ---------------------------------------


def _plan_node(state: BookState) -> dict:
    run_plan_topics(state["output_dir"])
    return {}


def _order_node(state: BookState) -> dict:
    ordered = run_order_topics(state["output_dir"])
    return {"ordered_topics": ordered}


def _topic_outline_node(state: BookState) -> dict:
    chapters = run_topic_outline(state["ordered_topics"], state["output_dir"])
    return {"chapters": chapters}


def _write_topic_node(state: BookState) -> dict:
    notes_paths: dict[str, str] = {}
    for chapter in state["chapters"]:
        output_path = notes_output_path(f"topic_{chapter['slug']}", state["output_dir"])
        run_cached(output_path, lambda ch=chapter: run_write_topic(ch, state["output_dir"]))
        notes_paths[chapter["id"]] = str(output_path)
    return {"notes_paths": notes_paths}


def _book_pass_topic_node(state: BookState) -> dict:
    chapters = [
        {
            "file_key": chapter["slug"],
            "title": chapter["title"],
            "notes_path": state["notes_paths"][chapter["id"]],
        }
        for chapter in state["chapters"]
        if not chapter["skip"]
    ]
    return {"book_pass": _run_book_pass(chapters, state["output_dir"])}


def _render_topic_node(state: BookState) -> dict:
    chunk_minutes = load_settings().chunk_minutes
    book_pass = state.get("book_pass", {})
    index_terms_by_file_key = book_pass.get("index_terms_by_file_key", {})

    chapters = [
        {
            "file_key": chapter["slug"],
            "title": chapter["title"],
            "notes_path": state["notes_paths"][chapter["id"]],
            "screenshots": load_screenshots_for_sources(
                chapter.get("sources", []), state["output_dir"]
            ),
            # No single source video's duration applies to a merged topic;
            # approximate from its source chunk count (each ~chunk_minutes
            # long) -- good enough to size the volume split, not exact.
            "hours": len(chapter.get("sources", [])) * chunk_minutes / 60,
            "index_terms": index_terms_by_file_key.get(chapter["slug"], []),
        }
        for chapter in state["chapters"]
        if not chapter["skip"]
    ]
    tex_path, pdf_path = _render_chapters(
        chapters,
        state["output_dir"],
        preface_path=book_pass.get("preface_path"),
        glossary_entries=book_pass.get("glossary"),
        topic_index_chapters=(
            [{"title": chapter["title"]} for chapter in chapters] if book_pass else None
        ),
    )
    return {"tex_path": tex_path, "pdf_path": pdf_path}


def build_video_graph(checkpointer=None):
    """BOOK_ORDER=video (v2): fetch->chunk->topics->write->outline->book_pass->render->END."""
    builder = StateGraph(BookState)
    builder.add_node("fetch", _fetch_node)
    builder.add_node("check_budget", _check_budget_node)
    builder.add_node("chunk", _chunk_node)
    builder.add_node("frames", _frames_node)
    builder.add_node("topics", _topics_node)
    builder.add_node("write", _write_node)
    builder.add_node("outline", _outline_node)
    builder.add_node("book_pass", _book_pass_node)
    builder.add_node("render", _render_node)

    builder.add_edge(START, "fetch")
    builder.add_edge("fetch", "check_budget")
    builder.add_edge("check_budget", "chunk")
    builder.add_edge("chunk", "frames")
    builder.add_edge("frames", "topics")
    builder.add_edge("topics", "write")
    builder.add_edge("write", "outline")
    builder.add_edge("outline", "book_pass")
    builder.add_edge("book_pass", "render")
    builder.add_edge("render", END)

    return builder.compile(checkpointer=checkpointer)


def build_video_plan_graph(checkpointer=None):
    """BOOK_ORDER=video, --plan-only: stops before render/compile.

    Used by run_plan() (--plan-only): the operator reviews outline.md, edits
    outline.json's skip/locked flags, then re-runs the plain command, which
    builds the full graph instead — outline.py preserves the edits
    (sprints/v2 Task 4), and fetch/chunk/topics/write are unaffected or
    cache-skipped, so the run continues on to render/compile.
    """
    builder = StateGraph(BookState)
    builder.add_node("fetch", _fetch_node)
    builder.add_node("check_budget", _check_budget_node)
    builder.add_node("chunk", _chunk_node)
    builder.add_node("topics", _topics_node)
    builder.add_node("write", _write_node)
    builder.add_node("outline", _outline_node)

    builder.add_edge(START, "fetch")
    builder.add_edge("fetch", "check_budget")
    builder.add_edge("check_budget", "chunk")
    builder.add_edge("chunk", "topics")
    builder.add_edge("topics", "write")
    builder.add_edge("write", "outline")
    builder.add_edge("outline", END)

    return builder.compile(checkpointer=checkpointer)


def build_topic_graph(checkpointer=None):
    """BOOK_ORDER=topic (v3): fetch->check_budget->chunk->topics->plan->order->outline->write->book_pass->render->END."""
    builder = StateGraph(BookState)
    builder.add_node("fetch", _fetch_node)
    builder.add_node("check_budget", _check_budget_node)
    builder.add_node("chunk", _chunk_node)
    builder.add_node("frames", _frames_node)
    builder.add_node("topics", _topics_node)
    builder.add_node("plan", _plan_node)
    builder.add_node("order", _order_node)
    builder.add_node("outline", _topic_outline_node)
    builder.add_node("write", _write_topic_node)
    builder.add_node("book_pass", _book_pass_topic_node)
    builder.add_node("render", _render_topic_node)

    builder.add_edge(START, "fetch")
    builder.add_edge("fetch", "check_budget")
    builder.add_edge("check_budget", "chunk")
    builder.add_edge("chunk", "frames")
    builder.add_edge("frames", "topics")
    builder.add_edge("topics", "plan")
    builder.add_edge("plan", "order")
    builder.add_edge("order", "outline")
    builder.add_edge("outline", "write")
    builder.add_edge("write", "book_pass")
    builder.add_edge("book_pass", "render")
    builder.add_edge("render", END)

    return builder.compile(checkpointer=checkpointer)


def build_topic_plan_graph(checkpointer=None):
    """BOOK_ORDER=topic, --plan-only: stops before write/render/compile."""
    builder = StateGraph(BookState)
    builder.add_node("fetch", _fetch_node)
    builder.add_node("check_budget", _check_budget_node)
    builder.add_node("chunk", _chunk_node)
    builder.add_node("topics", _topics_node)
    builder.add_node("plan", _plan_node)
    builder.add_node("order", _order_node)
    builder.add_node("outline", _topic_outline_node)

    builder.add_edge(START, "fetch")
    builder.add_edge("fetch", "check_budget")
    builder.add_edge("check_budget", "chunk")
    builder.add_edge("chunk", "topics")
    builder.add_edge("topics", "plan")
    builder.add_edge("plan", "order")
    builder.add_edge("order", "outline")
    builder.add_edge("outline", END)

    return builder.compile(checkpointer=checkpointer)


_VIDEO_NODE_ORDER = [
    "fetch", "check_budget", "chunk", "frames", "topics", "write", "outline", "book_pass", "render",
]
_VIDEO_PLAN_NODE_ORDER = ["fetch", "check_budget", "chunk", "topics", "write", "outline"]
_TOPIC_NODE_ORDER = [
    "fetch", "check_budget", "chunk", "frames", "topics", "plan", "order", "outline", "write",
    "book_pass", "render",
]
_TOPIC_PLAN_NODE_ORDER = ["fetch", "check_budget", "chunk", "topics", "plan", "order", "outline"]


def _node_order_for(book_order: str, phase: str) -> list[str]:
    if book_order == "topic":
        return _TOPIC_PLAN_NODE_ORDER if phase == "plan" else _TOPIC_NODE_ORDER
    return _VIDEO_PLAN_NODE_ORDER if phase == "plan" else _VIDEO_NODE_ORDER


def get_progress(output_dir: str | Path, checkpointer, book_order: str | None = None, phase: str = "render") -> dict:
    """Read-only: reports where a book's LangGraph run currently stands,
    without invoking anything (sprints/v7 Task 4). Node names/ordering
    knowledge stays here, next to where the graphs themselves are defined --
    callers (e.g. backend/'s `/events` endpoint) never hardcode a node list.

    `phase`: "plan" inspects the --plan-only graph variant (matches
    `run_plan`'s node set, which skips `frames`/`write` down to `render`);
    anything else inspects the full graph variant (matches `run_book`/
    `resume_book`). This must match which of `run_plan`/`run_book` actually
    produced the checkpoint being read, the same way backend/'s
    `process_run_book` already tracks a book's current phase.

    Returns `{"completed_nodes": [...], "current_node": str | None,
    "next_nodes": [...], "step": int}`. A `thread_id` with no checkpoint yet
    (book not started) returns all-empty/zero rather than raising.
    """
    output_dir = Path(output_dir)
    book_order = book_order or load_settings().book_order
    node_order = _node_order_for(book_order, phase)

    if phase == "plan":
        graph = build_plan_graph(checkpointer=checkpointer, book_order=book_order)
    else:
        graph = build_graph(checkpointer=checkpointer, book_order=book_order)

    config = {"configurable": {"thread_id": str(output_dir)}}
    snapshot = graph.get_state(config)

    # Never run, or only LangGraph's internal START pseudo-node is pending
    # (the transient checkpoint it writes the instant graph.invoke() begins,
    # before any real node has executed) -- both report as "not started".
    if snapshot.created_at is None or list(snapshot.next) == [START]:
        return {"completed_nodes": [], "current_node": None, "next_nodes": [], "step": 0}

    next_nodes = list(snapshot.next)
    current_node = next_nodes[0] if next_nodes else None
    if current_node in node_order:
        completed_nodes = node_order[: node_order.index(current_node)]
    else:
        # next == () -- the graph ran to completion; every node in this
        # phase's order is done.
        completed_nodes = list(node_order)

    step = snapshot.metadata.get("step", 0) if snapshot.metadata else 0

    return {
        "completed_nodes": completed_nodes,
        "current_node": current_node,
        "next_nodes": next_nodes,
        "step": step,
    }


def build_graph(checkpointer=None, book_order: str | None = None):
    """Dispatch to the video- or topic-order graph based on BOOK_ORDER."""
    book_order = book_order or load_settings().book_order
    if book_order == "topic":
        return build_topic_graph(checkpointer=checkpointer)
    return build_video_graph(checkpointer=checkpointer)


def build_plan_graph(checkpointer=None, book_order: str | None = None):
    """Dispatch to the video- or topic-order --plan-only graph."""
    book_order = book_order or load_settings().book_order
    if book_order == "topic":
        return build_topic_plan_graph(checkpointer=checkpointer)
    return build_video_plan_graph(checkpointer=checkpointer)


def _checkpoint_db_path(output_dir: Path) -> Path:
    return output_dir / "graph_state.sqlite"


def run_book(
    url: str, output_dir: str | Path, force: bool = False, checkpointer=None
) -> Path:
    """Run the full fetch->chunk->topics->write->render pipeline for one video.

    `force` bypasses the MAX_BOOK_HOURS/MAX_BOOK_COST_USD budget gate
    (check_budget node, sprints/v7 Task 2/3) -- the CLI's --force flag.

    `checkpointer` (sprints/v7 Task 3): omit it (every existing caller --
    the CLI, every pre-v7 test) to get today's exact behavior, a SqliteSaver
    scoped to this call and closed afterward. Pass one (e.g. backend/'s
    shared Postgres-backed checkpointer) to use it as-is instead -- its
    lifecycle is then the caller's responsibility, not closed here.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if checkpointer is not None:
        graph = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": str(output_dir)}}
        final_state = graph.invoke(
            {"url": url, "output_dir": str(output_dir), "force": force}, config=config
        )
        return Path(final_state["pdf_path"])

    with SqliteSaver.from_conn_string(str(_checkpoint_db_path(output_dir))) as sqlite_checkpointer:
        graph = build_graph(checkpointer=sqlite_checkpointer)
        config = {"configurable": {"thread_id": str(output_dir)}}
        final_state = graph.invoke(
            {"url": url, "output_dir": str(output_dir), "force": force}, config=config
        )

    return Path(final_state["pdf_path"])


def run_plan(
    url: str, output_dir: str | Path, force: bool = False, checkpointer=None
) -> tuple[list[dict], list[dict]]:
    """Run fetch->chunk->topics->write->outline only (--plan-only).

    Stops before any render/compile step. Shares the same checkpoint db and
    thread_id as run_book/resume_book so the completed steps are not redone
    when the operator re-runs the plain command afterward. `force` bypasses
    the budget gate same as run_book.

    Returns `(videos, chapters)` -- callers that only need the chapter plan
    (e.g. the CLI's --plan-only) can ignore the first element; a caller that
    also needs to know which source videos were fetched (e.g. backend/'s
    outline-review sprint, which persists a Video row per source) doesn't
    have to re-derive that from chapters' `sources`.

    `checkpointer` (sprints/v7 Task 3): same optional-injection contract as
    run_book.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if checkpointer is not None:
        graph = build_plan_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": str(output_dir)}}
        final_state = graph.invoke(
            {"url": url, "output_dir": str(output_dir), "force": force}, config=config
        )
        return final_state["videos"], final_state["chapters"]

    with SqliteSaver.from_conn_string(str(_checkpoint_db_path(output_dir))) as sqlite_checkpointer:
        graph = build_plan_graph(checkpointer=sqlite_checkpointer)
        config = {"configurable": {"thread_id": str(output_dir)}}
        final_state = graph.invoke(
            {"url": url, "output_dir": str(output_dir), "force": force}, config=config
        )

    return final_state["videos"], final_state["chapters"]


def resume_book(output_dir: str | Path, checkpointer=None) -> Path:
    """Resume a previously interrupted run from its checkpoint.

    `checkpointer` (sprints/v7 Task 3): omit it to resume from the default
    SqliteSaver file under `output_dir` (today's exact behavior -- raises
    `FileNotFoundError` if that file doesn't exist). Pass the same
    caller-supplied checkpointer the interrupted `run_book`/`run_plan` call
    used to resume from it instead.
    """
    output_dir = Path(output_dir)

    if checkpointer is not None:
        graph = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": str(output_dir)}}
        final_state = graph.invoke(None, config=config)
        return Path(final_state["pdf_path"])

    db_path = _checkpoint_db_path(output_dir)
    if not db_path.exists():
        raise FileNotFoundError(f"no checkpoint database found at {db_path}")

    with SqliteSaver.from_conn_string(str(db_path)) as sqlite_checkpointer:
        graph = build_graph(checkpointer=sqlite_checkpointer)
        config = {"configurable": {"thread_id": str(output_dir)}}
        final_state = graph.invoke(None, config=config)

    return Path(final_state["pdf_path"])
