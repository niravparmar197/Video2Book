import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from api import storage
from api.ai_llm_bridge import load_settings as ai_llm_load_settings
from api.ai_llm_bridge import resume_book as ai_llm_resume_book
from api.ai_llm_bridge import run_book as ai_llm_run_book
from api.ai_llm_bridge import run_plan as ai_llm_run_plan
from api.checkpointer import get_checkpointer
from api.config import settings
from api.db import SessionLocal
from api.error_tracking import capture_exception_with_context
from api.logging import get_logger
from api.models import Book, Chapter, Video

LOCK_DURATION_MS = 5 * 60 * 1000  # 5-minute lock, per backend/AGENTS.md queue spec

# Status a book is in *while* a phase's job is running, and the status it
# lands in once that phase succeeds.
_RUNNING_STATUS = {"plan": "planning", "render": "rendering", "retry": "rendering"}
_SUCCESS_STATUS = {"plan": "outline_ready", "render": "done", "retry": "done"}


def _is_final_attempt(job: Any) -> bool:
    """True if BullMQ will not retry `job` after the attempt currently failing.

    Mirrors the same `(attemptsMade + 1) >= attempts` check bullmq's own
    `Job.moveToFailed` uses to decide retry vs. permanent failure, so this
    can be evaluated before that framework call runs.
    """
    attempts_made = getattr(job, "attemptsMade", 0)
    attempts = job.opts.get("attempts", 1)
    return (attempts_made + 1) >= attempts


def _set_status(book_id: str, **fields: Any) -> None:
    db = SessionLocal()
    try:
        book = db.get(Book, book_id)
        if book is None:
            return
        for key, value in fields.items():
            setattr(book, key, value)
        db.commit()
    finally:
        db.close()


def _source_video_ids(chapter: dict) -> list[str]:
    """ai_llm chapters are either single-video (`video_id`) or topic chapters
    merged across sources (`sources: [{video_id, chunk_index}, ...]`)."""
    if "video_id" in chapter:
        return [chapter["video_id"]]
    return sorted({source["video_id"] for source in chapter.get("sources", [])})


def _save_outline(book_id: str, videos: list[dict], chapters: list[dict]) -> None:
    """Upsert Video/Chapter rows from a completed `plan` phase's result."""
    db = SessionLocal()
    try:
        existing_videos = {
            v.video_id: v
            for v in db.execute(select(Video).where(Video.book_id == book_id)).scalars()
        }
        for video in videos:
            row = existing_videos.get(video["video_id"])
            if row is None:
                db.add(
                    Video(
                        book_id=book_id,
                        video_id=video["video_id"],
                        title=video.get("title"),
                        url=video.get("url", ""),
                        duration_seconds=video.get("duration_seconds"),
                    )
                )
            else:
                row.title = video.get("title")
                row.url = video.get("url", row.url)
                row.duration_seconds = video.get("duration_seconds")

        existing_chapters = {
            c.ai_llm_chapter_id: c
            for c in db.execute(select(Chapter).where(Chapter.book_id == book_id)).scalars()
        }
        for chapter in chapters:
            row = existing_chapters.get(chapter["id"])
            source_ids = json.dumps(_source_video_ids(chapter))
            if row is None:
                db.add(
                    Chapter(
                        book_id=book_id,
                        ai_llm_chapter_id=chapter["id"],
                        title=chapter["title"],
                        order_index=chapter["order"],
                        skip=chapter.get("skip", False),
                        locked=chapter.get("locked", False),
                        source_video_ids=source_ids,
                    )
                )
            else:
                row.title = chapter["title"]
                row.order_index = chapter["order"]
                row.skip = chapter.get("skip", False)
                row.locked = chapter.get("locked", False)
                row.source_video_ids = source_ids

        db.commit()
    finally:
        db.close()


def _finalize_pdf(book_id: str, local_pdf_path: Path) -> str:
    """Uploads the rendered PDF to S3 and deletes the local copy -- the
    rest of output/<book_id>/ (checkpoint db, chunk cache, chapter .tex
    files) is left alone since a future retry still needs it. Returns the
    S3 object key, which is what `Book.pdf_path` is set to."""
    key = storage.upload_pdf(book_id, local_pdf_path)
    local_pdf_path.unlink(missing_ok=True)
    return key


async def process_run_book(job: Any, token: str | None = None) -> dict:
    """BullMQ processor for the `run_book` queue.

    Dispatches on `job.data["phase"]`:
    - `plan`: ai_llm's `run_plan` (stops before render); upserts Video/
      Chapter rows from the result so `GET /books/{id}/outline` has
      something to show.
    - `render`: ai_llm's `run_book` (full pipeline) -- called after outline
      review, re-reading any skip/locked edits from outline.json on disk.
    - `retry`: ai_llm's `resume_book` -- resumes a `failed` book from its
      checkpoint; disk-cached steps and already-verified chapters aren't
      redone.

    All three call into ai_llm via `asyncio.to_thread` so the blocking
    LangGraph pipeline never stalls the event loop. On failure, marks the
    Book row `failed` only once BullMQ has exhausted its configured
    retries -- an earlier attempt leaves the book in its running status so
    a retry doesn't get reported as a false failure.
    """
    book_id = job.data["book_id"]
    url = job.data["url"]
    phase = job.data.get("phase", "render")
    output_dir = Path(settings.output_root) / book_id

    # No outline.json yet means the book failed in the plan phase. Resuming
    # the full render graph from that checkpoint never reaches render (the
    # plan graph has no frames node, so render's join never fires) and the
    # retry died with KeyError 'pdf_path' -- such a book could never be
    # retried. Re-run the plan phase instead; finished steps are cached.
    if phase == "retry" and not (output_dir / "outline.json").exists():
        phase = "plan"

    logger = get_logger(book_id=book_id, step=f"run_book:{phase}")

    running_status = _RUNNING_STATUS[phase]
    success_status = _SUCCESS_STATUS[phase]

    _set_status(book_id, status=running_status, error_message=None)
    logger.info("status changed", extra={"status": running_status})

    try:
        if phase == "plan":
            videos, chapters = await asyncio.to_thread(
                ai_llm_run_plan, url, output_dir, False, get_checkpointer()
            )
            _save_outline(book_id, videos, chapters)
            result: dict = {"chapters": len(chapters)}

            # REVIEW_OUTLINE=false (root AGENTS.md setting): skip the human
            # outline-review gate and render right away in this same job,
            # instead of sitting in outline_ready until someone clicks
            # "Save & generate PDF". Inline rather than re-enqueued: this
            # job still holds the book's jobId, so a re-enqueue under the
            # same id would silently no-op -- and inline also skips a trip
            # back through the queue.
            if not ai_llm_load_settings().review_outline:
                success_status = "done"
                _set_status(book_id, status="rendering")
                logger.info(
                    "status changed",
                    extra={"status": "rendering", "reason": "REVIEW_OUTLINE=false"},
                )
                pdf_path = await asyncio.to_thread(
                    ai_llm_run_book, url, output_dir, False, get_checkpointer()
                )
                key = await asyncio.to_thread(_finalize_pdf, book_id, pdf_path)
                _set_status(book_id, pdf_path=key)
                result = {"chapters": len(chapters), "pdf_path": key}
        elif phase == "retry":
            pdf_path = await asyncio.to_thread(ai_llm_resume_book, output_dir, get_checkpointer())
            key = await asyncio.to_thread(_finalize_pdf, book_id, pdf_path)
            _set_status(book_id, pdf_path=key)
            result = {"pdf_path": key}
        else:
            pdf_path = await asyncio.to_thread(
                ai_llm_run_book, url, output_dir, False, get_checkpointer()
            )
            key = await asyncio.to_thread(_finalize_pdf, book_id, pdf_path)
            _set_status(book_id, pdf_path=key)
            result = {"pdf_path": key}
    except Exception as exc:
        if _is_final_attempt(job):
            _set_status(book_id, status="failed", error_message=str(exc))
            logger.error("status changed", extra={"status": "failed", "error": str(exc)})
            capture_exception_with_context(exc, book_id=book_id, phase=phase)
        else:
            attempts_made = getattr(job, "attemptsMade", 0)
            attempts = job.opts.get("attempts", 1)
            logger.warning(
                "attempt failed, will retry",
                extra={"attempt": attempts_made + 1, "attempts": attempts, "error": str(exc)},
            )
        raise

    _set_status(book_id, status=success_status)
    logger.info("status changed", extra={"status": success_status})
    return result
