import urllib.request

from api import storage
from api.models import Book


def test_download_pdf_returns_404_for_unknown_book(client, auth_headers):
    resp = client.get("/books/does-not-exist/pdf", headers=auth_headers)
    assert resp.status_code == 404


def test_download_pdf_requires_auth(client, db_session, user):
    book = Book(url="https://youtu.be/x", status="running", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    resp = client.get(f"/books/{book.id}/pdf")
    assert resp.status_code == 401


def test_download_pdf_returns_404_when_not_done(client, db_session, user, auth_headers):
    book = Book(url="https://youtu.be/x", status="running", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    resp = client.get(f"/books/{book.id}/pdf", headers=auth_headers)
    assert resp.status_code == 404


def test_download_pdf_returns_404_when_pdf_path_missing(client, db_session, user, auth_headers):
    book = Book(url="https://youtu.be/x", status="done", pdf_path=None, user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    resp = client.get(f"/books/{book.id}/pdf", headers=auth_headers)
    assert resp.status_code == 404


def test_download_pdf_redirects_to_a_working_presigned_url(
    client, db_session, user, auth_headers, tmp_path
):
    local_pdf = tmp_path / "book.pdf"
    local_pdf.write_bytes(b"%PDF-1.4 fake pdf bytes")

    book = Book(url="https://youtu.be/x", status="queued", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    key = storage.upload_pdf(book.id, local_pdf)
    book.status = "done"
    book.pdf_path = key
    db_session.commit()

    resp = client.get(f"/books/{book.id}/pdf", headers=auth_headers, follow_redirects=False)

    assert resp.status_code == 307
    location = resp.headers["location"]
    assert key in location

    fetched = urllib.request.urlopen(location).read()
    assert fetched == b"%PDF-1.4 fake pdf bytes"


def test_download_pdf_from_another_user_returns_404(
    client, db_session, user, make_user, tmp_path
):
    local_pdf = tmp_path / "book.pdf"
    local_pdf.write_bytes(b"%PDF-1.4 fake pdf bytes")

    book = Book(url="https://youtu.be/x", status="queued", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    key = storage.upload_pdf(book.id, local_pdf)
    book.status = "done"
    book.pdf_path = key
    db_session.commit()

    _other_user, _key, other_headers = make_user()
    resp = client.get(f"/books/{book.id}/pdf", headers=other_headers)
    assert resp.status_code == 404


def test_epub_and_markdown_are_uploaded_with_the_book_and_downloadable(
    client, db_session, user, auth_headers, tmp_path
):
    book = Book(url="https://youtu.be/x", status="done", pdf_path="x/book.pdf", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)
    (tmp_path / "book.epub").write_bytes(b"PK epub bytes")
    (tmp_path / "book.md").write_bytes(b"# My Book\n")

    assert storage.upload_book_files(book.id, tmp_path) == ["epub", "md"]
    try:
        for file_format, expected in (("epub", b"PK epub bytes"), ("md", b"# My Book\n")):
            resp = client.get(f"/books/{book.id}/download/{file_format}", headers=auth_headers, follow_redirects=False)
            assert resp.status_code == 307
            assert urllib.request.urlopen(resp.headers["location"]).read() == expected
    finally:
        for file_format in ("epub", "md"):
            storage._client().delete_object(Bucket=storage.settings.s3_bucket, Key=storage.book_file_key(book.id, file_format))


def test_book_file_download_404s_for_unknown_format_missing_file_or_unfinished_book(
    client, db_session, user, auth_headers
):
    done = Book(url="https://youtu.be/x", status="done", pdf_path="x/book.pdf", user_id=user.id)
    running = Book(url="https://youtu.be/y", status="rendering", user_id=user.id)
    db_session.add_all([done, running])
    db_session.commit()

    assert client.get(f"/books/{done.id}/download/docx", headers=auth_headers).status_code == 404
    assert client.get(f"/books/{done.id}/download/epub", headers=auth_headers).status_code == 404  # never uploaded
    assert client.get(f"/books/{running.id}/download/epub", headers=auth_headers).status_code == 404
