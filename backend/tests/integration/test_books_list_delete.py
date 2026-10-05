from datetime import datetime, timedelta, timezone

import api.book_deletion as deletion_module
from api.models import Book, Chapter


def _book(db_session, user, status="done", age_minutes=0):
    book = Book(
        url="https://youtu.be/x",
        status=status,
        user_id=user.id,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=age_minutes),
    )
    db_session.add(book)
    db_session.commit()
    return book


def test_list_books_returns_only_the_users_books_newest_first(client, make_user, db_session):
    alice, _, alice_headers = make_user()
    bob, _, _ = make_user()
    older = _book(db_session, alice, age_minutes=10)
    newer = _book(db_session, alice, status="failed")
    _book(db_session, bob)

    resp = client.get("/books", headers=alice_headers)

    assert resp.status_code == 200
    assert [book["id"] for book in resp.json()] == [newer.id, older.id]


def test_list_books_pages_and_needs_a_key(client, make_user, db_session):
    user, _, headers = make_user()
    for minutes in range(3):
        _book(db_session, user, age_minutes=minutes)

    assert len(client.get("/books?limit=2", headers=headers).json()) == 2
    assert len(client.get("/books?limit=2&offset=2", headers=headers).json()) == 1
    assert client.get("/books").status_code == 401


def test_delete_book_removes_the_row_and_its_files(client, make_user, db_session, monkeypatch):
    removed = []
    monkeypatch.setattr(deletion_module, "remove_book_files", lambda book: removed.append(book.id))
    user, _, headers = make_user()
    book = _book(db_session, user)
    db_session.add(Chapter(book_id=book.id, ai_llm_chapter_id="c1", title="One", order_index=0))
    db_session.commit()
    book_id = book.id

    resp = client.delete(f"/books/{book_id}", headers=headers)

    assert resp.status_code == 204
    db_session.expire_all()
    assert db_session.get(Book, book_id) is None
    assert db_session.query(Chapter).filter(Chapter.book_id == book_id).count() == 0
    assert removed == [book_id]


def test_delete_book_refuses_a_book_being_made_and_someone_elses(client, make_user, db_session):
    user, _, headers = make_user()
    other, _, _ = make_user()
    running = _book(db_session, user, status="rendering")
    foreign = _book(db_session, other)

    assert client.delete(f"/books/{running.id}", headers=headers).status_code == 409
    assert client.delete(f"/books/{foreign.id}", headers=headers).status_code == 404
