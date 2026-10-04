"""Structured logging configuration for the OCR Worker.

In production (env != "dev"), logs are emitted as JSON for log collectors.
In dev, logs are colorized for human readability.
"""

import logging
import sys
from typing import Any

import structlog

from ocr_worker.config import get_settings


SERVICE_NAME = "ocr-worker"


def _add_service_name(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Add a static 'service' field to every log entry."""
    event_dict["service"] = SERVICE_NAME
    return event_dict


def configure_logging() -> None:
    """Configure structlog and stdlib logging.

    Called once at worker startup, before any log records are emitted.
    """
    settings = get_settings()
    is_dev = settings.environment == "dev"

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_service_name,
        structlog.processors.StackInfoRenderer(),
    ]

    if is_dev:
        renderer: Any = structlog.dev.ConsoleRenderer(colors=True)
    else:
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


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger.

    Usage:
        log = get_logger(__name__)
        log.info("document_processed", document_id="...", duration_ms=1234)
    """
    return structlog.get_logger(name)  # type: ignore[return-value]