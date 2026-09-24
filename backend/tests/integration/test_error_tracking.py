from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import api.main as main_module
import api.routers.books as books_module


def test_unhandled_exception_returns_500_logs_and_captures_to_sentry(
    auth_headers, log_stream, monkeypatch
):
    def _boom(db, book_id, user):
        raise RuntimeError("something truly unexpected")

    monkeypatch.setattr(books_module, "get_owned_book", _boom)

    capture_mock = MagicMock()
    monkeypatch.setattr(main_module, "capture_exception_with_context", capture_mock)

    # Our handler *does* still run with the default TestClient (the log
    # assertion below would already prove that) -- but Starlette's
    # TestClient additionally re-raises any exception that reached
    # ServerErrorMiddleware (i.e. wasn't an HTTPException) unless told
    # not to, specifically so real bugs aren't silently swallowed in
    # tests. This test's whole point is to assert the *handled* 500
    # response, so it opts out of that re-raise deliberately.
    local_client = TestClient(main_module.app, raise_server_exceptions=False)
    resp = local_client.get("/books/some-id", headers=auth_headers)

    assert resp.status_code == 500
    assert resp.json() == {"detail": "internal server error"}

    capture_mock.assert_called_once()
    args, kwargs = capture_mock.call_args
    assert isinstance(args[0], RuntimeError)
    assert kwargs["path"] == "/books/some-id"

    from tests.conftest import parse_log_lines

    lines = parse_log_lines(log_stream)
    error_lines = [line for line in lines if line.get("step") == "unhandled_exception"]
    assert error_lines, f"no unhandled_exception log line among {lines}"
    assert error_lines[0]["level"] == "ERROR"
