"""Structured logging configuration using structlog.

In production (env != "dev"), logs are emitted as JSON for log collectors
(Loki, ELK, CloudWatch). In dev, logs are colorized for human readability.
"""

import logging
import sys
from typing import Any

import structlog

from api.config import get_settings


def _add_service_name(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Add a static 'service' field to every log entry."""
    event_dict["service"] = "api"
    return event_dict


def configure_logging() -> None:
    """Configure structlog and stdlib logging.

    Called once at application startup, before any log records are emitted.
    """
    settings = get_settings()
    is_dev = settings.environment == "dev"

    # Shared processors: run for every log record, in order.
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_service_name,
        structlog.processors.StackInfoRenderer(),
    ]

    if is_dev:
        # Dev: colorful, human-readable output.
        renderer: Any = structlog.dev.ConsoleRenderer(colors=True)
    else:
        # Prod: JSON output for log collectors.
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging so that uvicorn/third-party logs
    # flow through the same structlog pipeline.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)

    # Align uvicorn access/error loggers with root.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger.

    Usage:
        log = get_logger(__name__)
        log.info("document_uploaded", document_id="...", size_bytes=1234)
    """
    return structlog.get_logger(name)  # type: ignore[return-value]