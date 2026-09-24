from api.models import Book


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
    assert body == {
        "id": book.id,
        "status": "running",
        "pdf_path": None,
        "error_message": None,
    }


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
