import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import select

from api import storage
from api.config import settings
from api.jobs import run_book as run_book_job
from api.jobs.run_book import _is_final_attempt, _source_video_ids, process_run_book
from api.models import Book, Chapter, Video
from tests.conftest import parse_log_lines


def _fake_job(
    book_id: str, url: str, attempts_made: int, attempts: int, phase: str = "render"
) -> SimpleNamespace:
    return SimpleNamespace(
        data={"book_id": book_id, "url": url, "phase": phase},
        opts={"attempts": attempts},
        attemptsMade=attempts_made,
    )


def _write_fake_pdf(tmp_path: Path, book_id: str, content: bytes = b"%PDF-1.4 fake") -> Path:
    """A real file on disk -- `_finalize_pdf` uploads it to (real) S3Mock
    via `storage.upload_pdf`, which needs an actual file to read."""
    path = tmp_path / book_id / "book.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.mark.parametrize(
    "attempts_made,attempts,expected",
    [
        (0, 1, True),  # single-attempt job, first failure is final
        (0, 3, False),  # first of 3 attempts, retries remain
        (1, 3, False),  # second of 3 attempts, one retry remains
        (2, 3, True),  # third of 3 attempts, no retries remain
    ],
)
def test_is_final_attempt(attempts_made, attempts, expected):
    job = _fake_job("book-1", "https://youtu.be/x", attempts_made, attempts)
    assert _is_final_attempt(job) is expected


@pytest.mark.parametrize(
    "chapter,expected",
    [
        ({"video_id": "vid1"}, ["vid1"]),
        ({"sources": [{"video_id": "vid2"}, {"video_id": "vid1"}]}, ["vid1", "vid2"]),
        ({"sources": [{"video_id": "vid1"}, {"video_id": "vid1"}]}, ["vid1"]),
    ],
)
def test_source_video_ids(chapter, expected):
    assert _source_video_ids(chapter) == expected


async def test_process_run_book_render_success_marks_done(monkeypatch, db_session, user, tmp_path):
    book = Book(url="https://youtu.be/x", status="outline_ready", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    fake_pdf = _write_fake_pdf(tmp_path, book.id, b"%PDF-1.4 render success")
    monkeypatch.setattr(
        run_book_job, "ai_llm_run_book", lambda url, output_dir, force, checkpointer: fake_pdf
    )

    job = _fake_job(book.id, "https://youtu.be/x", attempts_made=0, attempts=3, phase="render")
    result = await process_run_book(job)

    expected_key = f"{book.id}/book.pdf"
    assert result == {"pdf_path": expected_key}
    db_session.refresh(book)
    assert book.status == "done"
    assert book.pdf_path == expected_key
    assert not fake_pdf.exists()  # local copy deleted after upload

    url = storage.presigned_url(expected_key, expires_in=60)
    import urllib.request

    assert urllib.request.urlopen(url).read() == b"%PDF-1.4 render success"


async def test_process_run_book_final_attempt_marks_failed(monkeypatch, db_session, user):
    book = Book(url="https://youtu.be/x", status="outline_ready", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    def _boom(url, output_dir, force, checkpointer):
        raise RuntimeError("NVIDIA and Gemini both failed")

    monkeypatch.setattr(run_book_job, "ai_llm_run_book", _boom)

    job = _fake_job(book.id, "https://youtu.be/x", attempts_made=2, attempts=3, phase="render")
    with pytest.raises(RuntimeError):
        await process_run_book(job)

    db_session.refresh(book)
    assert book.status == "failed"
    assert book.error_message == "NVIDIA and Gemini both failed"


async def test_process_run_book_non_final_attempt_stays_in_running_status(
    monkeypatch, db_session, user
):
    book = Book(url="https://youtu.be/x", status="outline_ready", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    def _boom(url, output_dir, force, checkpointer):
        raise RuntimeError("transient rate limit")

    monkeypatch.setattr(run_book_job, "ai_llm_run_book", _boom)

    job = _fake_job(book.id, "https://youtu.be/x", attempts_made=0, attempts=3, phase="render")
    with pytest.raises(RuntimeError):
        await process_run_book(job)

    db_session.refresh(book)
    assert book.status == "rendering"
    assert book.error_message is None


async def test_process_run_book_final_attempt_captures_to_sentry(monkeypatch, db_session, user):
    from unittest.mock import MagicMock

    book = Book(url="https://youtu.be/x", status="outline_ready", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    def _boom(url, output_dir, force, checkpointer):
        raise RuntimeError("NVIDIA and Gemini both failed")

    monkeypatch.setattr(run_book_job, "ai_llm_run_book", _boom)
    capture_mock = MagicMock()
    monkeypatch.setattr(run_book_job, "capture_exception_with_context", capture_mock)

    job = _fake_job(book.id, "https://youtu.be/x", attempts_made=2, attempts=3, phase="render")
    with pytest.raises(RuntimeError):
        await process_run_book(job)

    capture_mock.assert_called_once()
    args, kwargs = capture_mock.call_args
    assert isinstance(args[0], RuntimeError)
    assert kwargs == {"book_id": book.id, "phase": "render"}


async def test_process_run_book_non_final_attempt_does_not_capture_to_sentry(
    monkeypatch, db_session, user
):
    from unittest.mock import MagicMock

    book = Book(url="https://youtu.be/x", status="outline_ready", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    def _boom(url, output_dir, force, checkpointer):
        raise RuntimeError("transient rate limit")

    monkeypatch.setattr(run_book_job, "ai_llm_run_book", _boom)
    capture_mock = MagicMock()
    monkeypatch.setattr(run_book_job, "capture_exception_with_context", capture_mock)

    job = _fake_job(book.id, "https://youtu.be/x", attempts_made=0, attempts=3, phase="render")
    with pytest.raises(RuntimeError):
        await process_run_book(job)

    capture_mock.assert_not_called()


async def test_process_run_book_logs_status_transitions(
    monkeypatch, db_session, log_stream, user, tmp_path
):
    book = Book(url="https://youtu.be/x", status="outline_ready", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    fake_pdf = _write_fake_pdf(tmp_path, book.id)
    monkeypatch.setattr(
        run_book_job, "ai_llm_run_book", lambda url, output_dir, force, checkpointer: fake_pdf
    )

    job = _fake_job(book.id, "https://youtu.be/x", attempts_made=0, attempts=3, phase="render")
    await process_run_book(job)

    lines = [line for line in parse_log_lines(log_stream) if line.get("book_id") == book.id]
    statuses = [line["status"] for line in lines if "status" in line]
    assert statuses == ["rendering", "done"]
    assert all(line["step"] == "run_book:render" for line in lines)


async def test_process_run_book_failure_log_has_no_secrets(monkeypatch, db_session, log_stream, user):
    book = Book(url="https://youtu.be/x", status="outline_ready", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    def _boom(url, output_dir, force, checkpointer):
        raise RuntimeError("NVIDIA and Gemini both failed")

    monkeypatch.setattr(run_book_job, "ai_llm_run_book", _boom)

    job = _fake_job(book.id, "https://youtu.be/x", attempts_made=2, attempts=3, phase="render")
    with pytest.raises(RuntimeError):
        await process_run_book(job)

    raw = log_stream.getvalue()
    assert "NVIDIA and Gemini both failed" in raw
    assert settings.database_url not in raw
    assert settings.redis_url not in raw


async def test_process_run_book_plan_success_marks_outline_ready(monkeypatch, db_session, user):
    book = Book(url="https://youtu.be/playlist", status="queued", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    fake_videos = [
        {"video_id": "vid1", "title": "First", "url": "https://youtu.be/vid1", "duration_seconds": 100},
        {"video_id": "vid2", "title": "Second", "url": "https://youtu.be/vid2", "duration_seconds": 200},
    ]
    fake_chapters = [
        {"id": "chapter:vid1", "video_id": "vid1", "title": "First", "order": 1, "skip": False, "locked": False},
        {"id": "chapter:vid2", "video_id": "vid2", "title": "Second", "order": 2, "skip": False, "locked": False},
    ]
    monkeypatch.setattr(
        run_book_job,
        "ai_llm_run_plan",
        lambda url, output_dir, force, checkpointer: (fake_videos, fake_chapters),
    )

    job = _fake_job(book.id, "https://youtu.be/playlist", attempts_made=0, attempts=3, phase="plan")
    result = await process_run_book(job)

    assert result == {"chapters": 2}
    db_session.refresh(book)
    assert book.status == "outline_ready"

    videos = db_session.execute(select(Video).where(Video.book_id == book.id)).scalars().all()
    assert {v.video_id for v in videos} == {"vid1", "vid2"}

    chapters = (
        db_session.execute(select(Chapter).where(Chapter.book_id == book.id)).scalars().all()
    )
    assert {c.ai_llm_chapter_id for c in chapters} == {"chapter:vid1", "chapter:vid2"}
    by_id = {c.ai_llm_chapter_id: c for c in chapters}
    assert by_id["chapter:vid1"].order_index == 1
    assert json.loads(by_id["chapter:vid1"].source_video_ids) == ["vid1"]


async def test_process_run_book_plan_upsert_is_idempotent_on_rerun(monkeypatch, db_session, user):
    book = Book(url="https://youtu.be/playlist", status="queued", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    fake_videos = [{"video_id": "vid1", "title": "First", "url": "https://youtu.be/vid1"}]
    fake_chapters = [
        {"id": "chapter:vid1", "video_id": "vid1", "title": "First", "order": 1, "skip": True, "locked": False}
    ]
    monkeypatch.setattr(
        run_book_job,
        "ai_llm_run_plan",
        lambda url, output_dir, force, checkpointer: (fake_videos, fake_chapters),
    )

    job = _fake_job(book.id, "https://youtu.be/playlist", attempts_made=0, attempts=3, phase="plan")
    await process_run_book(job)
    await process_run_book(job)

    videos = db_session.execute(select(Video).where(Video.book_id == book.id)).scalars().all()
    chapters = (
        db_session.execute(select(Chapter).where(Chapter.book_id == book.id)).scalars().all()
    )
    assert len(videos) == 1
    assert len(chapters) == 1
    assert chapters[0].skip is True


async def test_process_run_book_render_passes_the_shared_postgres_checkpointer(
    monkeypatch, db_session, user, tmp_path
):
    book = Book(url="https://youtu.be/x", status="outline_ready", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    fake_pdf = _write_fake_pdf(tmp_path, book.id)
    captured = {}

    def fake_run_book(url, output_dir, force, checkpointer):
        captured["checkpointer"] = checkpointer
        return fake_pdf

    monkeypatch.setattr(run_book_job, "ai_llm_run_book", fake_run_book)

    job = _fake_job(book.id, "https://youtu.be/x", attempts_made=0, attempts=3, phase="render")
    await process_run_book(job)

    assert isinstance(captured["checkpointer"], PostgresSaver)


async def test_process_run_book_plan_passes_the_shared_postgres_checkpointer(
    monkeypatch, db_session, user
):
    book = Book(url="https://youtu.be/playlist", status="queued", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    captured = {}

    def fake_run_plan(url, output_dir, force, checkpointer):
        captured["checkpointer"] = checkpointer
        return [], []

    monkeypatch.setattr(run_book_job, "ai_llm_run_plan", fake_run_plan)

    job = _fake_job(book.id, "https://youtu.be/playlist", attempts_made=0, attempts=3, phase="plan")
    await process_run_book(job)

    assert isinstance(captured["checkpointer"], PostgresSaver)


async def test_process_run_book_retry_passes_the_shared_postgres_checkpointer(
    monkeypatch, db_session, user, tmp_path
):
    book = Book(url="https://youtu.be/x", status="failed", error_message="boom", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    fake_pdf = _write_fake_pdf(tmp_path, book.id)
    captured = {}

    def fake_resume_book(output_dir, checkpointer):
        captured["checkpointer"] = checkpointer
        return fake_pdf

    monkeypatch.setattr(run_book_job, "ai_llm_resume_book", fake_resume_book)

    job = _fake_job(book.id, "https://youtu.be/x", attempts_made=0, attempts=3, phase="retry")
    await process_run_book(job)

    assert isinstance(captured["checkpointer"], PostgresSaver)


async def test_process_run_book_retry_calls_resume_book(monkeypatch, db_session, user, tmp_path):
    book = Book(url="https://youtu.be/x", status="failed", error_message="boom", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    fake_pdf = _write_fake_pdf(tmp_path, book.id, b"%PDF-1.4 retry success")
    calls = []

    def fake_resume_book(output_dir, checkpointer):
        calls.append(output_dir)
        return fake_pdf

    monkeypatch.setattr(run_book_job, "ai_llm_resume_book", fake_resume_book)

    job = _fake_job(book.id, "https://youtu.be/x", attempts_made=0, attempts=3, phase="retry")
    result = await process_run_book(job)

    expected_key = f"{book.id}/book.pdf"
    assert result == {"pdf_path": expected_key}
    assert len(calls) == 1
    db_session.refresh(book)
    assert book.status == "done"
    assert book.pdf_path == expected_key
    assert not fake_pdf.exists()
