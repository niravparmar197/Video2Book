import io
import json
import logging

from api.logging import JsonFormatter, get_logger


def test_get_logger_emits_json_with_bound_context():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())

    logger = get_logger("test.video2book", book_id="abc123", step="create")
    logger.logger.addHandler(handler)
    logger.logger.setLevel(logging.INFO)
    logger.logger.propagate = False

    logger.info("book created")

    record = json.loads(stream.getvalue().strip())
    assert record["message"] == "book created"
    assert record["level"] == "INFO"
    assert record["book_id"] == "abc123"
    assert record["step"] == "create"
    assert "ts" in record


def test_get_logger_merges_call_site_extra_with_bound_context():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())

    logger = get_logger("test.video2book.extra", book_id="abc123", step="get")
    logger.logger.addHandler(handler)
    logger.logger.setLevel(logging.INFO)
    logger.logger.propagate = False

    logger.info("book status fetched", extra={"status": "done"})

    record = json.loads(stream.getvalue().strip())
    assert record["book_id"] == "abc123"
    assert record["step"] == "get"
    assert record["status"] == "done"
