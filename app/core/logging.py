"""Structured logging configuration for NexoBank.

In *development* the output is human-readable (coloured if the terminal
supports it).  In *production* every log record is serialised as a single
JSON line, which log-aggregators (Loki, CloudWatch, Datadog …) can parse and
index without extra configuration.

Usage::

    from app.core.logging import get_logger

    logger = get_logger(__name__)
    logger.info("user.login", extra={"user_id": str(user.id)})

Call ``setup_logging()`` once during application startup (inside the lifespan
handler) before the first request is served.
"""

import logging
import logging.config
import sys
from typing import Any

from app.core.config import settings

# ---------------------------------------------------------------------------
# JSON formatter (production)
# ---------------------------------------------------------------------------


class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import UTC, datetime

        log_object: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Propagate any ``extra`` keys the caller added
        _standard_keys = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "taskName",
        }
        for key, value in record.__dict__.items():
            if key not in _standard_keys:
                log_object[key] = value

        if record.exc_info:
            log_object["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(log_object, default=str)


# ---------------------------------------------------------------------------
# Setup function — call once at startup
# ---------------------------------------------------------------------------


def setup_logging() -> None:
    """Configure the root logger based on the current ``ENVIRONMENT``.

    - ``production``: JSON output to stdout.
    - Any other environment: coloured human-readable output to stdout.
    """
    log_level = logging.DEBUG if not settings.is_production else logging.INFO

    if settings.is_production:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
    else:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    # Replace all existing handlers on the root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Silence noisy third-party loggers in production
    if settings.is_production:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Factory — use this everywhere instead of logging.getLogger directly
# ---------------------------------------------------------------------------


def get_logger(name: str) -> logging.Logger:
    """Return a logger for the given *name* (typically ``__name__``)."""
    return logging.getLogger(name)
