"""S3 (or an S3-compatible service, e.g. the local S3Mock container)
storage for rendered PDFs. `Book.pdf_path` holds the object key this
module returns, not a local filesystem path, once a render succeeds.
"""

from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from api.config import settings

_BUCKET_ALREADY_EXISTS_CODES = {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        # Explicit timeouts *and* a capped retry count -- boto3's default
        # retry policy re-attempts a failed connect several times with
        # backoff, so even a 2s connect_timeout can add up to a minute-plus
        # hang against an unreachable host without this (see sprints/v2
        # Task 4's psycopg connect_timeout fix for the same class of issue).
        config=Config(
            signature_version="s3v4",
            connect_timeout=2,
            # read_timeout bounds a silent wait for the server, not the whole
            # upload, but a large (tens of MB) PDF needs more than 5s of slack.
            read_timeout=60,
            retries={"max_attempts": 2},
            # boto3 >= 1.36 adds a CRC32 checksum to every upload part by
            # default; S3Mock then rejects CompleteMultipartUpload ("The
            # complete request must include the checksum for each part") for
            # any PDF over the 8MB multipart threshold -- which is every book
            # with a few dozen screenshots, and every long-video book. Only
            # send checksums when an operation requires them.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def _ensure_bucket(client) -> None:
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        try:
            client.create_bucket(Bucket=settings.s3_bucket)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in _BUCKET_ALREADY_EXISTS_CODES:
                raise


def pdf_key(book_id: str) -> str:
    return f"{book_id}/book.pdf"


def upload_pdf(book_id: str, local_path: str | Path) -> str:
    """Uploads `local_path` to S3 and returns the object key."""
    client = _client()
    _ensure_bucket(client)
    key = pdf_key(book_id)
    client.upload_file(str(local_path), settings.s3_bucket, key)
    return key


# Extra book formats ai_llm writes next to book.pdf, by download name.
BOOK_FILE_FORMATS = {"epub": "book.epub", "md": "book.md"}


def book_file_key(book_id: str, file_format: str) -> str:
    return f"{book_id}/{BOOK_FILE_FORMATS[file_format]}"


def upload_book_files(book_id: str, output_dir: str | Path) -> list[str]:
    """Upload whichever extra formats (book.epub, book.md) exist in the
    book's output folder; returns the formats uploaded."""
    client = _client()
    _ensure_bucket(client)
    uploaded = []
    for file_format, name in BOOK_FILE_FORMATS.items():
        path = Path(output_dir) / name
        if path.exists():
            client.upload_file(str(path), settings.s3_bucket, book_file_key(book_id, file_format))
            uploaded.append(file_format)
    return uploaded


def object_exists(key: str) -> bool:
    try:
        _client().head_object(Bucket=settings.s3_bucket, Key=key)
        return True
    except ClientError:
        return False


def presigned_url(key: str, expires_in: int = 900) -> str:
    client = _client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=expires_in,
    )


def delete_pdf(key: str) -> None:
    client = _client()
    client.delete_object(Bucket=settings.s3_bucket, Key=key)


def check_s3() -> bool:
    try:
        _client().list_buckets()
        return True
    except Exception:
        return False
