"""Error tracking via Sentry -- fully optional.

With `SENTRY_DSN` unset (the default), `init_error_tracking()` never
calls `sentry_sdk.init()`, so no network I/O is ever attempted; every
`capture_exception_with_context()` call is then a safe no-op courtesy of
the SDK's own behavior when no client has been configured.
"""

import sentry_sdk

from api.config import settings


def init_error_tracking() -> None:
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.sentry_environment)


def capture_exception_with_context(exc: BaseException, **context: str) -> None:
    for key, value in context.items():
        sentry_sdk.set_tag(key, value)
    sentry_sdk.capture_exception(exc)


def capture_message_with_context(message: str, level: str = "warning", **context: str) -> None:
    for key, value in context.items():
        sentry_sdk.set_tag(key, value)
    sentry_sdk.capture_message(message, level=level)
