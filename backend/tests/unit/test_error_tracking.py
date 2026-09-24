from types import SimpleNamespace
from unittest.mock import MagicMock

import sentry_sdk

import api.error_tracking as error_tracking


def test_init_error_tracking_skips_sentry_init_when_dsn_unset(monkeypatch):
    monkeypatch.setattr(
        error_tracking,
        "settings",
        SimpleNamespace(sentry_dsn="", sentry_environment="development"),
    )
    init_mock = MagicMock()
    monkeypatch.setattr(sentry_sdk, "init", init_mock)

    error_tracking.init_error_tracking()

    init_mock.assert_not_called()


def test_init_error_tracking_calls_sentry_init_when_dsn_set(monkeypatch):
    monkeypatch.setattr(
        error_tracking,
        "settings",
        SimpleNamespace(sentry_dsn="https://fake@example.com/1", sentry_environment="staging"),
    )
    init_mock = MagicMock()
    monkeypatch.setattr(sentry_sdk, "init", init_mock)

    error_tracking.init_error_tracking()

    init_mock.assert_called_once_with(
        dsn="https://fake@example.com/1", environment="staging"
    )


def test_capture_exception_with_context_sets_tags_then_captures(monkeypatch):
    calls = []
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda k, v: calls.append(("tag", k, v)))
    monkeypatch.setattr(sentry_sdk, "capture_exception", lambda exc: calls.append(("capture", exc)))

    exc = RuntimeError("boom")
    error_tracking.capture_exception_with_context(exc, book_id="abc123", phase="render")

    tag_calls = [c for c in calls if c[0] == "tag"]
    assert ("tag", "book_id", "abc123") in tag_calls
    assert ("tag", "phase", "render") in tag_calls
    assert calls[-1] == ("capture", exc)


def test_capture_exception_with_context_is_safe_without_init():
    # No sentry_sdk.init() call anywhere in this test -- the SDK's own
    # no-client-configured no-op behavior is what's under test here.
    error_tracking.capture_exception_with_context(RuntimeError("never initialized"), book_id="x")
