"""
AetherOS — Structured JSON logging via structlog (C11).

Call configure_logging() once at startup. After that, every logger.info/warning/error
call produces a JSON line that log aggregators (Loki, CloudWatch, Datadog) can parse.
"""
from __future__ import annotations

import logging
import os
import sys


def configure_logging() -> None:
    """Configure structlog for JSON output in production, pretty output in dev."""
    try:
        import structlog  # type: ignore
    except ImportError:
        # Structlog not installed — fall back to standard logging gracefully.
        logging.basicConfig(
            level=_log_level(),
            format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
            stream=sys.stdout,
        )
        return

    env = os.getenv("ENVIRONMENT", "development")
    is_prod = env == "production"

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if is_prod:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(_log_level())

    # Quiet noisy third-party loggers
    for lib in ("uvicorn.access", "sqlalchemy.engine", "httpx", "httpcore"):
        logging.getLogger(lib).setLevel(logging.WARNING)


def _log_level() -> int:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_name, logging.INFO)
