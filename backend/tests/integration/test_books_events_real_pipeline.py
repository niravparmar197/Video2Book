"""sprints/v7 Task 8: a real end-to-end integration test -- the actual
ai_llm graph (real Postgres checkpointer, real node functions) runs behind
a real uvicorn server (a real TCP socket, real chunked SSE delivery -- not
httpx's in-process ASGITransport, which buffers a whole request before
returning it and so can't demonstrate genuine wall-clock streaming) while
a real httpx client reads `/events` concurrently. The events actually
received, in actual receipt order, must reflect real node transitions in
the correct order, ending in a real terminal event.

Only the LLM/video/compile boundary is stubbed (the same boundary every
ai_llm unit test stubs -- root AGENTS.md: never call a real LLM/YouTube/
paid API from a test). ai_llm's own `tests/unit/conftest.py` provides these
same stubs as autouse fixtures for *its* test session; this test lives in
backend/'s test session, which doesn't get them for free, so they're set
up explicitly here.
"""

import asyncio
import dataclasses
import json
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import uvicorn

import api.main as main_module
from api.config import settings as real_settings
from api.jobs import run_book as run_book_job
from api.jobs.run_book import process_run_book
from api.models import Book
from api.routers import books as books_module

import app.graph as ai_llm_graph_module
import app.nodes.book_pass as ai_llm_book_pass_module
import app.nodes.topics as ai_llm_topics_module
import app.nodes.verify as ai_llm_verify_module
import app.nodes.write as ai_llm_write_module
from app.youtube import VideoInfo

SAMPLE_VTT = (
    "WEBVTT\n\n"
    "00:00:00.000 --> 00:00:02.500\n"
    "Hello and welcome to this video about neural networks.\n"
)

_NODE_ORDER = [
    "fetch", "check_budget", "chunk", "frames", "topics", "write", "outline", "book_pass", "render",
]


def _fake_run_fetch_playlist(url, output_dir):
    time.sleep(0.05)
    output_dir = Path(output_dir)
    captions_dir = output_dir / "work" / "captions"
    captions_dir.mkdir(parents=True, exist_ok=True)
    captions_path = captions_dir / "vid1.en.vtt"
    captions_path.write_text(SAMPLE_VTT, encoding="utf-8")
    return [
        VideoInfo(
            video_id="vid1",
            title="A video",
            duration_seconds=100,
            url=url,
            captions_path=str(captions_path),
        )
    ]


def _slow_topics_call_writer(prompt, **kw):
    time.sleep(0.05)
    return '["neural networks"]'


def _slow_write_call_writer(prompt, **kw):
    time.sleep(0.05)
    return "## Neural Networks\n\nNotes."


def _passing_judge_call_writer(prompt, **kw):
    return json.dumps({"score": 10, "feedback": "looks good"})


def _fake_compile_chapter(tex_path, **kwargs):
    time.sleep(0.02)
    pdf_path = Path(tex_path).with_suffix(".pdf")
    pdf_path.write_bytes(b"%PDF-fake")
    return pdf_path


async def test_events_stream_reflects_real_node_transitions_in_order(
    monkeypatch, db_session, user, auth_headers, tmp_path
):
    monkeypatch.setenv("BOOK_ORDER", "video")
    monkeypatch.setenv("VIDEO_MODE", "captions_only")

    monkeypatch.setattr(ai_llm_graph_module, "run_fetch_playlist", _fake_run_fetch_playlist)
    monkeypatch.setattr(ai_llm_topics_module, "call_writer", _slow_topics_call_writer)
    monkeypatch.setattr(ai_llm_write_module, "call_writer", _slow_write_call_writer)
    monkeypatch.setattr(ai_llm_verify_module, "call_writer", _passing_judge_call_writer)
    monkeypatch.setattr(ai_llm_book_pass_module, "call_writer", lambda prompt, **kw: "[]")
    monkeypatch.setattr(ai_llm_graph_module, "compile_chapter", _fake_compile_chapter)

    fake_settings = dataclasses.replace(
        real_settings, output_root=str(tmp_path), events_poll_seconds=0.01
    )
    monkeypatch.setattr(run_book_job, "settings", fake_settings)
    monkeypatch.setattr(books_module, "settings", fake_settings)

    book = Book(
        url="https://www.youtube.com/watch?v=vid1", status="outline_ready", user_id=user.id
    )
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    job = SimpleNamespace(
        data={"book_id": book.id, "url": book.url, "phase": "render"},
        opts={"attempts": 1},
        attemptsMade=0,
    )

    config = uvicorn.Config(main_module.app, host="127.0.0.1", port=0, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]

        events_seen: list[tuple[str, dict]] = []

        async def _consume_events():
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                async with client.stream(
                    "GET", f"/books/{book.id}/events", headers=auth_headers
                ) as resp:
                    assert resp.status_code == 200
                    current_event = None
                    async for line in resp.aiter_lines():
                        if line.startswith("event: "):
                            current_event = line[len("event: ") :]
                        elif line.startswith("data: ") and current_event:
                            payload = json.loads(line[len("data: ") :])
                            events_seen.append((current_event, payload))
                            if current_event in ("done", "failed"):
                                return

        # Start the SSE consumer first and give it a moment to actually
        # connect and enter its polling loop, so it observes the run's
        # entire lifetime -- starting it concurrently with (or after) the
        # real pipeline risks the connection's real (if small) TCP/HTTP
        # setup latency eating into a short stubbed run's observation
        # window, undercounting distinct real nodes non-deterministically.
        consume_task = asyncio.create_task(_consume_events())
        await asyncio.sleep(0.1)
        run_task = asyncio.create_task(process_run_book(job))
        await asyncio.wait_for(asyncio.gather(consume_task, run_task), timeout=30)
    finally:
        server.should_exit = True
        await server_task

    progress_events = [payload for event, payload in events_seen if event == "progress"]
    node_sequence = [p["current_node"] for p in progress_events if p["current_node"]]

    # How many distinct real nodes a 0.01s poll interval actually catches
    # during a sub-2-second stubbed run is inherently sensitive to real
    # CPython GIL/thread scheduling under whatever load this specific
    # machine is under at the moment (ai_llm's own sprints/v7/TASKS.md Task
    # 4 Finding D documents the same class of real, observed shared-machine
    # scheduling variability) -- not something to chase with ever-longer
    # sleeps. What's asserted here doesn't depend on catching every node:
    # at least one real node was actually observed via live polling (proof
    # this is real data, not a canned/empty stream), whatever was captured
    # is in correct pipeline order and never regresses, and the stream
    # still ends in the correct real terminal event regardless of how many
    # intermediate polls landed.
    assert node_sequence, "expected at least one real intermediate node to be observed"
    order = {name: i for i, name in enumerate(_NODE_ORDER)}
    indices = [order[name] for name in node_sequence]
    assert indices == sorted(indices)

    assert events_seen[-1][0] == "done"

    db_session.refresh(book)
    assert book.status == "done"


# --- Per-chapter progress (sprints/v9 Task 6) -----------------------------


def _fake_run_fetch_playlist_two_videos(url, output_dir):
    time.sleep(0.05)
    output_dir = Path(output_dir)
    captions_dir = output_dir / "work" / "captions"
    captions_dir.mkdir(parents=True, exist_ok=True)

    videos = []
    for video_id, text in [
        ("vid1", "Hello and welcome to this video about neural networks."),
        ("vid2", "This second video explains gradient descent in detail."),
    ]:
        captions_path = captions_dir / f"{video_id}.en.vtt"
        captions_path.write_text(
            f"WEBVTT\n\n00:00:00.000 --> 00:00:02.500\n{text}\n", encoding="utf-8"
        )
        videos.append(
            VideoInfo(
                video_id=video_id,
                title=f"Video {video_id}",
                duration_seconds=100,
                url=url,
                captions_path=str(captions_path),
            )
        )
    return videos


def _write_call_writer_two_videos(prompt, **kw):
    time.sleep(0.02)
    return "## Notes\n\nContent."


_REFINE_STATE = {"vid1_judge_calls": 0}


def _judge_call_writer_one_refine_for_vid1(prompt, **kw):
    """vid1's first attempt fails and needs one refine; vid2 passes
    immediately -- so the two chapters end up with different real
    attempts/score/passed shapes."""
    if "neural networks" in prompt:
        _REFINE_STATE["vid1_judge_calls"] += 1
        if _REFINE_STATE["vid1_judge_calls"] == 1:
            return json.dumps({"score": 3, "feedback": "needs more detail"})
        # Widen the window for a mid-write poll to observe vid1 sitting at
        # "done" (attempts=2) before vid2's chapter starts.
        time.sleep(0.2)
        return json.dumps({"score": 9, "feedback": "great"})
    return json.dumps({"score": 10, "feedback": "great"})


async def test_events_stream_reflects_real_per_chapter_progress(
    monkeypatch, db_session, user, auth_headers, tmp_path
):
    monkeypatch.setenv("BOOK_ORDER", "video")
    monkeypatch.setenv("VIDEO_MODE", "captions_only")
    _REFINE_STATE["vid1_judge_calls"] = 0

    monkeypatch.setattr(ai_llm_graph_module, "run_fetch_playlist", _fake_run_fetch_playlist_two_videos)
    monkeypatch.setattr(ai_llm_topics_module, "call_writer", _slow_topics_call_writer)
    monkeypatch.setattr(ai_llm_write_module, "call_writer", _write_call_writer_two_videos)
    monkeypatch.setattr(ai_llm_verify_module, "call_writer", _judge_call_writer_one_refine_for_vid1)
    monkeypatch.setattr(ai_llm_book_pass_module, "call_writer", lambda prompt, **kw: "[]")
    monkeypatch.setattr(ai_llm_graph_module, "compile_chapter", _fake_compile_chapter)

    fake_settings = dataclasses.replace(
        real_settings, output_root=str(tmp_path), events_poll_seconds=0.01
    )
    monkeypatch.setattr(run_book_job, "settings", fake_settings)
    monkeypatch.setattr(books_module, "settings", fake_settings)

    book = Book(
        url="https://www.youtube.com/watch?v=vid1", status="outline_ready", user_id=user.id
    )
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    job = SimpleNamespace(
        data={"book_id": book.id, "url": book.url, "phase": "render"},
        opts={"attempts": 1},
        attemptsMade=0,
    )

    config = uvicorn.Config(main_module.app, host="127.0.0.1", port=0, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]

        events_seen: list[tuple[str, dict]] = []

        async def _consume_events():
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                async with client.stream(
                    "GET", f"/books/{book.id}/events", headers=auth_headers
                ) as resp:
                    assert resp.status_code == 200
                    current_event = None
                    async for line in resp.aiter_lines():
                        if line.startswith("event: "):
                            current_event = line[len("event: ") :]
                        elif line.startswith("data: ") and current_event:
                            payload = json.loads(line[len("data: ") :])
                            events_seen.append((current_event, payload))
                            if current_event in ("done", "failed"):
                                return

        consume_task = asyncio.create_task(_consume_events())
        await asyncio.sleep(0.1)
        run_task = asyncio.create_task(process_run_book(job))
        await asyncio.wait_for(asyncio.gather(consume_task, run_task), timeout=30)
    finally:
        server.should_exit = True
        await server_task

    progress_events = [payload for event, payload in events_seen if event == "progress"]

    # Track the latest-seen state per chapter id across every poll -- how
    # many polls land mid-write is real OS thread scheduling (same
    # documented variability as the node-order test above), so this
    # doesn't assume every poll caught every transition.
    latest_by_id: dict[str, dict] = {}
    for payload in progress_events:
        for chapter in payload.get("chapters", []):
            latest_by_id[chapter["id"]] = chapter

    assert latest_by_id, "expected at least one real chapter entry to be observed"

    # A chapter's status must never appear to regress across the observed
    # sequence (pending -> done, never done -> pending).
    seen_done: set[str] = set()
    for payload in progress_events:
        for chapter in payload.get("chapters", []):
            if chapter["id"] in seen_done:
                assert chapter["status"] == "done"
            elif chapter["status"] == "done":
                seen_done.add(chapter["id"])

    # The real point of this test: at least one real chapter was observed
    # reaching "done", and vid1's real refine attempt is visible if it was
    # caught by a poll (the 0.2s sleep above exists specifically to make
    # that likely, not guaranteed -- same tradeoff as the node-order test).
    done_chapters = {cid: c for cid, c in latest_by_id.items() if c["status"] == "done"}
    assert done_chapters, "expected at least one chapter to reach done"
    for chapter in done_chapters.values():
        assert chapter["score"] is not None
        assert chapter["attempts"] is not None
        assert chapter["passed"] is not None
    if "chapter:vid1" in done_chapters:
        assert done_chapters["chapter:vid1"]["attempts"] == 2
        assert done_chapters["chapter:vid1"]["passed"] is True

    assert events_seen[-1][0] == "done"

    db_session.refresh(book)
    assert book.status == "done"
