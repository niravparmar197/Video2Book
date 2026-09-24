import json
from types import SimpleNamespace

from bullmq import Job, Queue

import api.routers.outline as outline_module
from api.config import settings
from api.models import Book, Chapter
from api.queue import QUEUE_NAME


def _settings_with_output_root(output_root: str) -> SimpleNamespace:
    return SimpleNamespace(
        database_url=settings.database_url, redis_url=settings.redis_url, output_root=output_root
    )


def _make_book_with_chapters(db_session, status: str, user_id: str) -> Book:
    book = Book(url="https://youtu.be/playlist", status=status, user_id=user_id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    db_session.add_all(
        [
            Chapter(
                book_id=book.id,
                ai_llm_chapter_id="chapter:vid2",
                title="Second",
                order_index=2,
                skip=False,
                locked=False,
                source_video_ids=json.dumps(["vid2"]),
            ),
            Chapter(
                book_id=book.id,
                ai_llm_chapter_id="chapter:vid1",
                title="First",
                order_index=1,
                skip=False,
                locked=False,
                source_video_ids=json.dumps(["vid1"]),
            ),
        ]
    )
    db_session.commit()
    return book


def test_get_outline_404_for_unknown_book(client, auth_headers):
    resp = client.get("/books/does-not-exist/outline", headers=auth_headers)
    assert resp.status_code == 404


def test_get_outline_requires_auth(client, db_session, user):
    book = Book(url="https://youtu.be/x", status="planning", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    resp = client.get(f"/books/{book.id}/outline")
    assert resp.status_code == 401


def test_get_outline_from_another_user_returns_404(client, db_session, user, make_user):
    book = _make_book_with_chapters(db_session, status="outline_ready", user_id=user.id)

    _other_user, _key, other_headers = make_user()
    resp = client.get(f"/books/{book.id}/outline", headers=other_headers)
    assert resp.status_code == 404


def test_get_outline_409_while_not_ready(client, db_session, user, auth_headers):
    book = Book(url="https://youtu.be/x", status="planning", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    resp = client.get(f"/books/{book.id}/outline", headers=auth_headers)
    assert resp.status_code == 409


def test_get_outline_returns_chapters_ordered(client, db_session, user, auth_headers):
    book = _make_book_with_chapters(db_session, status="outline_ready", user_id=user.id)

    resp = client.get(f"/books/{book.id}/outline", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert [c["id"] for c in body] == ["chapter:vid1", "chapter:vid2"]
    assert body[0] == {
        "id": "chapter:vid1",
        "title": "First",
        "order": 1,
        "skip": False,
        "locked": False,
        "source_video_ids": ["vid1"],
    }


def test_put_outline_404_for_unknown_book(client, auth_headers):
    resp = client.put("/books/does-not-exist/outline", json=[], headers=auth_headers)
    assert resp.status_code == 404


def test_put_outline_requires_auth(client, db_session, user):
    book = Book(url="https://youtu.be/x", status="outline_ready", user_id=user.id)
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    resp = client.put(f"/books/{book.id}/outline", json=[])
    assert resp.status_code == 401


def test_put_outline_409_unless_outline_ready(client, db_session, user, auth_headers):
    book = _make_book_with_chapters(db_session, status="planning", user_id=user.id)

    resp = client.put(
        f"/books/{book.id}/outline",
        json=[{"id": "chapter:vid1", "skip": True, "locked": False}],
        headers=auth_headers,
    )
    assert resp.status_code == 409


def test_put_outline_422_for_unknown_chapter_id(client, db_session, user, auth_headers):
    book = _make_book_with_chapters(db_session, status="outline_ready", user_id=user.id)

    resp = client.put(
        f"/books/{book.id}/outline",
        json=[{"id": "chapter:does-not-exist", "skip": True, "locked": False}],
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_put_outline_saves_edits_patches_disk_and_enqueues_render(
    client, db_session, user, auth_headers, tmp_path, monkeypatch
):
    monkeypatch.setattr(outline_module, "settings", _settings_with_output_root(str(tmp_path)))
    book = _make_book_with_chapters(db_session, status="outline_ready", user_id=user.id)

    output_dir = tmp_path / book.id
    output_dir.mkdir(parents=True)
    outline_json = output_dir / "outline.json"
    outline_json.write_text(
        json.dumps(
            [
                {"id": "chapter:vid1", "title": "First", "order": 1, "skip": False, "locked": False},
                {"id": "chapter:vid2", "title": "Second", "order": 2, "skip": False, "locked": False},
            ]
        ),
        encoding="utf-8",
    )

    resp = client.put(
        f"/books/{book.id}/outline",
        json=[{"id": "chapter:vid1", "skip": True, "locked": False}],
        headers=auth_headers,
    )

    assert resp.status_code == 202
    assert resp.json()["id"] == book.id

    db_session.expire_all()
    chapters = {c.ai_llm_chapter_id: c for c in db_session.query(Chapter).filter_by(book_id=book.id)}
    assert chapters["chapter:vid1"].skip is True
    assert chapters["chapter:vid2"].skip is False

    on_disk = json.loads(outline_json.read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in on_disk}
    assert by_id["chapter:vid1"]["skip"] is True
    assert by_id["chapter:vid2"]["skip"] is False


def test_put_outline_from_another_user_returns_404(client, db_session, user, make_user):
    book = _make_book_with_chapters(db_session, status="outline_ready", user_id=user.id)

    _other_user, _key, other_headers = make_user()
    resp = client.put(f"/books/{book.id}/outline", json=[], headers=other_headers)
    assert resp.status_code == 404


async def test_put_outline_enqueues_render_phase(
    client, db_session, user, auth_headers, tmp_path, monkeypatch
):
    monkeypatch.setattr(outline_module, "settings", _settings_with_output_root(str(tmp_path)))
    book = _make_book_with_chapters(db_session, status="outline_ready", user_id=user.id)

    client.put(f"/books/{book.id}/outline", json=[], headers=auth_headers)

    queue = Queue(QUEUE_NAME, {"connection": settings.redis_url})
    try:
        job = await Job.fromId(queue, book.id)
        assert job is not None
        assert job.data["phase"] == "render"
    finally:
        await queue.close()
