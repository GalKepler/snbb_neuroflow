"""Structured logging configuration using structlog."""

import logging
import sys
import traceback
from pathlib import Path
from typing import Literal

import structlog
from structlog.types import Processor


def setup_logging(
    level: str = "INFO",
    format: Literal["json", "console"] = "console",
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
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a logger instance, optionally bound to a name."""
    log = structlog.get_logger()
    if name:
        log = log.bind(component=name)
    return log


def setup_session_logger(
    log_dir: Path,
    pipeline_name: str,
    participant_id: str,
    session_id: str,
) -> Path:
    """Configure structlog to write to a per-session log file.

    Reconfigures structlog in this process so all subsequent log calls
    (from the adapter, runner, etc.) go to the file. Also returns the
    path so callers can write additional output (stdout/stderr) to it.

    Returns the log file path: {log_dir}/{pipeline_name}/{participant_id}_{session_id}.log
    """
    pipeline_log_dir = log_dir / pipeline_name
    pipeline_log_dir.mkdir(parents=True, exist_ok=True)

    log_path = pipeline_log_dir / f"{participant_id}_{session_id}.log"

    # Reconfigure structlog to write to this file (no colors in files)
    log_file = open(log_path, "a")  # noqa: SIM115

    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer(colors=False),
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=log_file),
        cache_logger_on_first_use=False,
    )

    return log_path


def write_to_log(log_path: Path, header: str, content: str) -> None:
    """Append a labelled block of text to a log file."""
    if not content or not content.strip():
        return
    with open(log_path, "a") as f:
        f.write(f"\n{'=' * 72}\n")
        f.write(f"  {header}\n")
        f.write(f"{'=' * 72}\n")
        f.write(content)
        if not content.endswith("\n"):
            f.write("\n")
