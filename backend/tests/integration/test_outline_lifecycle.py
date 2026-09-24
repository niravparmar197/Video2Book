from types import SimpleNamespace

from api.jobs import run_book as run_book_job
from api.jobs.run_book import process_run_book


def _job(book_id: str, url: str, phase: str) -> SimpleNamespace:
    return SimpleNamespace(
        data={"book_id": book_id, "url": url, "phase": phase},
        opts={"attempts": 3},
        attemptsMade=0,
    )


async def test_full_outline_review_then_render(
    client, monkeypatch, db_session, auth_headers, tmp_path
):
    url = "https://www.youtube.com/watch?v=abc123"
    create_resp = client.post("/books/youtube", json={"url": url}, headers=auth_headers)
    assert create_resp.status_code == 201
    book_id = create_resp.json()["id"]

    fake_videos = [
        {"video_id": "abc123", "title": "Only Video", "url": url, "duration_seconds": 300}
    ]
    fake_chapters = [
        {
            "id": "chapter:abc123",
            "video_id": "abc123",
            "title": "Only Video",
            "order": 1,
            "skip": False,
            "locked": False,
        }
    ]
    monkeypatch.setattr(
        run_book_job,
        "ai_llm_run_plan",
        lambda u, output_dir, force, checkpointer: (fake_videos, fake_chapters),
    )

    await process_run_book(_job(book_id, url, phase="plan"))

    status_resp = client.get(f"/books/{book_id}", headers=auth_headers)
    assert status_resp.json()["status"] == "outline_ready"

    outline_resp = client.get(f"/books/{book_id}/outline", headers=auth_headers)
    assert outline_resp.status_code == 200
    chapters = outline_resp.json()
    assert len(chapters) == 1
    assert chapters[0]["skip"] is False

    put_resp = client.put(
        f"/books/{book_id}/outline",
        json=[{"id": "chapter:abc123", "skip": True, "locked": False}],
        headers=auth_headers,
    )
    assert put_resp.status_code == 202

    outline_after_put = client.get(f"/books/{book_id}/outline", headers=auth_headers).json()
    assert outline_after_put[0]["skip"] is True

    fake_pdf = tmp_path / book_id / "book.pdf"
    fake_pdf.parent.mkdir(parents=True)
    fake_pdf.write_bytes(b"%PDF-1.4 rendered")
    monkeypatch.setattr(
        run_book_job, "ai_llm_run_book", lambda u, output_dir, force, checkpointer: fake_pdf
    )

    await process_run_book(_job(book_id, url, phase="render"))

    final = client.get(f"/books/{book_id}", headers=auth_headers).json()
    assert final["status"] == "done"
    assert final["pdf_path"] == f"{book_id}/book.pdf"

    outline_after_render = client.get(f"/books/{book_id}/outline", headers=auth_headers).json()
    assert outline_after_render[0]["skip"] is True


async def test_failed_book_retry_reaches_done(
    client, monkeypatch, db_session, user, auth_headers, tmp_path
):
    from api.models import Book

    book = Book(
        url="https://youtu.be/x", status="failed", error_message="rate limited", user_id=user.id
    )
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    retry_resp = client.post(f"/books/{book.id}/retry", headers=auth_headers)
    assert retry_resp.status_code == 202

    fake_pdf = tmp_path / book.id / "book.pdf"
    fake_pdf.parent.mkdir(parents=True)
    fake_pdf.write_bytes(b"%PDF-1.4 retried")
    monkeypatch.setattr(run_book_job, "ai_llm_resume_book", lambda output_dir, checkpointer: fake_pdf)

    await process_run_book(_job(book.id, book.url, phase="retry"))

    final = client.get(f"/books/{book.id}", headers=auth_headers).json()
    assert final["status"] == "done"
    assert final["pdf_path"] == f"{book.id}/book.pdf"
    assert final["error_message"] is None  # cleared once the retry starts running
