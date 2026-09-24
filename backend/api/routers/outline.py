import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.config import settings
from api.db import get_db
from api.logging import get_logger
from api.models import Book, Chapter, User
from api.queue import enqueue_run_book
from api.routers.books import get_owned_book
from api.schemas import BookResponse, ChapterEdit, ChapterOut

router = APIRouter(prefix="/books", tags=["outline"])

_OUTLINE_NOT_READY_STATUSES = {"queued", "planning"}


def _chapter_out(chapter: Chapter) -> ChapterOut:
    return ChapterOut(
        id=chapter.ai_llm_chapter_id,
        title=chapter.title,
        order=chapter.order_index,
        skip=chapter.skip,
        locked=chapter.locked,
        source_video_ids=json.loads(chapter.source_video_ids),
    )


def _patch_outline_json(output_dir: Path, updates: dict[str, dict]) -> None:
    """Mirror skip/locked edits into outline.json so ai_llm's outline node
    (`_preserve_flags`) honors them when the render phase re-runs it."""
    if not updates:
        return
    path = output_dir / "outline.json"
    if not path.exists():
        return
    chapters = json.loads(path.read_text(encoding="utf-8"))
    for chapter in chapters:
        update = updates.get(chapter["id"])
        if update is not None:
            chapter["skip"] = update["skip"]
            chapter["locked"] = update["locked"]
    path.write_text(json.dumps(chapters, indent=2, ensure_ascii=False), encoding="utf-8")


@router.get("/{book_id}/outline", response_model=list[ChapterOut])
def get_outline(
    book_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[ChapterOut]:
    book = get_owned_book(db, book_id, user)
    if book.status in _OUTLINE_NOT_READY_STATUSES:
        raise HTTPException(
            status_code=409, detail=f"outline not ready yet (book is '{book.status}')"
        )

    chapters = (
        db.execute(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.order_index))
        .scalars()
        .all()
    )
    return [_chapter_out(c) for c in chapters]


@router.put("/{book_id}/outline", response_model=BookResponse, status_code=202)
async def put_outline(
    book_id: str,
    edits: list[ChapterEdit],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Book:
    book = get_owned_book(db, book_id, user)
    if book.status != "outline_ready":
        raise HTTPException(
            status_code=409,
            detail=f"book is '{book.status}', not 'outline_ready' -- nothing to save",
        )

    chapters_by_id = {
        c.ai_llm_chapter_id: c
        for c in db.execute(select(Chapter).where(Chapter.book_id == book_id)).scalars()
    }
    unknown_ids = [edit.id for edit in edits if edit.id not in chapters_by_id]
    if unknown_ids:
        raise HTTPException(
            status_code=422, detail=f"chapter id(s) not in this book's outline: {unknown_ids}"
        )

    updates: dict[str, dict] = {}
    for edit in edits:
        chapter = chapters_by_id[edit.id]
        chapter.skip = edit.skip
        chapter.locked = edit.locked
        updates[edit.id] = {"skip": edit.skip, "locked": edit.locked}
    db.commit()

    _patch_outline_json(Path(settings.output_root) / book_id, updates)

    logger = get_logger(book_id=book.id, step="outline_save")
    logger.info("outline edits saved", extra={"chapters_edited": len(edits)})

    await enqueue_run_book(book.id, book.url, phase="render")
    logger.info("render phase job enqueued")

    return book
