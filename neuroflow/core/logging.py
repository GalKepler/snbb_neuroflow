"""Structured logging configuration using structlog."""

import logging
import sys
from pathlib import Path
from typing import Literal

import structlog
from structlog.types import Processor


def setup_logging(
    level: str = "INFO",
    format: Literal["json", "console"] = "json",
    log_file: Path | None = None,
) -> None:
    """Configure structured logging for neuroflow."""
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if format == "json":
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    log_output = sys.stdout
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_output = open(log_file, "a")  # noqa: SIM115

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=log_output),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a logger instance, optionally bound to a name."""
    log = structlog.get_logger()
    if name:
        log = log.bind(component=name)
    return log
