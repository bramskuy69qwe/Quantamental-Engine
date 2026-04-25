"""
JSON log formatter for RotatingFileHandler.

Produces newline-delimited JSON (one object per line) compatible with
log aggregators (Grafana Loki, jq, etc.).

Usage in main.py:
    from logging.handlers import RotatingFileHandler
    from core.log_formatter import JsonFormatter

    handler = RotatingFileHandler(config.LOG_FILE, maxBytes=10*1024*1024, backupCount=5)
    handler.setFormatter(JsonFormatter())
    logging.getLogger().addHandler(handler)
"""
from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        obj: dict = {
            "ts":      datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level":   record.levelname,
            "logger":  record.name,
            "message": record.getMessage(),
        }

        # Include exception info if present
        if record.exc_info:
            obj["exc_info"] = self.formatException(record.exc_info)
        elif record.exc_text:
            obj["exc_info"] = record.exc_text

        # Include any extra fields attached via logger.extra or structlog-style dicts
        # (Fields that are not standard LogRecord attributes)
        _standard = {
            "name", "msg", "args", "created", "filename", "funcName",
            "levelname", "levelno", "lineno", "module", "msecs",
            "pathname", "process", "processName", "relativeCreated",
            "thread", "threadName", "exc_info", "exc_text", "stack_info",
            "message", "taskName",
        }
        for key, val in record.__dict__.items():
            if key not in _standard and not key.startswith("_"):
                try:
                    json.dumps(val)   # only include JSON-serialisable extras
                    obj[key] = val
                except (TypeError, ValueError):
                    obj[key] = str(val)

        return json.dumps(obj, ensure_ascii=False)
