import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

from api import storage
from api.models import Book
from api.retention import delete_expired_pdfs, find_expired_books


def _make_book(db_session, user, tmp_path, *, age_days: int) -> Book:
    # pdf_path and updated_at must both land in the same INSERT: an
    # UPDATE after the fact would trip Book.updated_at's `onupdate=_now`
    # and silently wipe out the aged timestamp this test relies on.
    book_id = str(uuid.uuid4())
    local_pdf = tmp_path / f"{age_days}.pdf"
    local_pdf.write_bytes(b"%PDF-1.4 retention test")
    key = storage.upload_pdf(book_id, local_pdf)

    book = Book(
        id=book_id,
        url="https://youtu.be/x",
        status="done",
        user_id=user.id,
        pdf_path=key,
        updated_at=datetime.now(timezone.utc) - timedelta(days=age_days),
    )
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)
    return book


def test_find_expired_books_only_returns_books_past_the_window(db_session, user, tmp_path):
    expired = _make_book(db_session, user, tmp_path, age_days=40)
    fresh = _make_book(db_session, user, tmp_path, age_days=1)

    results = find_expired_books(db_session, retention_days=30)

    ids = {b.id for b in results}
    assert expired.id in ids
    assert fresh.id not in ids


def test_delete_expired_pdfs_removes_s3_object_and_clears_pdf_path(
    db_session, user, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    import api.retention as retention_module

    monkeypatch.setattr(
        retention_module,
        "settings",
        SimpleNamespace(pdf_retention_days=30),
    )

    expired = _make_book(db_session, user, tmp_path, age_days=40)
    fresh = _make_book(db_session, user, tmp_path, age_days=1)
    expired_key = expired.pdf_path
    fresh_key = fresh.pdf_path

    deleted_count = delete_expired_pdfs()

    assert deleted_count == 1

    db_session.expire_all()
    assert db_session.get(Book, expired.id).pdf_path is None
    assert db_session.get(Book, fresh.id).pdf_path == fresh_key

    expired_url = storage.presigned_url(expired_key, expires_in=60)
    try:
        urllib.request.urlopen(expired_url)
        assert False, "expected the expired object to be gone"
    except urllib.error.HTTPError as exc:
        assert exc.code == 404

    fresh_url = storage.presigned_url(fresh_key, expires_in=60)
    assert urllib.request.urlopen(fresh_url).read() == b"%PDF-1.4 retention test"
