from api.models import Book, Video


def test_get_unknown_book_returns_404(client, auth_headers):
    resp = client.get("/books/does-not-exist", headers=auth_headers)
    assert resp.status_code == 404


def test_get_book_requires_auth(client, db_session, user):
    book = Book(url="https://www.youtube.com/watch?v=abc123", status="running", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    resp = client.get(f"/books/{book.id}")
    assert resp.status_code == 401


def test_get_book_from_another_user_returns_404(client, db_session, user, make_user):
    book = Book(url="https://www.youtube.com/watch?v=abc123", status="running", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    _other_user, _key, other_headers = make_user()
    resp = client.get(f"/books/{book.id}", headers=other_headers)
    assert resp.status_code == 404


def test_get_book_reflects_current_db_state(client, db_session, user, auth_headers):
    book = Book(url="https://www.youtube.com/watch?v=abc123", status="running", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    resp = client.get(f"/books/{book.id}", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    created_at = body.pop("created_at")
    assert created_at  # ISO 8601 timestamp -- exact value is DB-generated, not asserted
    assert body == {
        "id": book.id,
        "status": "running",
        "pdf_path": None,
        "error_message": None,
        "estimated_cost_usd": 0.0,
        "url": "https://www.youtube.com/watch?v=abc123",
        "videos": [],
    }


def test_get_book_includes_video_titles(client, db_session, user, auth_headers):
    book = Book(url="https://www.youtube.com/playlist?list=xyz", status="planning", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    db_session.add_all(
        [
            Video(
                book_id=book.id,
                video_id="vid1",
                title="Lecture 1: Introduction",
                url="https://www.youtube.com/watch?v=vid1",
                duration_seconds=1800,
            ),
            Video(
                book_id=book.id,
                video_id="vid2",
                title=None,
                url="https://www.youtube.com/watch?v=vid2",
                duration_seconds=None,
            ),
        ]
    )
    db_session.commit()

    resp = client.get(f"/books/{book.id}", headers=auth_headers)

    assert resp.status_code == 200
    videos = resp.json()["videos"]
    assert len(videos) == 2
    assert {"video_id": "vid1", "title": "Lecture 1: Introduction", "duration_seconds": 1800} in videos
    assert {"video_id": "vid2", "title": None, "duration_seconds": None} in videos


def test_get_book_reports_done_with_pdf_path(client, db_session, user, auth_headers):
    book = Book(
        url="https://www.youtube.com/watch?v=abc123",
        status="done",
        pdf_path="output/xyz/book.pdf",
        user_id=user.id,
    )
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    resp = client.get(f"/books/{book.id}", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "done"
    assert resp.json()["pdf_path"] == "output/xyz/book.pdf"


def test_get_book_reports_failed_with_error_message(client, db_session, user, auth_headers):
    book = Book(
        url="https://www.youtube.com/watch?v=abc123",
        status="failed",
        error_message="NVIDIA and Gemini both failed",
        user_id=user.id,
    )
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    resp = client.get(f"/books/{book.id}", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"
    assert resp.json()["error_message"] == "NVIDIA and Gemini both failed"
