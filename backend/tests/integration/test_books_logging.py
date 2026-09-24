from tests.conftest import parse_log_lines


def test_create_book_logs_book_id_and_step(client, log_stream, auth_headers):
    resp = client.post(
        "/books/youtube",
        json={"url": "https://www.youtube.com/watch?v=abc123"},
        headers=auth_headers,
    )
    book_id = resp.json()["id"]

    lines = parse_log_lines(log_stream)
    create_lines = [line for line in lines if line.get("step") == "create"]
    assert create_lines, f"no step=create log line among {lines}"
    assert all(line["book_id"] == book_id for line in create_lines)


def test_get_book_logs_book_id_and_step(client, log_stream, db_session, user, auth_headers):
    from api.models import Book

    book = Book(url="https://www.youtube.com/watch?v=abc123", status="running", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    client.get(f"/books/{book.id}", headers=auth_headers)

    lines = parse_log_lines(log_stream)
    get_lines = [line for line in lines if line.get("step") == "get"]
    assert get_lines, f"no step=get log line among {lines}"
    assert all(line["book_id"] == book.id for line in get_lines)
