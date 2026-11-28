"""
AetherOS — Structured JSON logging via structlog (C11).

Call configure_logging() once at startup. After that, every logger.info/warning/error
call produces a JSON line that log aggregators (Loki, CloudWatch, Datadog) can parse.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys

from aether_os.core.security.redact import redact_pii, redact_secrets
from aether_os.core.telemetry.trace_context import current_trace_id

# Keys whose values are identifiers or timestamps: never rewritten (a UUID or date must stay searchable).
_KEEP = frozenset({"timestamp", "level", "logger", "trace_id", "org_id", "user_id", "run_id", "request_id"})
_MAX_DEPTH = 4


def _clean(value, depth=0):
    if isinstance(value, str):
        return redact_pii(redact_secrets(value, limit=100_000))
    if depth < _MAX_DEPTH and isinstance(value, dict):
        return {k: (v if k in _KEEP else _clean(v, depth + 1)) for k, v in value.items()}
    if depth < _MAX_DEPTH and isinstance(value, (list, tuple)):
        return [_clean(v, depth + 1) for v in value]
    return value


def add_trace_id(_logger, _method, event_dict):
    """Put the request's trace id on every log line (structlog and stdlib records alike)."""
    tid = current_trace_id()
    if tid and "trace_id" not in event_dict:
        event_dict["trace_id"] = tid
    return event_dict


def redact_event(_logger, _method, event_dict):
    """Last processor before rendering: secrets and personal data never reach the log sink (KAN-50)."""
    return {k: (v if k in _KEEP else _clean(v)) for k, v in event_dict.items()}


def file_handler(formatter: logging.Formatter) -> "logging.Handler | None":
    """Rotating log file under the state directory (a mounted host volume in docker-compose), so the log survives the
    container being recreated: `docker logs` is stored inside the container and was lost with it (KAN-274 G13).
    LOG_TO_FILE=0 turns it off; an unwritable directory is logged and skipped, never fatal."""
    if os.getenv("LOG_TO_FILE", "1").strip().lower() in ("0", "false", "no", "off"):
        return None
    from aether_os.core.state_paths import state_dir
    path = state_dir() / "logs" / "api.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=int(os.getenv("LOG_FILE_MAX_BYTES", str(20 * 1024 * 1024))),
            backupCount=int(os.getenv("LOG_FILE_BACKUPS", "10")), encoding="utf-8")
    except (OSError, ValueError) as exc:
        logging.getLogger(__name__).warning("Persistent log file %s unavailable, logging to stdout only: %s", path, exc)
        return None
    handler.setFormatter(formatter)
    return handler


def configure_logging() -> None:
    """Configure structlog for JSON output in production, pretty output in dev."""
    try:
        import structlog  # type: ignore
    except ImportError:
        # Structlog not installed — fall back to standard logging gracefully.
        plain = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s %(message)s")
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(plain)
        handlers = [h for h in (stream, file_handler(plain)) if h]
        logging.basicConfig(level=_log_level(), handlers=handlers, force=True)
        return

    env = os.getenv("ENVIRONMENT", "development")
    is_prod = env == "production"

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        add_trace_id,
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
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, structlog.processors.format_exc_info,
                    redact_event, renderer],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    persistent = file_handler(formatter)
    if persistent:
        root_logger.addHandler(persistent)
    root_logger.setLevel(_log_level())

    # Quiet noisy third-party loggers
    for lib in ("uvicorn.access", "sqlalchemy.engine", "httpx", "httpcore"):
        logging.getLogger(lib).setLevel(logging.WARNING)


def _log_level() -> int:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_name, logging.INFO)
