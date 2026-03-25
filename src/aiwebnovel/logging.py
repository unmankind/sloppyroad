"""Structlog configuration for AIWN 2.0.

Provides JSON output for production and pretty console output for development.
Must be called early in application startup before any logging occurs.
"""

from __future__ import annotations

import logging
import re
import sys

import structlog

from aiwebnovel.config import Settings

# Pattern that matches common API key formats in log values
_KEY_REDACT_RE = re.compile(
    r"(sk-ant-api\S+|sk-ant-\S+|sk-proj-\S+|sk-\S{20,}|r8_\S+)"
)


def _redact_api_keys(
    _logger: object, _method: str, event_dict: dict,
) -> dict:
    """Structlog processor that scrubs API key patterns from all values."""
    for key, value in event_dict.items():
        if isinstance(value, str) and _KEY_REDACT_RE.search(value):
            event_dict[key] = _KEY_REDACT_RE.sub("[REDACTED]", value)
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure structlog and stdlib logging.

    Args:
        settings: Application settings (uses log_level and debug).
    """
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        _redact_api_keys,  # SECURITY: scrub API keys before rendering
    ]

    if settings.debug:
        # Pretty console output for development
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        # JSON output for production (Docker, log aggregation)
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
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Quiet noisy third-party loggers
    for name in ("uvicorn.access", "httpcore", "httpx", "litellm"):
        logging.getLogger(name).setLevel(max(log_level, logging.WARNING))
