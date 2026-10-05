"""Retention: remove the files of books older than `PDF_RETENTION_DAYS`.

For each finished (done/failed) book last updated before the cutoff, every
stored file goes -- the PDF, book.epub and book.md in S3, the worker's
local output folder and the LangGraph checkpoints -- and `Book.pdf_path`
is cleared. The row stays, so the user still sees the book (without a
download). Run daily by the worker (api.worker's housekeeping loop); also
`python -m api.retention` by hand.
"""

import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.book_deletion import book_output_dir, remove_book_files
from api.config import settings
from api.db import SessionLocal
from api.logging import get_logger
from api.models import Book

_FINISHED_STATUSES = ("done", "failed")
# An empty folder this old is a leftover (a job that never wrote anything),
# not one a job is about to fill.
_EMPTY_DIR_MIN_AGE_SECONDS = 3600


def find_expired_books(
    db: Session, retention_days: int, now: datetime | None = None
) -> list[Book]:
    """Finished books past the window that still have files to remove."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)
    candidates = db.execute(
        select(Book).where(Book.status.in_(_FINISHED_STATUSES), Book.updated_at < cutoff)
    ).scalars()
    return [book for book in candidates if book.pdf_path or book_output_dir(book.id).exists()]


def delete_expired_books() -> int:
    db = SessionLocal()
    try:
        expired = find_expired_books(db, settings.pdf_retention_days)
        for book in expired:
            remove_book_files(book)
            book.pdf_path = None
        db.commit()
        return len(expired)
    finally:
        db.close()


def remove_empty_output_dirs(output_root: str | Path | None = None, now: float | None = None) -> int:
    """Delete empty book folders under OUTPUT_ROOT older than an hour (884
    of them had piled up in a dev checkout)."""
    root = Path(output_root or settings.output_root)
    if not root.is_dir():
        return 0
    now = now if now is not None else time.time()
    removed = 0
    for folder in root.iterdir():
        try:
            if (
                folder.is_dir()
                and not any(folder.iterdir())
                and now - folder.stat().st_mtime > _EMPTY_DIR_MIN_AGE_SECONDS
            ):
                folder.rmdir()
                removed += 1
        except OSError:
            continue
    return removed


def remove_orphan_output_dirs(
    known_book_ids: set[str], output_root: str | Path | None = None, now: float | None = None
) -> int:
    """Delete book folders whose book no longer exists (deleted while its
    job was still running, which then wrote to the folder again), once they
    are an hour old."""
    root = Path(output_root or settings.output_root)
    if not root.is_dir():
        return 0
    now = now if now is not None else time.time()
    removed = 0
    for folder in root.iterdir():
        try:
            if (
                folder.is_dir()
                and folder.name not in known_book_ids
                and now - folder.stat().st_mtime > _EMPTY_DIR_MIN_AGE_SECONDS
            ):
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def run_retention() -> dict:
    deleted = delete_expired_books()
    empty = remove_empty_output_dirs()
    db = SessionLocal()
    try:
        known = set(db.execute(select(Book.id)).scalars())
    finally:
        db.close()
    orphans = remove_orphan_output_dirs(known)
    get_logger(step="retention").info(
        "retention done",
        extra={"books_cleared": deleted, "empty_dirs_removed": empty, "orphan_dirs_removed": orphans},
    )
    return {"books_cleared": deleted, "empty_dirs_removed": empty, "orphan_dirs_removed": orphans}


if __name__ == "__main__":
    result = run_retention()
    print(
        f"Cleared files of {result['books_cleared']} book(s) older than "
        f"{settings.pdf_retention_days} day(s); removed {result['empty_dirs_removed']} empty and "
        f"{result['orphan_dirs_removed']} orphan folder(s)."
    )
