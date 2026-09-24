import urllib.request
import uuid

from api import storage


def test_upload_pdf_then_presigned_url_round_trips_bytes(tmp_path):
    book_id = f"test-{uuid.uuid4()}"
    local_pdf = tmp_path / "book.pdf"
    local_pdf.write_bytes(b"%PDF-1.4 test bytes")

    key = storage.upload_pdf(book_id, local_pdf)

    assert key == f"{book_id}/book.pdf"

    url = storage.presigned_url(key, expires_in=60)
    fetched = urllib.request.urlopen(url).read()
    assert fetched == b"%PDF-1.4 test bytes"


def test_delete_pdf_removes_the_object(tmp_path):
    book_id = f"test-{uuid.uuid4()}"
    local_pdf = tmp_path / "book.pdf"
    local_pdf.write_bytes(b"%PDF-1.4 to be deleted")

    key = storage.upload_pdf(book_id, local_pdf)
    storage.delete_pdf(key)

    url = storage.presigned_url(key, expires_in=60)
    try:
        urllib.request.urlopen(url)
        assert False, "expected the object to be gone"
    except urllib.error.HTTPError as exc:
        assert exc.code == 404


def test_check_s3_true_when_reachable():
    assert storage.check_s3() is True


def test_check_s3_false_when_unreachable(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        storage,
        "settings",
        SimpleNamespace(
            s3_endpoint_url="http://localhost:59999",
            s3_access_key="test",
            s3_secret_key="test",
            s3_region="us-east-1",
            s3_bucket="video2book-books",
        ),
    )
    assert storage.check_s3() is False
