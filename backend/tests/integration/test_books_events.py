import dataclasses
import json

import api.routers.books as books_module
from api.config import settings as real_settings
from api.db import SessionLocal
from api.models import Book


def test_events_requires_auth(client, db_session, user):
    book = Book(url="https://www.youtube.com/watch?v=abc123", status="done", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    with client.stream("GET", f"/books/{book.id}/events") as resp:
        assert resp.status_code == 401


def test_events_404_for_unknown_book(client, auth_headers):
    with client.stream("GET", "/books/does-not-exist/events", headers=auth_headers) as resp:
        assert resp.status_code == 404


def test_events_404_for_another_users_book(client, db_session, user, make_user):
    book = Book(url="https://www.youtube.com/watch?v=abc123", status="done", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    _other_user, _key, other_headers = make_user()
    with client.stream("GET", f"/books/{book.id}/events", headers=other_headers) as resp:
        assert resp.status_code == 404


def test_events_streams_a_terminal_event_for_a_done_book(client, db_session, user, auth_headers):
    book = Book(
        url="https://www.youtube.com/watch?v=abc123",
        status="done",
        pdf_path="placeholder/book.pdf",
        user_id=user.id,
    )
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    with client.stream("GET", f"/books/{book.id}/events", headers=auth_headers) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        lines = [line for line in resp.iter_lines() if line]

    assert any(line == "event: done" for line in lines)


def test_events_streams_a_terminal_event_for_a_failed_book(client, db_session, user, auth_headers):
    book = Book(
        url="https://www.youtube.com/watch?v=abc123",
        status="failed",
        error_message="boom",
        user_id=user.id,
    )
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    with client.stream("GET", f"/books/{book.id}/events", headers=auth_headers) as resp:
        assert resp.status_code == 200
        lines = [line for line in resp.iter_lines() if line]

    assert any(line == "event: failed" for line in lines)


def _parse_sse(lines: list[str]) -> list[tuple[str, dict]]:
    events = []
    current_event = None
    for line in lines:
        if line.startswith("event: "):
            current_event = line[len("event: ") :]
        elif line.startswith("data: "):
            events.append((current_event, json.loads(line[len("data: ") :])))
    return events


def test_events_includes_chapters_and_a_chapter_change_produces_a_new_event(
    client, db_session, user, auth_headers, monkeypatch
):
    book = Book(url="https://www.youtube.com/watch?v=abc123", status="rendering", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    monkeypatch.setattr(
        books_module, "settings", dataclasses.replace(real_settings, events_poll_seconds=0.01)
    )
    monkeypatch.setattr(
        books_module,
        "ai_llm_get_progress",
        lambda output_dir, checkpointer, book_order, phase: {
            "completed_nodes": ["fetch", "chunk", "topics"],
            "current_node": "write",
            "next_nodes": ["outline"],
            "step": 3,
        },
    )

    calls = {"n": 0}

    def fake_chapter_progress(output_dir):
        calls["n"] += 1
        if calls["n"] == 1:
            return [
                {
                    "id": "chapter:vid1",
                    "title": "V1",
                    "status": "pending",
                    "score": None,
                    "attempts": None,
                    "passed": None,
                }
            ]

        # Stop the stream once the chapter has "finished" -- a fresh
        # session, since this runs in asyncio.to_thread's own thread.
        session = SessionLocal()
        try:
            row = session.get(Book, book.id)
            row.status = "done"
            session.commit()
        finally:
            session.close()

        return [
            {
                "id": "chapter:vid1",
                "title": "V1",
                "status": "done",
                "score": 9,
                "attempts": 1,
                "passed": True,
            }
        ]

    monkeypatch.setattr(books_module, "ai_llm_get_chapter_progress", fake_chapter_progress)

    with client.stream("GET", f"/books/{book.id}/events", headers=auth_headers) as resp:
        assert resp.status_code == 200
        lines = [line for line in resp.iter_lines() if line]

    events = _parse_sse(lines)
    progress_events = [data for event, data in events if event == "progress"]

    assert len(progress_events) == 2
    assert progress_events[0]["chapters"][0]["status"] == "pending"
    assert progress_events[1]["chapters"][0]["status"] == "done"
    assert progress_events[1]["chapters"][0]["score"] == 9
    assert progress_events[1]["chapters"][0]["attempts"] == 1
    assert events[-1][0] == "done"
