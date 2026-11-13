"""Structured logging utilities for the Sukuna platform.

Provides a JSON formatter for production use and a request_id filter
that pulls the current request ID from thread-local storage.
"""

import json
import logging
import traceback
from datetime import datetime, timezone


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects.

    Output fields: timestamp, level, logger, message, request_id, user_id, extra.
    """

    def format(self, record: logging.LogRecord) -> str:
        from apps.compliance.log_filters import redact, redact_value

        log_entry: dict = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": getattr(record, "request_id", None),
            "user_id": getattr(record, "user_id", None),
        }

        # Collect any extra fields passed via `extra={}` kwarg
        standard_attrs = logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
        extra = {
            k: v
            for k, v in record.__dict__.items()
            if k not in standard_attrs and k not in ("request_id", "user_id", "message")
        }
        if extra:
            log_entry["extra"] = redact_value(extra)

        if record.exc_info and record.exc_info[1] is not None:
            tb_lines = traceback.format_exception(*record.exc_info)
            log_entry["exception"] = [redact(line) for line in tb_lines]

        return json.dumps(log_entry, default=str)


class RequestIdFilter(logging.Filter):
    """Injects request_id and user_id from thread-local storage into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        from config.middleware.request_id import get_request_id, get_user_id

        record.request_id = get_request_id()
        record.user_id = get_user_id()
        return True
