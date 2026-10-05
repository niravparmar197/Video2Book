"""Remove a book everywhere it is stored: S3 files, the worker's local
output folder, its LangGraph checkpoints and its database rows.

Shared by DELETE /books/{id}, DELETE /users/me and retention, so a book is
never half-deleted (retention used to drop only the PDF and leave the
e-book, the Markdown and the whole local folder behind).
"""

import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from api import storage
from api.config import settings
from api.logging import get_logger
from api.models import Book


def book_output_dir(book_id: str) -> Path:
    return Path(settings.output_root) / book_id


def remove_book_files(book: Book) -> None:
    """S3 objects, local folder and checkpoints -- each best effort, logged:
    one unreachable store must not keep the rest (or the DB row) around."""
    logger = get_logger(book_id=book.id, step="delete")
    output_dir = book_output_dir(book.id)
    try:
        storage.delete_book_files(book.id, book.pdf_path)
    except Exception as error:  # noqa: BLE001
        logger.warning("could not delete S3 files", extra={"error": str(error)})
    shutil.rmtree(output_dir, ignore_errors=True)
    try:
        from api.checkpointer import get_checkpointer

        # graph.py's thread id is the book's output folder.
        get_checkpointer().delete_thread(str(output_dir))
    except Exception as error:  # noqa: BLE001
        logger.warning("could not delete checkpoints", extra={"error": str(error)})


async def delete_book(db: Session, book: Book) -> None:
    """Stop the book's queued job (best effort), remove its files, then the
    row (videos and chapters cascade). Commits."""
    from api.queue import cancel_run_book

    logger = get_logger(book_id=book.id, step="delete")
    try:
        await cancel_run_book(book.id)
    except Exception as error:  # noqa: BLE001 - nothing queued, or Redis down
        logger.info("no queued job removed", extra={"error": str(error)})
    remove_book_files(book)
    db.delete(book)
    db.commit()
    logger.info("book deleted")
