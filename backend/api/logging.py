"""Structured JSON logging.

`get_logger(book_id=..., step=...)` returns an adapter that stamps every
record with that context, so log lines for a given book/step can be
grep'd/filtered without correlating timestamps by hand. Never pass a
connection string, API key, or other secret as context or message -- only
ids, step/status names, and already-sanitized error text belong here.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ContextLoggerAdapter(logging.LoggerAdapter):
    """A LoggerAdapter whose bound context merges with (rather than
    overwrites) any `extra=` passed at the call site."""

    def process(self, msg: str, kwargs: dict) -> tuple[str, dict]:
        kwargs["extra"] = {**self.extra, **kwargs.get("extra", {})}
        return msg, kwargs


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str = "video2book", **context: Any) -> ContextLoggerAdapter:
    return ContextLoggerAdapter(logging.getLogger(name), context)
