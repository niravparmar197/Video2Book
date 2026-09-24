import urllib.request
from types import SimpleNamespace

from api.jobs import run_book as run_book_job
from api.jobs.run_book import process_run_book


def _job(book_id: str, url: str, phase: str) -> SimpleNamespace:
    return SimpleNamespace(
        data={"book_id": book_id, "url": url, "phase": phase},
        opts={"attempts": 3},
        attemptsMade=0,
    )


async def test_render_to_s3_then_download_round_trips_bytes(
    client, monkeypatch, db_session, auth_headers, tmp_path
):
    url = "https://www.youtube.com/watch?v=abc123"
    create_resp = client.post("/books/youtube", json={"url": url}, headers=auth_headers)
    book_id = create_resp.json()["id"]

    monkeypatch.setattr(
        run_book_job,
        "ai_llm_run_plan",
        lambda u, output_dir, force, checkpointer: (
            [{"video_id": "abc123", "title": "T", "url": url}],
            [
                {
                    "id": "chapter:abc123",
                    "video_id": "abc123",
                    "title": "T",
                    "order": 1,
                    "skip": False,
                    "locked": False,
                }
            ],
        ),
    )
    await process_run_book(_job(book_id, url, phase="plan"))
    assert client.get(f"/books/{book_id}", headers=auth_headers).json()["status"] == "outline_ready"

    rendered_bytes = b"%PDF-1.4 the actual rendered book"
    fake_pdf = tmp_path / book_id / "book.pdf"
    fake_pdf.parent.mkdir(parents=True)
    fake_pdf.write_bytes(rendered_bytes)
    monkeypatch.setattr(
        run_book_job, "ai_llm_run_book", lambda u, output_dir, force, checkpointer: fake_pdf
    )

    await process_run_book(_job(book_id, url, phase="render"))

    status = client.get(f"/books/{book_id}", headers=auth_headers).json()
    assert status["status"] == "done"
    assert status["pdf_path"] == f"{book_id}/book.pdf"

    download = client.get(f"/books/{book_id}/pdf", headers=auth_headers, follow_redirects=False)
    assert download.status_code == 307

    fetched = urllib.request.urlopen(download.headers["location"]).read()
    assert fetched == rendered_bytes
