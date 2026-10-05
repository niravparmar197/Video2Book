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


def test_delete_object_removes_the_object(tmp_path):
    book_id = f"test-{uuid.uuid4()}"
    local_pdf = tmp_path / "book.pdf"
    local_pdf.write_bytes(b"%PDF-1.4 to be deleted")

    key = storage.upload_pdf(book_id, local_pdf)
    storage.delete_object(key)

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


def test_a_pdf_over_the_multipart_threshold_uploads_with_s3mock(tmp_path):
    # >8MB makes boto3 use multipart; with its default per-part CRC32 checksums
    # S3Mock rejected CompleteMultipartUpload and the finished book failed to
    # upload. Any book with dozens of screenshots (or a long video) is this big.
    import os

    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-1.5\n" + os.urandom(12 * 1024 * 1024))

    key = storage.upload_pdf("multipart-regression", big)
    try:
        head = storage._client().head_object(Bucket=storage.settings.s3_bucket, Key=key)
        assert head["ContentLength"] == big.stat().st_size
    finally:
        storage.delete_object(key)
