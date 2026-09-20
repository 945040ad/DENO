"""Structured logging (structlog → stdlib), JSON in production.

Context such as ``request_id``, ``user_id``, ``project_id`` and ``run_id`` is
bound with ``bind_context()`` (contextvars) and appears on every log line
emitted in that request/job. Never log raw post text, emails or tokens.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from deno_core.settings import Settings, get_settings

_configured = False


def configure_logging(settings: Settings | None = None) -> None:
    global _configured
    if _configured:
        return
    settings = settings or get_settings()
    level = getattr(logging, settings.log_level.upper())

    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if settings.log_json else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # uvicorn's access log duplicates our request log.
    logging.getLogger("uvicorn.access").disabled = True
    _configured = True


def get_logger(name: str | None = None) -> Any:
    return structlog.stdlib.get_logger(name)


def bind_context(**values: Any) -> None:
    structlog.contextvars.bind_contextvars(**{k: v for k, v in values.items() if v is not None})


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()
