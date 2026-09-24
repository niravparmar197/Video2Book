from types import SimpleNamespace

from api.jobs import run_book as run_book_job
from api.jobs.run_book import process_run_book


def _job_for(body: dict, attempts_made: int, attempts: int, phase: str) -> SimpleNamespace:
    return SimpleNamespace(
        data={"book_id": body["id"], "url": "https://www.youtube.com/watch?v=abc123", "phase": phase},
        opts={"attempts": attempts},
        attemptsMade=attempts_made,
    )


async def test_create_then_plan_phase_reaches_outline_ready(
    client, monkeypatch, db_session, auth_headers
):
    create_resp = client.post(
        "/books/youtube",
        json={"url": "https://www.youtube.com/watch?v=abc123"},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["status"] == "queued"

    fake_videos = [{"video_id": "abc123", "title": "T", "url": body["id"]}]
    fake_chapters = [
        {"id": "chapter:abc123", "video_id": "abc123", "title": "T", "order": 1, "skip": False, "locked": False}
    ]
    monkeypatch.setattr(
        run_book_job,
        "ai_llm_run_plan",
        lambda url, output_dir, force, checkpointer: (fake_videos, fake_chapters),
    )

    job = _job_for(body, attempts_made=0, attempts=3, phase="plan")
    await process_run_book(job)

    status_resp = client.get(f"/books/{body['id']}", headers=auth_headers)
    assert status_resp.status_code == 200
    final = status_resp.json()
    assert final["status"] == "outline_ready"
    assert final["error_message"] is None

    outline_resp = client.get(f"/books/{body['id']}/outline", headers=auth_headers)
    assert outline_resp.status_code == 200
    assert [c["id"] for c in outline_resp.json()] == ["chapter:abc123"]


async def test_plan_phase_failure_after_final_attempt(client, monkeypatch, auth_headers):
    create_resp = client.post(
        "/books/youtube",
        json={"url": "https://www.youtube.com/watch?v=abc123"},
        headers=auth_headers,
    )
    body = create_resp.json()

    def _boom(url, output_dir, force, checkpointer):
        raise RuntimeError("NVIDIA and Gemini both failed")

    monkeypatch.setattr(run_book_job, "ai_llm_run_plan", _boom)

    job = _job_for(body, attempts_made=2, attempts=3, phase="plan")
    try:
        await process_run_book(job)
    except RuntimeError:
        pass

    status_resp = client.get(f"/books/{body['id']}", headers=auth_headers)
    assert status_resp.status_code == 200
    final = status_resp.json()
    assert final["status"] == "failed"
    assert final["error_message"] == "NVIDIA and Gemini both failed"
    assert final["pdf_path"] is None
