"""`python -m api.retention` -- deletes S3 objects for books whose PDF has
outlived `PDF_RETENTION_DAYS`, and clears their `Book.pdf_path`.

Not scheduled by this sprint (sprints/v5/PRD.md "Out of Scope") -- an
operator, or a future cron job, runs this by hand.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from api import storage
from api.config import settings
from api.db import SessionLocal
from api.models import Book


def find_expired_books(
    db: Session, retention_days: int, now: datetime | None = None
) -> list[Book]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)
    return list(
        db.execute(
            select(Book).where(Book.pdf_path.is_not(None), Book.updated_at < cutoff)
        ).scalars()
    )


def delete_expired_pdfs() -> int:
    db = SessionLocal()
    try:
        expired = find_expired_books(db, settings.pdf_retention_days)
        for book in expired:
            storage.delete_pdf(book.pdf_path)
            book.pdf_path = None
        db.commit()
        return len(expired)
    finally:
        db.close()


if __name__ == "__main__":
    deleted_count = delete_expired_pdfs()
    print(f"Deleted {deleted_count} expired PDF(s) older than {settings.pdf_retention_days} day(s).")
