import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

from api import storage
from api.models import Book
from api.retention import delete_expired_books, find_expired_books


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


def test_delete_expired_books_removes_s3_object_and_clears_pdf_path(
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

    deleted_count = delete_expired_books()

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


def test_retention_removes_every_file_of_an_expired_book(db_session, user, tmp_path, monkeypatch):
    from dataclasses import replace

    import api.book_deletion as deletion_module
    import api.retention as retention_module

    monkeypatch.setattr(retention_module, "settings", replace(retention_module.settings, pdf_retention_days=30))
    monkeypatch.setattr(deletion_module, "settings", replace(deletion_module.settings, output_root=str(tmp_path / "out")))
    expired = _make_book(db_session, user, tmp_path, age_days=40)
    for name in ("book.epub", "book.md"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    storage.upload_book_files(expired.id, tmp_path)
    local = tmp_path / "out" / expired.id / "work"
    local.mkdir(parents=True)
    (local / "chunk.json").write_text("{}", encoding="utf-8")

    assert retention_module.delete_expired_books() == 1

    for file_format in ("epub", "md"):
        assert not storage.object_exists(storage.book_file_key(expired.id, file_format))
    assert not storage.object_exists(storage.pdf_key(expired.id))
    assert not (tmp_path / "out" / expired.id).exists()
    # Nothing left to remove: not picked up again.
    assert retention_module.find_expired_books(db_session, 30) == []


def test_remove_empty_output_dirs_keeps_recent_and_non_empty_ones(tmp_path):
    import os
    import time

    from api.retention import remove_empty_output_dirs

    old_empty, new_empty, old_full = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    for folder in (old_empty, new_empty, old_full):
        folder.mkdir()
    (old_full / "book.pdf").write_bytes(b"x")
    hours_ago = time.time() - 7200
    for folder in (old_empty, old_full):
        os.utime(folder, (hours_ago, hours_ago))

    assert remove_empty_output_dirs(tmp_path) == 1
    assert not old_empty.exists() and new_empty.exists() and old_full.exists()


def test_remove_orphan_output_dirs_deletes_folders_of_books_that_no_longer_exist(tmp_path):
    import os
    import time

    from api.retention import remove_orphan_output_dirs

    kept, orphan, fresh_orphan = tmp_path / "book-1", tmp_path / "gone-1", tmp_path / "gone-2"
    for folder in (kept, orphan, fresh_orphan):
        (folder / "work").mkdir(parents=True)
    hours_ago = time.time() - 7200
    for folder in (kept, orphan):
        os.utime(folder, (hours_ago, hours_ago))

    assert remove_orphan_output_dirs({"book-1"}, tmp_path) == 1
    assert kept.exists() and not orphan.exists() and fresh_orphan.exists()
