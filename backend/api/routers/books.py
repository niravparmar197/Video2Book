import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from datetime import datetime, time, timezone

from api import storage
from api.ai_llm_bridge import estimate_playlist as ai_llm_estimate_playlist
from api.ai_llm_bridge import VideoUnavailableError
from api.ai_llm_bridge import save_genre as ai_llm_save_genre
from api.ai_llm_bridge import get_chapter_progress as ai_llm_get_chapter_progress
from api.ai_llm_bridge import get_progress as ai_llm_get_progress
from api.ai_llm_bridge import get_warnings as ai_llm_get_warnings
from api.ai_llm_bridge import get_timings as ai_llm_get_timings
from api.ai_llm_bridge import decided_book_kind as ai_llm_decided_book_kind
from api.ai_llm_bridge import load_settings as ai_llm_load_settings
from api.auth import get_current_user
from api.book_deletion import delete_book
from api.checkpointer import get_checkpointer
from api.config import settings
from api.db import SessionLocal, get_db
from api.error_tracking import capture_message_with_context
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


def _check_over_budget(estimates: list) -> None:
    """Raises 422 if a playlist's estimated total duration/cost exceeds
    ai_llm's own MAX_BOOK_HOURS/MAX_BOOK_COST_USD -- sprints/v8. Unlike the
    ai_llm CLI's --force, this API offers no bypass: a shared multi-tenant
    worker pool/rate-limit budget can't be signed away by one user."""
    budget = ai_llm_load_settings()
    total_hours = sum(e.duration_seconds for e in estimates) / 3600
    if total_hours > budget.max_book_hours:
        raise HTTPException(
            status_code=422,
            detail=(
                f"playlist total duration ({total_hours:.2f}h) exceeds "
                f"MAX_BOOK_HOURS ({budget.max_book_hours}h)"
            ),
        )

    total_cost = sum(e.estimated_cost_usd for e in estimates)
    if total_cost > budget.max_book_cost_usd:
        raise HTTPException(
            status_code=422,
            detail=(
                f"playlist estimated cost (${total_cost:.2f}) exceeds "
                f"MAX_BOOK_COST_USD (${budget.max_book_cost_usd:.2f})"
            ),
        )


def _check_daily_spend_alert(db: Session) -> None:
    """Observational only -- never blocks book creation. Sums
    estimated_cost_usd for every book created since UTC midnight today
    (including the one just committed) and captures a warning once that
    total crosses GLOBAL_DAILY_SPEND_ALERT_USD. Can't fire in production
    yet since every real estimated_cost_usd is 0.0 until a paid provider
    exists (sprints/v8)."""
    today_start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    today_total = db.execute(
        select(func.coalesce(func.sum(Book.estimated_cost_usd), 0.0)).where(
            Book.created_at >= today_start
        )
    ).scalar_one()

    if today_total >= settings.global_daily_spend_alert_usd:
        capture_message_with_context(
            f"global daily spend estimate (${today_total:.2f}) has reached "
            f"the GLOBAL_DAILY_SPEND_ALERT_USD threshold "
            f"(${settings.global_daily_spend_alert_usd:.2f})",
            level="warning",
        )


def _check_in_flight_limit(db: Session, user: User) -> None:
    in_flight = db.execute(
        select(func.count())
        .select_from(Book)
        .where(Book.user_id == user.id, Book.status.in_(_IN_FLIGHT_STATUSES))
    ).scalar_one()
    if in_flight >= settings.max_concurrent_books_per_user:
        db.rollback()  # releases the create_book lock, if held
        raise HTTPException(
            status_code=429,
            detail=(
                f"you already have {in_flight} book(s) in progress "
                f"(limit {settings.max_concurrent_books_per_user}) -- "
                "wait for one to finish before starting another"
            ),
        )


@router.post("/youtube", response_model=BookResponse, status_code=201)
async def create_book(
    payload: BookCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Book:
    # Early, cheap refusal -- before the estimate's YouTube round trip.
    _check_in_flight_limit(db, user)

    try:
        estimates = await asyncio.to_thread(ai_llm_estimate_playlist, str(payload.url))
    except VideoUnavailableError as error:
        # A members-only/private/removed video is the user's input problem, not
        # a server fault: say why instead of returning a bare 500.
        raise HTTPException(status_code=422, detail=f"YouTube can't open this video: {error}")
    _check_over_budget(estimates)
    total_cost = sum(e.estimated_cost_usd for e in estimates)

    # The binding check: a per-user lock held until this transaction commits,
    # so concurrent requests from one user count one at a time. Without it, a
    # load test's 4 simultaneous requests each counted 0 in flight and all 4
    # books were created past a limit of 3.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"create_book:{user.id}"})
    _check_in_flight_limit(db, user)
    book = Book(
        url=str(payload.url), status="queued", user_id=user.id, estimated_cost_usd=total_cost
    )
    db.add(book)
    db.commit()
    db.refresh(book)

    if payload.genre != "auto":
        ai_llm_save_genre(Path(settings.output_root) / book.id, payload.genre)

    _check_daily_spend_alert(db)

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


_LIST_LIMIT_MAX = 200


@router.get("", response_model=list[BookResponse])
async def list_books(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Book]:
    """The user's books, newest first. The web app used to keep this list in
    the browser only, so another device (or cleared site data) lost it."""
    limit = max(1, min(limit, _LIST_LIMIT_MAX))
    return list(
        db.execute(
            select(Book)
            .where(Book.user_id == user.id)
            .order_by(Book.created_at.desc())
            .limit(limit)
            .offset(max(0, offset))
        ).scalars()
    )


@router.delete("/{book_id}", status_code=204)
async def delete_book_endpoint(
    book_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Response:
    """Delete a book and everything stored for it (S3 files, local folder,
    checkpoints). A book the worker is making right now must be cancelled
    first."""
    book = get_owned_book(db, book_id, user)
    if book.status in ("planning", "rendering"):
        raise HTTPException(
            status_code=409, detail=f"book is '{book.status}' -- cancel it before deleting"
        )
    await delete_book(db, book)
    return Response(status_code=204)


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


@router.get("/{book_id}/download/{file_format}")
async def download_book_file(
    book_id: str,
    file_format: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RedirectResponse:
    """The book as an e-book (epub) or Markdown (md), next to the PDF."""
    book = get_owned_book(db, book_id, user)
    if file_format not in storage.BOOK_FILE_FORMATS:
        raise HTTPException(status_code=404, detail=f"unknown format {file_format!r}")
    key = storage.book_file_key(book_id, file_format)
    if book.status != "done" or not await asyncio.to_thread(storage.object_exists, key):
        raise HTTPException(status_code=404, detail=f"{file_format} not available")
    return RedirectResponse(storage.presigned_url(key), status_code=307)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _progress_events(book_id: str) -> AsyncIterator[str]:
    """Polls the book's status + LangGraph checkpoint every
    `EVENTS_POLL_SECONDS` and yields an SSE `progress` event only when the
    reported node position or any chapter's status changed since the last
    yield -- no-op ticks aren't sent. A chapter finishing while the
    book-wide node position stays put (e.g. chapter 4 of 12 during one long
    `write` node run) now counts as a real change (sprints/v9). Yields one
    final `done`/`failed` event and stops once the book leaves its
    in-flight statuses (sprints/v7 Task 7). Also includes a `warnings`
    array (sprints/v11) -- non-fatal degradations ai_llm logs and
    continues past (e.g. a chunk's topics extraction giving up on a
    malformed LLM response) previously only reached worker stdout, with
    no way for the frontend to know a book's output had quietly degraded.
    """
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

        warnings = await asyncio.to_thread(ai_llm_get_warnings, output_dir)

        if book.status in _TERMINAL_STATUSES:
            event = "done" if book.status == "done" else "failed"
            yield _sse(event, {"status": book.status, "warnings": warnings})
            return

        phase = "plan" if book.status in _PLAN_STATUSES else "render"
        progress = await asyncio.to_thread(
            ai_llm_get_progress, output_dir, checkpointer, None, phase
        )
        chapters = await asyncio.to_thread(ai_llm_get_chapter_progress, output_dir)
        progress["chapters"] = chapters
        progress["warnings"] = warnings
        # The kind of book once decided ("Podcast Notes", ...) and seconds per
        # finished step, so the progress screen can show both.
        progress["book_kind"] = await asyncio.to_thread(ai_llm_decided_book_kind, output_dir)
        progress["step_seconds"] = await asyncio.to_thread(ai_llm_get_timings, output_dir)

        key = (
            progress["current_node"],
            tuple(progress["completed_nodes"]),
            tuple((c["id"], c["status"], c["score"], c["attempts"]) for c in chapters),
            len(warnings),
            progress["book_kind"],
        )
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
