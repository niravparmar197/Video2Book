import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api import storage
from api.ai_llm_bridge import get_progress as ai_llm_get_progress
from api.auth import get_current_user
from api.checkpointer import get_checkpointer
from api.config import settings
from api.db import SessionLocal, get_db
from api.logging import get_logger
from api.models import Book, User
from api.queue import cancel_run_book, enqueue_run_book
from api.schemas import BookCreateRequest, BookResponse

router = APIRouter(prefix="/books", tags=["books"])

_IN_FLIGHT_STATUSES = ("queued", "planning", "outline_ready", "rendering")
_TERMINAL_STATUSES = ("done", "failed")
_PLAN_STATUSES = ("queued", "planning")


def get_owned_book(db: Session, book_id: str, user: User) -> Book:
    """A book that doesn't exist and one that exists but belongs to
    someone else behave identically: 404, never a distinguishing 403 --
    no existence leak across users."""
    book = db.get(Book, book_id)
    if book is None or book.user_id != user.id:
        raise HTTPException(status_code=404, detail="book not found")
    return book


@router.post("/youtube", response_model=BookResponse, status_code=201)
async def create_book(
    payload: BookCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Book:
    in_flight = db.execute(
        select(func.count())
        .select_from(Book)
        .where(Book.user_id == user.id, Book.status.in_(_IN_FLIGHT_STATUSES))
    ).scalar_one()
    if in_flight >= settings.max_concurrent_books_per_user:
        raise HTTPException(
            status_code=429,
            detail=(
                f"you already have {in_flight} book(s) in progress "
                f"(limit {settings.max_concurrent_books_per_user}) -- "
                "wait for one to finish before starting another"
            ),
        )

    book = Book(url=str(payload.url), status="queued", user_id=user.id)
    db.add(book)
    db.commit()
    db.refresh(book)

    logger = get_logger(book_id=book.id, step="create")
    logger.info("book created")

    await enqueue_run_book(book.id, str(payload.url), phase="plan")
    logger.info("plan phase job enqueued")

    return book


@router.post("/{book_id}/retry", response_model=BookResponse, status_code=202)
async def retry_book(
    book_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Book:
    book = get_owned_book(db, book_id, user)
    if book.status != "failed":
        raise HTTPException(
            status_code=409, detail=f"book is '{book.status}', not 'failed' -- nothing to retry"
        )

    logger = get_logger(book_id=book.id, step="retry")
    await enqueue_run_book(book.id, book.url, phase="retry")
    logger.info("retry phase job enqueued")

    return book


@router.post("/{book_id}/cancel", response_model=BookResponse, status_code=202)
async def cancel_book(
    book_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Book:
    book = get_owned_book(db, book_id, user)
    if book.status not in _IN_FLIGHT_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"book is '{book.status}', not in-flight -- nothing to cancel",
        )

    book.status = "failed"
    book.error_message = "Cancelled by user"
    db.commit()
    db.refresh(book)

    logger = get_logger(book_id=book.id, step="cancel")
    try:
        await cancel_run_book(book.id)
    except Exception as exc:
        # Best-effort queue cleanup (see cancel_run_book's docstring) --
        # the DB status change above is what actually matters here, so a
        # Redis hiccup doesn't fail the whole cancel request.
        logger.warning("could not remove queued job for cancelled book", extra={"error": str(exc)})
    logger.info("book cancelled")

    return book


@router.get("/{book_id}", response_model=BookResponse)
async def get_book(
    book_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Book:
    logger = get_logger(book_id=book_id, step="get")
    book = get_owned_book(db, book_id, user)
    logger.info("book status fetched", extra={"status": book.status})
    return book


@router.get("/{book_id}/pdf")
async def download_pdf(
    book_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> RedirectResponse:
    book = get_owned_book(db, book_id, user)
    if book.status != "done" or not book.pdf_path:
        raise HTTPException(status_code=404, detail="pdf not available")

    url = storage.presigned_url(book.pdf_path)
    return RedirectResponse(url, status_code=307)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _progress_events(book_id: str) -> AsyncIterator[str]:
    """Polls the book's status + LangGraph checkpoint every
    `EVENTS_POLL_SECONDS` and yields an SSE `progress` event only when the
    reported node position changed since the last yield -- no-op ticks
    aren't sent. Yields one final `done`/`failed` event and stops once the
    book leaves its in-flight statuses (sprints/v7 Task 7)."""
    output_dir = Path(settings.output_root) / book_id
    checkpointer = get_checkpointer()
    last_sent = None

    while True:
        db = SessionLocal()
        try:
            book = db.get(Book, book_id)
        finally:
            db.close()

        if book is None:
            return

        if book.status in _TERMINAL_STATUSES:
            event = "done" if book.status == "done" else "failed"
            yield _sse(event, {"status": book.status})
            return

        phase = "plan" if book.status in _PLAN_STATUSES else "render"
        progress = await asyncio.to_thread(
            ai_llm_get_progress, output_dir, checkpointer, None, phase
        )
        key = (progress["current_node"], tuple(progress["completed_nodes"]))
        if key != last_sent:
            last_sent = key
            yield _sse("progress", progress)

        await asyncio.sleep(settings.events_poll_seconds)


@router.get("/{book_id}/events")
async def book_events(
    book_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> StreamingResponse:
    get_owned_book(db, book_id, user)
    return StreamingResponse(_progress_events(book_id), media_type="text/event-stream")
