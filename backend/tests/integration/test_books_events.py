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
