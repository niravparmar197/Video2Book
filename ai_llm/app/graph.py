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

import contextvars
import functools
import json
import logging
import shutil
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, TypedDict, TypeVar

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from app.cache import run_cached
from app.config import load_settings
from app.export import write_epub, write_markdown_book
from app.latex.tex import (
    compile_chapter,
    render_book,
    render_book_volumes,
    render_chapter,
    split_into_volumes,
)
from app.nodes.align import chapter_section_times
from app.nodes.book_pass import (
    glossary_json_path,
    index_terms_json_path,
    run_glossary,
    run_index_terms,
)
from app.nodes.chunk import run_chunk
from app.nodes.fetch import run_fetch_playlist
from app.nodes.frames import load_screenshots_for_sources, load_video_screenshots, run_frames
from app.nodes.genre import BOOK_KINDS, genre_json_path, load_genre, run_genre
from app.nodes.order import run_order_topics
from app.nodes.outline import outline_json_path, run_outline, run_topic_outline
from app.nodes.plan import plan_json_path, run_plan_topics, run_single_chunk_plan
from app.nodes.topics import (
    run_topics,
    topics_from_youtube_chapters,
    topics_output_path,
    write_topics,
)
from app.nodes.write import chapter_status_path, notes_output_path, run_write, run_write_topic


class VideoRef(TypedDict):
    video_id: str
    title: str
    url: str
    captions_path: str
    duration_seconds: int
    channel: str
    chapters: list[dict]


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


_timings_lock = threading.Lock()


def timings_path(output_dir: str | Path) -> Path:
    """Where each graph node's wall-clock seconds are recorded, so a slow run
    shows exactly which step to optimize instead of guessing."""
    return Path(output_dir) / "timings.json"


def get_timings(output_dir: str | Path) -> dict[str, float]:
    """Read-only: seconds spent per node so far ({} before any node ran)."""
    path = timings_path(output_dir)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _record_timing(output_dir: str | Path, node: str, seconds: float) -> None:
    # `frames` and `topics` run in parallel, hence the lock around the
    # read-modify-write of the shared file.
    with _timings_lock:
        timings = get_timings(output_dir)
        timings[node] = round(seconds, 1)
        timings_path(output_dir).write_text(json.dumps(timings, indent=2), encoding="utf-8")


def _timed(name: str, node_fn: Callable[[BookState], dict]) -> Callable[[BookState], dict]:
    @functools.wraps(node_fn)
    def wrapper(state: BookState) -> dict:
        start = time.monotonic()
        try:
            return node_fn(state)
        finally:
            _record_timing(state["output_dir"], name, time.monotonic() - start)

    return wrapper


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
                "channel": video.channel,
                "chapters": list(video.chapters),
            }
            for video in videos
        ]
    }


# Independent per-chunk/per-chapter LLM calls (topics, write, index_terms)
# ran strictly one after another before this -- verified against a real run:
# a single 5-minute video's write+book_pass phase alone took ~8 minutes
# because 4 independent chapters were written sequentially, and that cost
# scales linearly (not sub-linearly) with a 30-hour playlist's ~60 chunks.
# Bounded rather than unbounded so a huge playlist doesn't spawn hundreds of
# threads at once; NVIDIA's 40 RPM cap (app/llm.py's _pace, thread-safe) is
# what actually limits throughput. The LLM bound is LLM_PARALLEL_CALLS
# (default 12; measured: 8 real writer calls in parallel finished in 63s vs
# 42s for one, so an 8-hour video's ~40 chapters take minutes, not the ~20
# minutes 4-at-a-time did). ffmpeg scans are CPU work, so they stay at 4.
_MAX_PARALLEL_FRAME_SCANS = 4

_T = TypeVar("_T")
_R = TypeVar("_R")


def _map_parallel(
    items: list[_T], fn: Callable[[_T], _R], max_workers: int | None = None
) -> list[_R]:
    """Run fn(item) for each item on a bounded thread pool, returning
    results in the same order as `items`.

    Every submitted item is allowed to finish -- success or failure --
    before any exception is raised; only then does the first one raise
    (deterministically, by input order). This preserves each sequential
    loop's original crash-safety guarantee (root AGENTS.md: "every step
    saves to disk") now that items run concurrently: a real regression
    caught this -- ThreadPoolExecutor.map() raises a failing item's
    exception as soon as it's reached, which could happen before a sibling
    item running in the same batch had finished writing its own output to
    disk, losing work that should have survived for --resume to skip.
    """
    if not items:
        return []
    max_workers = max(1, max_workers or load_settings().llm_parallel_calls)
    with ThreadPoolExecutor(max_workers=min(len(items), max_workers)) as pool:
        # Each task runs in a copy of the caller's context, so per-run
        # context (which book's warnings file to write to) follows the work
        # onto pool threads -- plain submit() would drop it.
        futures = [pool.submit(contextvars.copy_context().run, fn, item) for item in items]
        results: list[_R] = []
        first_exception: Exception | None = None
        for future in futures:
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - re-raised below, not swallowed
                if first_exception is None:
                    first_exception = exc
        if first_exception is not None:
            raise first_exception
        return results


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

    Each chunk's ffmpeg scene scan ran strictly one after another before
    this -- unlike topics/write, which were already parallelized
    (_map_parallel) -- so a playlist's total frames time scaled linearly
    with its chunk count even though each chunk's scan is independent I/O
    (network stream read + local ffmpeg), not an LLM call bound by a
    shared rate limit. Bounded by _MAX_PARALLEL_FRAME_SCANS so
    a huge playlist doesn't spawn hundreds of ffmpeg processes at once.
    """
    if load_settings().video_mode == "captions_only":
        return {}

    videos_by_id = {video["video_id"]: video for video in state["videos"]}
    chunk_items = [
        (video_id, chunk_path)
        for video_id, chunk_paths in state["chunk_paths"].items()
        for chunk_path in chunk_paths
    ]

    def process(item: tuple[str, str]) -> None:
        video_id, chunk_path = item
        video = videos_by_id[video_id]
        chunk = json.loads(Path(chunk_path).read_text(encoding="utf-8"))
        try:
            run_frames(
                video_id,
                video["url"],
                chunk,
                state["output_dir"],
                video_duration_seconds=video["duration_seconds"],
            )
        except Exception as error:  # noqa: BLE001 - screenshots are optional
            # Screenshots are an extra, the notes are the book: a blocked or
            # failed video download (e.g. YouTube's "confirm you're not a bot")
            # used to fail the whole book after all the writing was done.
            # Nothing is saved for this chunk, so a later --resume/retry tries
            # its screenshots again.
            logging.getLogger("app.nodes.frames").warning(
                "no screenshots for %s chunk %s: %s", video_id, chunk["chunk_index"], error
            )

    try:
        _map_parallel(chunk_items, process, max_workers=_MAX_PARALLEL_FRAME_SCANS)
    finally:
        # VIDEO_MODE=download's temporary per-video copies -- never kept
        # past this node (root AGENTS.md: no stored video files).
        shutil.rmtree(Path(state["output_dir"]) / "work" / "frames" / "_video", ignore_errors=True)
    return {}


def _topics_node(state: BookState) -> dict:
    all_chunk_paths = [
        chunk_path
        for video_chunk_paths in state["chunk_paths"].values()
        for chunk_path in video_chunk_paths
    ]

    def process(chunk_path: str | None) -> None:
        if chunk_path is None:
            # The book's genre (lecture / podcast / comedy) is one more short
            # LLM call; it runs in the same pool so it costs no extra time.
            run_cached(
                genre_json_path(state["output_dir"]),
                lambda: run_genre(state["videos"], state["output_dir"]),
            )
            return
        chunk = json.loads(Path(chunk_path).read_text(encoding="utf-8"))
        output_path = topics_output_path(chunk, state["output_dir"])
        # A creator's own YouTube chapters are the speaker's real structure:
        # use them as this chunk's topics and skip the LLM call.
        video = next((v for v in state["videos"] if v["video_id"] == chunk["video_id"]), {})
        from_chapters = topics_from_youtube_chapters(chunk, video.get("chapters") or [])
        run_cached(
            output_path,
            lambda: write_topics(chunk, from_chapters, state["output_dir"])
            if from_chapters
            else run_topics(chunk_path, state["output_dir"]),
        )

    _map_parallel([None, *all_chunk_paths], process)
    return {}


def _write_node(state: BookState) -> dict:
    def process(video: dict) -> tuple[str, str]:
        video_id = video["video_id"]
        output_path = notes_output_path(video_id, state["output_dir"])
        run_cached(output_path, lambda: run_write(video_id, state["output_dir"]))
        return video_id, str(output_path)

    results = _map_parallel(state["videos"], process)
    return {"notes_paths": dict(results)}


def _outline_node(state: BookState) -> dict:
    chapters = run_outline(state["videos"], state["output_dir"])
    return {"chapters": chapters}


def _run_book_pass(chapters: list[dict], output_dir: str) -> dict:
    """Shared book_pass orchestration (sprints/v6 PRD.md): subject-index
    terms per chapter and a merged glossary -- both grounded in the
    chapters' own final notes. `chapters` is a mode-agnostic list of
    {file_key, title, notes_path} (non-skipped chapters only). Each
    underlying LLM call is cache-skipped via run_cached, matching every
    other step's crash-safety rule.

    The glossary is the only LLM work here (batched in parallel inside
    run_glossary); each chapter's index terms are then derived from it and
    the chapter's bold terms without an LLM call. No preface: the book is
    topic notes, and a generic preface was a page of filler.

    A comedy recap has no terms to define or look up, so it skips both (and
    their LLM calls).
    """
    if load_genre(output_dir) == "comedy":
        return {"glossary": [], "index_terms_by_file_key": {}}

    chapters_with_notes = [
        {"title": chapter["title"], "notes": Path(chapter["notes_path"]).read_text(encoding="utf-8")}
        for chapter in chapters
    ]
    glossary_path = glossary_json_path(output_dir)
    run_cached(glossary_path, lambda: run_glossary(chapters_with_notes, output_dir))
    glossary = json.loads(glossary_path.read_text(encoding="utf-8"))
    glossary_terms = [entry["term"] for entry in glossary]

    # Index terms need no LLM call: the glossary terms each chapter mentions
    # plus its bold terms (app.nodes.book_pass.index_terms_from_notes).
    index_terms_by_file_key = {}
    for chapter, chapter_notes in zip(chapters, chapters_with_notes):
        terms_path = index_terms_json_path(chapter["file_key"], output_dir)
        run_cached(
            terms_path,
            lambda chapter=chapter, notes=chapter_notes["notes"]: run_index_terms(
                chapter["file_key"], notes, output_dir, glossary_terms
            ),
        )
        index_terms_by_file_key[chapter["file_key"]] = json.loads(terms_path.read_text(encoding="utf-8"))

    return {
        "glossary": glossary,
        "index_terms_by_file_key": index_terms_by_file_key,
    }


def _book_title(videos: list[dict]) -> str:
    """The source video's own title for a single-video book; "Video2Book"
    (main.tex.j2's long-standing default) for a playlist, since synthesizing
    one title for a merged multi-video book is a separate design question,
    not this fix's scope. Verified against a real book: with no title ever
    threaded through at all, every book's title page read "Video2Book"
    regardless of the source video."""
    if len(videos) == 1:
        return videos[0]["title"]
    return "Video2Book"


def _render_chapters(
    chapters: list[dict],
    output_dir: str,
    glossary_entries: list[dict] | None = None,
    book_title: str = "Video2Book",
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
    are marked with \\index{} at their first occurrence. `glossary_entries`
    (sprints/v6 PRD.md), if given, adds the glossary. No preface or topic
    index: the book is topic notes, and both were filler pages. Everything downstream
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
            # Where each section is spoken: places screenshots by time and
            # links each section to its moment on YouTube (app.nodes.align).
            chapter_section_times(notes, chapter.get("sources", []), output_dir),
        )
        file_keys.append(chapter["file_key"])

    total_hours = sum(chapter.get("hours", 0.0) for chapter in chapters)
    volume_hours = load_settings().volume_hours

    if total_hours <= volume_hours:
        main_tex_path = render_book(
            file_keys,
            output_dir,
            glossary_entries=glossary_entries,
            book_title=book_title,
            book_kind=BOOK_KINDS[load_genre(output_dir)],
        )
        pdf_path = compile_chapter(main_tex_path)
        book_pdf_path = Path(output_dir) / "book.pdf"
        shutil.copyfile(pdf_path, book_pdf_path)
        _write_exports(chapters, output_dir, book_title)
        return str(main_tex_path), str(book_pdf_path)

    chapters_with_hours = [
        (chapter["file_key"], chapter.get("hours", 0.0)) for chapter in chapters
    ]
    chapter_groups = split_into_volumes(chapters_with_hours, volume_hours)
    volume_tex_paths = render_book_volumes(
        chapter_groups,
        output_dir,
        glossary_entries=glossary_entries,
        book_title=book_title,
        book_kind=BOOK_KINDS[load_genre(output_dir)],
    )

    last_pdf_path = None
    for volume_index, main_tex_path in enumerate(volume_tex_paths, start=1):
        pdf_path = compile_chapter(main_tex_path)
        volume_pdf_path = Path(output_dir) / f"book_vol{volume_index}.pdf"
        shutil.copyfile(pdf_path, volume_pdf_path)
        last_pdf_path = volume_pdf_path

    _write_exports(chapters, output_dir, book_title)
    return str(volume_tex_paths[-1]), str(last_pdf_path)


def _write_exports(chapters: list[dict], output_dir: str, book_title: str) -> None:
    """book.md and book.epub next to the PDF (app.export). Optional extras: a
    failure is logged as a warning and never fails the book."""
    try:
        exported = [
            {"title": chapter["title"], "notes": Path(chapter["notes_path"]).read_text(encoding="utf-8")}
            for chapter in chapters
        ]
        book_kind = BOOK_KINDS[load_genre(output_dir)]
        write_markdown_book(exported, Path(output_dir) / "book.md", book_title)
        write_epub(exported, Path(output_dir) / "book.epub", book_title, book_kind)
    except Exception as error:  # noqa: BLE001 - extra formats must not fail the PDF
        logging.getLogger("app.nodes.export").warning("could not write book.md/book.epub: %s", error)


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
            "sources": [
                {"video_id": chapter["video_id"], "chunk_index": index}
                for index in range(len(state["chunk_paths"].get(chapter["video_id"], [])))
            ],
            "index_terms": index_terms_by_file_key.get(chapter["video_id"], []),
        }
        for chapter in state["chapters"]
        if not chapter["skip"]
    ]
    tex_path, pdf_path = _render_chapters(
        chapters,
        state["output_dir"],
        glossary_entries=book_pass.get("glossary"),
        book_title=_book_title(state["videos"]),
    )
    return {"tex_path": tex_path, "pdf_path": pdf_path}


# --- BOOK_ORDER=topic nodes (v3) ---------------------------------------


def _plan_node(state: BookState) -> dict:
    # Cached: the render phase re-runs the graph from START, and without
    # this the plan LLM call ran again -- wasting time and, worse, able to
    # produce a different plan than the outline the user already reviewed.
    output_dir = state["output_dir"]

    def plan() -> None:
        # One chunk in the whole book (a single short video): nothing to
        # merge, so skip the LLM merge call and write one chapter.
        if run_single_chunk_plan(output_dir, state["videos"][0]["title"]) is None:
            run_plan_topics(output_dir)

    run_cached(plan_json_path(output_dir), plan)
    return {}


def _order_node(state: BookState) -> dict:
    ordered = run_order_topics(state["output_dir"])
    return {"ordered_topics": ordered}


def _topic_outline_node(state: BookState) -> dict:
    chapters = run_topic_outline(state["ordered_topics"], state["output_dir"])
    return {"chapters": chapters}


def _write_topic_node(state: BookState) -> dict:
    def process(chapter: dict) -> tuple[str, str]:
        output_path = notes_output_path(f"topic_{chapter['slug']}", state["output_dir"])
        run_cached(output_path, lambda: run_write_topic(chapter, state["output_dir"]))
        return chapter["id"], str(output_path)

    results = _map_parallel(state["chapters"], process)
    return {"notes_paths": dict(results)}


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


def _chunk_key(source: dict) -> tuple[str, int]:
    return source["video_id"], source["chunk_index"]


def _topic_chapter_hours_and_fresh_sources(
    chapters: list[dict], chunk_minutes: int
) -> list[tuple[float, list[dict]]]:
    """Per chapter: (hours, sources whose screenshots it should show).

    In topic mode one source chunk can feed several chapters (a 30-minute
    chunk usually covers a few topics). Counting the whole chunk for every
    chapter made a 13-hour video look like 20-40 hours -- which wrongly
    split it into volumes (backend/ stores one PDF per book, so a second
    volume would never be uploaded) -- and repeated the chunk's screenshots
    in every chapter that used it. Instead each chunk's time is shared
    evenly between the chapters that use it (the total is the real
    duration), and its screenshots go only to the first chapter that uses it.
    """
    # A chapter listing the same chunk twice still uses it once.
    sources_by_chapter = [
        list({_chunk_key(source): source for source in chapter.get("sources", [])}.values())
        for chapter in chapters
    ]
    users = Counter(_chunk_key(source) for sources in sources_by_chapter for source in sources)
    chunk_hours = chunk_minutes / 60
    shown: set[tuple[str, int]] = set()
    result = []
    for sources in sources_by_chapter:
        hours = sum(chunk_hours / users[_chunk_key(source)] for source in sources)
        fresh = [source for source in sources if _chunk_key(source) not in shown]
        shown.update(_chunk_key(source) for source in sources)
        result.append((hours, fresh))
    return result


def _render_topic_node(state: BookState) -> dict:
    chunk_minutes = load_settings().chunk_minutes
    book_pass = state.get("book_pass", {})
    index_terms_by_file_key = book_pass.get("index_terms_by_file_key", {})

    active = [chapter for chapter in state["chapters"] if not chapter["skip"]]
    hours_and_sources = _topic_chapter_hours_and_fresh_sources(active, chunk_minutes)

    chapters = [
        {
            "file_key": chapter["slug"],
            "title": chapter["title"],
            "notes_path": state["notes_paths"][chapter["id"]],
            "screenshots": load_screenshots_for_sources(fresh_sources, state["output_dir"]),
            "sources": chapter.get("sources", []),
            "hours": hours,
            "index_terms": index_terms_by_file_key.get(chapter["slug"], []),
        }
        for chapter, (hours, fresh_sources) in zip(active, hours_and_sources)
    ]
    tex_path, pdf_path = _render_chapters(
        chapters,
        state["output_dir"],
        glossary_entries=book_pass.get("glossary"),
        book_title=_book_title(state["videos"]),
    )
    return {"tex_path": tex_path, "pdf_path": pdf_path}


def build_video_graph(checkpointer=None):
    """BOOK_ORDER=video (v2): fetch->chunk->{frames, topics->write->outline->
    book_pass}->render->END.

    `frames` and `topics` run as parallel branches off `chunk` (sprints/v10):
    both write no BookState keys of their own (screenshots and topics are
    read back from disk by `render`/`topics`->`write` respectively, not
    passed through graph state), so there's no state-merge conflict, and
    `topics` has no data dependency on `frames`' output -- only the two
    branches converging at `render` (which reads frames' saved screenshots
    from disk) enforces frames must finish before render, same guarantee as
    the old strictly-sequential chain, just without frames blocking topics/
    write/outline/book_pass from starting concurrently.
    """
    builder = StateGraph(BookState)
    builder.add_node("fetch", _timed("fetch", _fetch_node))
    builder.add_node("check_budget", _timed("check_budget", _check_budget_node))
    builder.add_node("chunk", _timed("chunk", _chunk_node))
    builder.add_node("frames", _timed("frames", _frames_node))
    builder.add_node("topics", _timed("topics", _topics_node))
    builder.add_node("write", _timed("write", _write_node))
    builder.add_node("outline", _timed("outline", _outline_node))
    builder.add_node("book_pass", _timed("book_pass", _book_pass_node))
    builder.add_node("render", _timed("render", _render_node))

    builder.add_edge(START, "fetch")
    builder.add_edge("fetch", "check_budget")
    builder.add_edge("check_budget", "chunk")
    builder.add_edge("chunk", "frames")
    builder.add_edge("chunk", "topics")
    builder.add_edge("topics", "write")
    builder.add_edge("write", "outline")
    builder.add_edge("outline", "book_pass")
    builder.add_edge(["frames", "book_pass"], "render")
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
    builder.add_node("fetch", _timed("fetch", _fetch_node))
    builder.add_node("check_budget", _timed("check_budget", _check_budget_node))
    builder.add_node("chunk", _timed("chunk", _chunk_node))
    builder.add_node("topics", _timed("topics", _topics_node))
    builder.add_node("write", _timed("write", _write_node))
    builder.add_node("outline", _timed("outline", _outline_node))

    builder.add_edge(START, "fetch")
    builder.add_edge("fetch", "check_budget")
    builder.add_edge("check_budget", "chunk")
    builder.add_edge("chunk", "topics")
    builder.add_edge("topics", "write")
    builder.add_edge("write", "outline")
    builder.add_edge("outline", END)

    return builder.compile(checkpointer=checkpointer)


def build_topic_graph(checkpointer=None):
    """BOOK_ORDER=topic (v3): fetch->check_budget->chunk->{frames, topics->
    plan->order->outline->write->book_pass}->render->END.

    `frames` runs parallel to topics/plan/order/outline/write/book_pass
    (sprints/v10), same rationale as `build_video_graph`: no state-key
    conflict, no data dependency, only `render` (which reads frames' saved
    screenshots from disk) needs frames to have finished.
    """
    builder = StateGraph(BookState)
    builder.add_node("fetch", _timed("fetch", _fetch_node))
    builder.add_node("check_budget", _timed("check_budget", _check_budget_node))
    builder.add_node("chunk", _timed("chunk", _chunk_node))
    builder.add_node("frames", _timed("frames", _frames_node))
    builder.add_node("topics", _timed("topics", _topics_node))
    builder.add_node("plan", _timed("plan", _plan_node))
    builder.add_node("order", _timed("order", _order_node))
    builder.add_node("outline", _timed("outline", _topic_outline_node))
    builder.add_node("write", _timed("write", _write_topic_node))
    builder.add_node("book_pass", _timed("book_pass", _book_pass_topic_node))
    builder.add_node("render", _timed("render", _render_topic_node))

    builder.add_edge(START, "fetch")
    builder.add_edge("fetch", "check_budget")
    builder.add_edge("check_budget", "chunk")
    builder.add_edge("chunk", "frames")
    builder.add_edge("chunk", "topics")
    builder.add_edge("topics", "plan")
    builder.add_edge("plan", "order")
    builder.add_edge("order", "outline")
    builder.add_edge("outline", "write")
    builder.add_edge("write", "book_pass")
    builder.add_edge(["frames", "book_pass"], "render")
    builder.add_edge("render", END)

    return builder.compile(checkpointer=checkpointer)


def build_topic_plan_graph(checkpointer=None):
    """BOOK_ORDER=topic, --plan-only: stops before write/render/compile."""
    builder = StateGraph(BookState)
    builder.add_node("fetch", _timed("fetch", _fetch_node))
    builder.add_node("check_budget", _timed("check_budget", _check_budget_node))
    builder.add_node("chunk", _timed("chunk", _chunk_node))
    builder.add_node("topics", _timed("topics", _topics_node))
    builder.add_node("plan", _timed("plan", _plan_node))
    builder.add_node("order", _timed("order", _order_node))
    builder.add_node("outline", _timed("outline", _topic_outline_node))

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


def _parse_checkpoint_dt(value) -> datetime:
    """LangGraph's StateSnapshot.created_at is an ISO-8601 string in real
    checkpoints (confirmed by this module's own test fixtures); accept a
    datetime too defensively since that's not contractually guaranteed."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value)


def get_progress(output_dir: str | Path, checkpointer, book_order: str | None = None, phase: str = "render") -> dict:
    """Read-only: reports where a book's LangGraph run currently stands,
    without invoking anything (sprints/v7 Task 4; elapsed/percent added
    sprints/v10 Task 2). Node names/ordering knowledge stays here, next to
    where the graphs themselves are defined -- callers (e.g. backend/'s
    `/events` endpoint) never hardcode a node list.

    `phase`: "plan" inspects the --plan-only graph variant (matches
    `run_plan`'s node set, which skips `frames`/`write` down to `render`);
    anything else inspects the full graph variant (matches `run_book`/
    `resume_book`). This must match which of `run_plan`/`run_book` actually
    produced the checkpoint being read, the same way backend/'s
    `process_run_book` already tracks a book's current phase.

    Returns `{"completed_nodes": [...], "current_node": str | None,
    "next_nodes": [...], "step": int, "percent": int, "elapsed_seconds":
    int}`. A `thread_id` with no checkpoint yet (book not started) returns
    all-empty/zero rather than raising.

    `next_nodes` can hold more than one entry now that `frames` runs as a
    parallel branch (sprints/v10 Task 1): `current_node`/`completed_nodes`
    are derived from the *earliest*-positioned pending node in `node_order`,
    not naively from `next_nodes[0]`, so a node genuinely still running in
    the other (not-yet-reported) branch is never miscounted as completed.

    Known limitation: if the higher-`node_order`-index parallel branch
    (`topics`) finishes before the lower-index one (`frames`) -- the
    reverse of node_order's positional assumption -- `topics` is
    under-reported as not-yet-completed (and `percent` undercounts by one
    node's worth) until `frames` also finishes and both leave `next`. This
    never affects pipeline correctness (`render` still genuinely waits for
    both via the graph's join edge) -- it's a progress-display accuracy
    trade-off, acceptable for the "elapsed + percent, no ETA" scope this
    was built for (sprints/v10 PRD).
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
        return {
            "completed_nodes": [],
            "current_node": None,
            "next_nodes": [],
            "step": 0,
            "percent": 0,
            "elapsed_seconds": 0,
        }

    next_nodes = sorted(
        snapshot.next, key=lambda n: node_order.index(n) if n in node_order else len(node_order)
    )
    current_node = next_nodes[0] if next_nodes else None
    if next_nodes:
        boundary = min(
            (node_order.index(n) for n in next_nodes if n in node_order), default=len(node_order)
        )
        completed_nodes = node_order[:boundary]
    else:
        # next == () -- the graph ran to completion; every node in this
        # phase's order is done.
        completed_nodes = list(node_order)

    step = snapshot.metadata.get("step", 0) if snapshot.metadata else 0
    percent = round(len(completed_nodes) / len(node_order) * 100) if node_order else 0

    history = list(graph.get_state_history(config))
    started_at = _parse_checkpoint_dt(history[-1].created_at if history else snapshot.created_at)
    # Elapsed freezes at the last checkpoint's time once the run is done
    # (next_nodes empty) so it doesn't keep growing on a later poll; while
    # still in progress it's measured against wall-clock now, so it keeps
    # ticking between checkpoint writes.
    end_time = datetime.now(timezone.utc) if next_nodes else _parse_checkpoint_dt(snapshot.created_at)
    elapsed_seconds = max(0, round((end_time - started_at).total_seconds()))

    return {
        "completed_nodes": completed_nodes,
        "current_node": current_node,
        "next_nodes": next_nodes,
        "step": step,
        "percent": percent,
        "elapsed_seconds": elapsed_seconds,
    }


def get_chapter_progress(output_dir: str | Path) -> list[dict]:
    """Read-only: reports each chapter's write-and-verify progress, without
    invoking anything (sprints/v9). Reads outline.json (the chapter list)
    plus whatever notes/status files app.nodes.write has produced so far --
    never touches LangGraph, since a chapter's status is a disk artifact,
    not graph state.

    A chapter's write-key is self-evident from its own outline.json shape:
    "video_id" present -> BOOK_ORDER=video's key (matches
    notes_output_path's <video_id>.md); otherwise -> BOOK_ORDER=topic's
    "topic_<slug>" key. No book_order param needed, unlike get_progress,
    which needs it to build a graph before it can call get_state.

    Returns one dict per chapter: {"id", "title", "status": "pending" |
    "done", "score", "attempts", "passed"} -- the last three are None until
    "done". Returns [] (not an error) if outline.json doesn't exist yet
    (outline hasn't run).
    """
    output_dir = Path(output_dir)
    path = outline_json_path(output_dir)
    if not path.exists():
        return []

    chapters = json.loads(path.read_text(encoding="utf-8"))
    progress = []
    for chapter in chapters:
        key = chapter["video_id"] if "video_id" in chapter else f"topic_{chapter['slug']}"
        done = notes_output_path(key, output_dir).exists()
        status = None
        if done:
            status_path = chapter_status_path(key, output_dir)
            if status_path.exists():
                status = json.loads(status_path.read_text(encoding="utf-8"))

        progress.append(
            {
                "id": chapter["id"],
                "title": chapter["title"],
                "status": "done" if done else "pending",
                "score": status["score"] if status else None,
                "attempts": status["attempts"] if status else None,
                "passed": status["passed"] if status else None,
            }
        )
    return progress


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


def warnings_path(output_dir: str | Path) -> Path:
    """The deterministic warnings.jsonl path for a book (sprints/v11:
    surfacing non-fatal degradations). Exposed so callers (e.g. a test, or
    a future cache-aware node) can check it without reconstructing the
    path themselves.
    """
    return Path(output_dir) / "warnings.jsonl"


# Which book's warnings.jsonl the current run writes to. A context
# variable, not a per-run handler: with several books running concurrently
# in one worker process, a handler attached per run to the shared
# "app.nodes" logger would copy every book's warnings into every other
# running book's file.
_current_warnings_path: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "v2b_current_warnings_path", default=None
)
_warnings_handler_lock = threading.Lock()
_warnings_handler_installed = False


class _WarningFileHandler(logging.Handler):
    """Appends each WARNING+ log record to the current run's warnings.jsonl
    the instant it's emitted -- not collected in memory and written once at
    the end, so a warning survives a crash the same way every other step's
    output does (root AGENTS.md: "every step saves to disk"). Records
    logged outside any run (no path in context) are ignored.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        path = _current_warnings_path.get()
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")


def _ensure_warnings_handler() -> None:
    global _warnings_handler_installed
    with _warnings_handler_lock:
        if not _warnings_handler_installed:
            logging.getLogger("app.nodes").addHandler(_WarningFileHandler())
            _warnings_handler_installed = True


@contextmanager
def _collect_warnings(output_dir: str | Path) -> Iterator[None]:
    """Captures every WARNING+ record logged by app.nodes.* (e.g. "topics
    extraction ... produced no usable JSON array after a retry;
    continuing with an empty topics list") during one graph run, to
    <output_dir>/warnings.jsonl -- these already-logged degradations
    (topics.py, plan.py, book_pass.py, write.py, verify.py, frames.py all
    log-and-continue rather than raise) previously only ever reached
    stdout/worker logs, with no way for a caller like backend/'s /events
    stream to know a book's output had quietly degraded. Attaching to the
    "app.nodes" logger (the common parent of every node module's own
    logging.getLogger(__name__)) via normal log propagation captures all
    of them in one place without touching each node file.
    """
    _ensure_warnings_handler()
    token = _current_warnings_path.set(warnings_path(output_dir))
    try:
        yield
    finally:
        _current_warnings_path.reset(token)


def get_warnings(output_dir: str | Path) -> list[dict]:
    """Read-only: every non-fatal degradation warning logged so far for
    this book (sprints/v11), without invoking anything -- same disk-
    artifact-read pattern as get_chapter_progress. Returns [] if the run
    hasn't logged any yet, or hasn't started (not an error).
    """
    path = warnings_path(output_dir)
    if not path.exists():
        return []
    warnings: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            warnings.append(json.loads(line))
    return warnings


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
        with _collect_warnings(output_dir):
            final_state = graph.invoke(
                {"url": url, "output_dir": str(output_dir), "force": force}, config=config
            )
        return Path(final_state["pdf_path"])

    with SqliteSaver.from_conn_string(str(_checkpoint_db_path(output_dir))) as sqlite_checkpointer:
        graph = build_graph(checkpointer=sqlite_checkpointer)
        config = {"configurable": {"thread_id": str(output_dir)}}
        with _collect_warnings(output_dir):
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
        with _collect_warnings(output_dir):
            final_state = graph.invoke(
                {"url": url, "output_dir": str(output_dir), "force": force}, config=config
            )
        return final_state["videos"], final_state["chapters"]

    with SqliteSaver.from_conn_string(str(_checkpoint_db_path(output_dir))) as sqlite_checkpointer:
        graph = build_plan_graph(checkpointer=sqlite_checkpointer)
        config = {"configurable": {"thread_id": str(output_dir)}}
        with _collect_warnings(output_dir):
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
        with _collect_warnings(output_dir):
            final_state = graph.invoke(None, config=config)
        return Path(final_state["pdf_path"])

    db_path = _checkpoint_db_path(output_dir)
    if not db_path.exists():
        raise FileNotFoundError(f"no checkpoint database found at {db_path}")

    with SqliteSaver.from_conn_string(str(db_path)) as sqlite_checkpointer:
        graph = build_graph(checkpointer=sqlite_checkpointer)
        config = {"configurable": {"thread_id": str(output_dir)}}
        with _collect_warnings(output_dir):
            final_state = graph.invoke(None, config=config)

    return Path(final_state["pdf_path"])
