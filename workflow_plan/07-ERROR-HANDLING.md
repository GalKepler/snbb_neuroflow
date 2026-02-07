# Error Handling and Recovery

## Overview

This document describes the comprehensive error handling strategy, retry logic, dead letter queue management, and recovery tools.

## Error Handling Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      ERROR HANDLING FLOW                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐   │
│  │ Task         │────▶│ Error        │────▶│ Retry Decision       │   │
│  │ Execution    │     │ Caught       │     │                      │   │
│  └──────────────┘     └──────────────┘     └──────────┬───────────┘   │
│                                                        │               │
│                              ┌─────────────────────────┼───────────┐  │
│                              │                         │           │  │
│                              ▼                         ▼           ▼  │
│                    ┌──────────────┐         ┌───────────┐ ┌─────────┐│
│                    │ Retry        │         │ Mark      │ │ Dead    ││
│                    │ (with delay) │         │ Failed    │ │ Letter  ││
│                    └──────────────┘         └───────────┘ │ Queue   ││
│                                                           └─────────┘│
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

## Retry Policy Implementation

### File: `neuroflow/core/retry.py`

```python
"""Retry policy implementation for pipeline execution."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, TypeVar

import structlog

log = structlog.get_logger("retry")

T = TypeVar("T")


class RetryableError(Exception):
    """Base class for errors that should trigger retry."""
    pass


class TransientError(RetryableError):
    """Temporary errors that are likely to succeed on retry."""
    pass


class ResourceError(RetryableError):
    """Resource exhaustion errors (memory, disk, etc.)."""
    pass


class NonRetryableError(Exception):
    """Errors that should NOT trigger retry."""
    pass


class ValidationError(NonRetryableError):
    """Input validation failures."""
    pass


class ConfigurationError(NonRetryableError):
    """Configuration or setup errors."""
    pass


@dataclass
class RetryPolicy:
    """Configuration for retry behavior."""
    max_attempts: int = 3
    initial_delay_seconds: int = 300  # 5 minutes
    max_delay_seconds: int = 3600  # 1 hour
    exponential_backoff: bool = True
    jitter: bool = True
    retry_on: tuple[type[Exception], ...] = (RetryableError,)
    
    def get_delay(self, attempt: int) -> int:
        """Calculate delay for a given attempt number."""
        if not self.exponential_backoff:
            delay = self.initial_delay_seconds
        else:
            delay = self.initial_delay_seconds * (2 ** (attempt - 1))
        
        delay = min(delay, self.max_delay_seconds)
        
        if self.jitter:
            import random
            jitter_range = delay * 0.2  # ±20% jitter
            delay = delay + random.uniform(-jitter_range, jitter_range)
        
        return int(delay)
    
    def should_retry(self, exception: Exception, attempt: int) -> bool:
        """Determine if we should retry after this exception."""
        if attempt >= self.max_attempts:
            return False
        
        if isinstance(exception, NonRetryableError):
            return False
        
        return isinstance(exception, self.retry_on)


class RetryContext:
    """Tracks retry state for a pipeline run."""
    
    def __init__(self, run_id: int, policy: RetryPolicy):
        self.run_id = run_id
        self.policy = policy
        self.attempt = 0
        self.errors: list[dict] = []
        self.started_at = datetime.now(timezone.utc)
    
    def record_error(self, exception: Exception) -> None:
        """Record an error for this retry context."""
        self.errors.append({
            "attempt": self.attempt,
            "error_type": type(exception).__name__,
            "error_message": str(exception),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    
    def should_retry(self, exception: Exception) -> bool:
        """Check if we should retry after this error."""
        return self.policy.should_retry(exception, self.attempt)
    
    def get_next_delay(self) -> int:
        """Get delay before next retry."""
        return self.policy.get_delay(self.attempt)
    
    def increment_attempt(self) -> None:
        """Increment attempt counter."""
        self.attempt += 1
    
    @property
    def is_exhausted(self) -> bool:
        """Check if all retries have been exhausted."""
        return self.attempt >= self.policy.max_attempts


# Default policies for different pipeline types
DEFAULT_POLICIES = {
    "bids_conversion": RetryPolicy(
        max_attempts=2,
        initial_delay_seconds=300,
        max_delay_seconds=1800,
    ),
    "qsiprep": RetryPolicy(
        max_attempts=3,
        initial_delay_seconds=1800,
        max_delay_seconds=7200,
    ),
    "qsirecon": RetryPolicy(
        max_attempts=3,
        initial_delay_seconds=1800,
        max_delay_seconds=3600,
    ),
    "qsiparc": RetryPolicy(
        max_attempts=3,
        initial_delay_seconds=300,
        max_delay_seconds=1800,
    ),
}


def get_retry_policy(pipeline_name: str) -> RetryPolicy:
    """Get the retry policy for a pipeline."""
    return DEFAULT_POLICIES.get(pipeline_name, RetryPolicy())
```

## Error Classification

### File: `neuroflow/core/error_classifier.py`

```python
"""Classify errors to determine retry behavior."""

import re
from typing import Optional

import structlog

from neuroflow.core.retry import (
    ConfigurationError,
    NonRetryableError,
    ResourceError,
    RetryableError,
    TransientError,
    ValidationError,
)

log = structlog.get_logger("error_classifier")


# Pattern matching for common errors
ERROR_PATTERNS = {
    # Transient errors - likely to succeed on retry
    r"Connection refused": TransientError,
    r"Connection reset": TransientError,
    r"Timeout": TransientError,
    r"Network is unreachable": TransientError,
    r"Service Unavailable": TransientError,
    r"Too many open files": TransientError,
    
    # Resource errors - may need delay before retry
    r"Cannot allocate memory": ResourceError,
    r"No space left on device": ResourceError,
    r"Out of memory": ResourceError,
    r"Resource temporarily unavailable": ResourceError,
    r"MemoryError": ResourceError,
    
    # Validation errors - don't retry
    r"Invalid BIDS": ValidationError,
    r"Missing required file": ValidationError,
    r"Malformed DICOM": ValidationError,
    r"Protocol mismatch": ValidationError,
    
    # Configuration errors - don't retry
    r"Config file not found": ConfigurationError,
    r"Invalid configuration": ConfigurationError,
    r"License expired": ConfigurationError,
    r"FreeSurfer license": ConfigurationError,
}


def classify_error(
    exception: Exception,
    stderr: Optional[str] = None,
    exit_code: Optional[int] = None,
) -> type[Exception]:
    """Classify an error to determine retry behavior.
    
    Args:
        exception: The caught exception
        stderr: Standard error output from pipeline
        exit_code: Process exit code
        
    Returns:
        Appropriate exception class for retry handling
    """
    error_text = str(exception)
    if stderr:
        error_text = f"{error_text}\n{stderr}"
    
    # Check against known patterns
    for pattern, error_class in ERROR_PATTERNS.items():
        if re.search(pattern, error_text, re.IGNORECASE):
            log.debug(
                "error.classified",
                pattern=pattern,
                error_class=error_class.__name__,
            )
            return error_class
    
    # Exit code based classification
    if exit_code is not None:
        if exit_code == 137:  # OOM killer
            return ResourceError
        if exit_code == 124:  # Timeout
            return TransientError
        if exit_code in (1, 2):  # Generic/usage error
            return NonRetryableError
    
    # Default: treat as potentially retryable
    log.debug("error.classified_default", error=error_text[:200])
    return RetryableError


def wrap_error(
    exception: Exception,
    stderr: Optional[str] = None,
    exit_code: Optional[int] = None,
) -> Exception:
    """Wrap an exception in the appropriate retryable/non-retryable class."""
    error_class = classify_error(exception, stderr, exit_code)
    
    if error_class == type(exception):
        return exception
    
    return error_class(str(exception))
```

## Dead Letter Queue

### File: `neuroflow/core/dead_letter.py`

```python
"""Dead letter queue for failed pipeline runs."""

from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import JSON, DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from neuroflow.models.base import Base, TimestampMixin

log = structlog.get_logger("dead_letter")


class DeadLetterEntry(Base, TimestampMixin):
    """A failed pipeline run that exhausted retries."""
    __tablename__ = "dead_letter_queue"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    
    # Reference to failed run
    pipeline_run_id: Mapped[int] = mapped_column(Integer, index=True)
    pipeline_name: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    subject_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    
    # Error details
    error_type: Mapped[str] = mapped_column(String(128))
    error_message: Mapped[str] = mapped_column(Text)
    error_details: Mapped[Optional[dict]] = mapped_column(JSON)
    
    # Retry history
    attempts: Mapped[int] = mapped_column(Integer)
    retry_history: Mapped[list] = mapped_column(JSON, default=list)
    
    # Resolution tracking
    resolved: Mapped[bool] = mapped_column(default=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[Optional[str]] = mapped_column(String(128))
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text)


class DeadLetterQueue:
    """Manages failed pipeline runs."""
    
    def __init__(self, db_session_factory):
        self.db_session_factory = db_session_factory
    
    def add(
        self,
        pipeline_run_id: int,
        pipeline_name: str,
        error_type: str,
        error_message: str,
        attempts: int,
        retry_history: list,
        session_id: Optional[int] = None,
        subject_id: Optional[int] = None,
        error_details: Optional[dict] = None,
    ) -> DeadLetterEntry:
        """Add a failed run to the dead letter queue."""
        with self.db_session_factory() as db:
            entry = DeadLetterEntry(
                pipeline_run_id=pipeline_run_id,
                pipeline_name=pipeline_name,
                session_id=session_id,
                subject_id=subject_id,
                error_type=error_type,
                error_message=error_message,
                error_details=error_details,
                attempts=attempts,
                retry_history=retry_history,
            )
            db.add(entry)
            db.flush()
            
            log.warning(
                "dead_letter.added",
                entry_id=entry.id,
                pipeline_run_id=pipeline_run_id,
                pipeline=pipeline_name,
                attempts=attempts,
            )
            
            return entry
    
    def get_unresolved(self, limit: int = 50) -> list[DeadLetterEntry]:
        """Get unresolved dead letter entries."""
        with self.db_session_factory() as db:
            entries = db.execute(
                select(DeadLetterEntry)
                .where(DeadLetterEntry.resolved == False)  # noqa: E712
                .order_by(DeadLetterEntry.created_at.desc())
                .limit(limit)
            ).scalars().all()
            return list(entries)
    
    def resolve(
        self,
        entry_id: int,
        resolved_by: str,
        notes: Optional[str] = None,
    ) -> bool:
        """Mark an entry as resolved."""
        with self.db_session_factory() as db:
            entry = db.get(DeadLetterEntry, entry_id)
            if not entry:
                return False
            
            entry.resolved = True
            entry.resolved_at = datetime.now(timezone.utc)
            entry.resolved_by = resolved_by
            entry.resolution_notes = notes
            
            log.info(
                "dead_letter.resolved",
                entry_id=entry_id,
                resolved_by=resolved_by,
            )
            
            return True
    
    def get_by_pipeline(self, pipeline_name: str) -> list[DeadLetterEntry]:
        """Get dead letter entries for a specific pipeline."""
        with self.db_session_factory() as db:
            entries = db.execute(
                select(DeadLetterEntry)
                .where(DeadLetterEntry.pipeline_name == pipeline_name)
                .where(DeadLetterEntry.resolved == False)  # noqa: E712
                .order_by(DeadLetterEntry.created_at.desc())
            ).scalars().all()
            return list(entries)
    
    def get_stats(self) -> dict:
        """Get statistics about the dead letter queue."""
        from sqlalchemy import func
        
        with self.db_session_factory() as db:
            total = db.execute(
                select(func.count(DeadLetterEntry.id))
            ).scalar()
            
            unresolved = db.execute(
                select(func.count(DeadLetterEntry.id))
                .where(DeadLetterEntry.resolved == False)  # noqa: E712
            ).scalar()
            
            by_pipeline = db.execute(
                select(
                    DeadLetterEntry.pipeline_name,
                    func.count(DeadLetterEntry.id),
                )
                .where(DeadLetterEntry.resolved == False)  # noqa: E712
                .group_by(DeadLetterEntry.pipeline_name)
            ).all()
            
            return {
                "total": total,
                "unresolved": unresolved,
                "by_pipeline": {row[0]: row[1] for row in by_pipeline},
            }
```

## Recovery Tools

### File: `neuroflow/cli/recovery.py`

```python
"""Recovery CLI commands for failed pipelines."""

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def recovery() -> None:
    """Recovery and error handling commands."""


@recovery.command("list")
@click.option("--pipeline", default=None, help="Filter by pipeline name")
@click.option("--limit", default=20, type=int, help="Number of entries")
@click.pass_context
def list_failed(ctx: click.Context, pipeline: str | None, limit: int) -> None:
    """List failed pipeline runs in dead letter queue."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.core.dead_letter import DeadLetterQueue
    from neuroflow.core.state import StateManager
    
    config = ctx.obj["config"]
    state = StateManager(config)
    dlq = DeadLetterQueue(state.get_session)
    
    if pipeline:
        entries = dlq.get_by_pipeline(pipeline)
    else:
        entries = dlq.get_unresolved(limit=limit)
    
    if not entries:
        console.print("[green]No unresolved entries in dead letter queue[/green]")
        return
    
    table = Table(title="Dead Letter Queue")
    table.add_column("ID", style="bold")
    table.add_column("Pipeline")
    table.add_column("Session/Subject")
    table.add_column("Error Type")
    table.add_column("Attempts")
    table.add_column("Failed At")
    
    for entry in entries:
        entity = f"ses:{entry.session_id}" if entry.session_id else f"sub:{entry.subject_id}"
        table.add_row(
            str(entry.id),
            entry.pipeline_name,
            entity,
            entry.error_type,
            str(entry.attempts),
            entry.created_at.strftime("%Y-%m-%d %H:%M"),
        )
    
    console.print(table)


@recovery.command("show")
@click.argument("entry_id", type=int)
@click.pass_context
def show_entry(ctx: click.Context, entry_id: int) -> None:
    """Show details of a dead letter entry."""
    from neuroflow.core.dead_letter import DeadLetterQueue
    from neuroflow.core.state import StateManager
    
    config = ctx.obj["config"]
    state = StateManager(config)
    dlq = DeadLetterQueue(state.get_session)
    
    entries = dlq.get_unresolved(limit=1000)
    entry = next((e for e in entries if e.id == entry_id), None)
    
    if not entry:
        console.print(f"[red]Entry {entry_id} not found[/red]")
        return
    
    console.print(f"[bold]Dead Letter Entry {entry.id}[/bold]\n")
    console.print(f"Pipeline: {entry.pipeline_name}")
    console.print(f"Pipeline Run ID: {entry.pipeline_run_id}")
    console.print(f"Session ID: {entry.session_id}")
    console.print(f"Subject ID: {entry.subject_id}")
    console.print(f"Attempts: {entry.attempts}")
    console.print(f"Failed At: {entry.created_at}")
    
    console.print("\n[bold]Error:[/bold]")
    console.print(f"Type: {entry.error_type}")
    console.print(f"Message: {entry.error_message}")
    
    if entry.retry_history:
        console.print("\n[bold]Retry History:[/bold]")
        for i, retry in enumerate(entry.retry_history, 1):
            console.print(f"  {i}. {retry.get('timestamp', 'N/A')}: {retry.get('error_message', 'N/A')[:100]}")


@recovery.command("retry")
@click.argument("entry_id", type=int)
@click.option("--force", is_flag=True, help="Force retry even if non-retryable")
@click.pass_context
def retry_entry(ctx: click.Context, entry_id: int, force: bool) -> None:
    """Retry a failed pipeline run."""
    from neuroflow.core.dead_letter import DeadLetterQueue
    from neuroflow.core.state import StateManager
    from neuroflow.workers.tasks import run_pipeline
    
    config = ctx.obj["config"]
    state = StateManager(config)
    dlq = DeadLetterQueue(state.get_session)
    
    entries = dlq.get_unresolved(limit=1000)
    entry = next((e for e in entries if e.id == entry_id), None)
    
    if not entry:
        console.print(f"[red]Entry {entry_id} not found[/red]")
        return
    
    # Create new pipeline run
    new_run = state.create_pipeline_run(
        pipeline_name=entry.pipeline_name,
        session_id=entry.session_id,
        subject_id=entry.subject_id,
        attempt_number=entry.attempts + 1,
    )
    
    console.print(f"[yellow]Queueing retry for {entry.pipeline_name}...[/yellow]")
    
    # Queue the task
    run_pipeline.delay(
        run_id=new_run.id,
        pipeline_name=entry.pipeline_name,
        session_id=entry.session_id,
        subject_id=entry.subject_id,
    )
    
    # Mark entry as resolved
    dlq.resolve(entry_id, resolved_by="manual_retry", notes=f"Retried as run {new_run.id}")
    
    console.print(f"[green]Queued as pipeline run {new_run.id}[/green]")


@recovery.command("resolve")
@click.argument("entry_id", type=int)
@click.option("--notes", default=None, help="Resolution notes")
@click.pass_context
def resolve_entry(ctx: click.Context, entry_id: int, notes: str | None) -> None:
    """Mark a dead letter entry as resolved (without retry)."""
    from neuroflow.core.dead_letter import DeadLetterQueue
    from neuroflow.core.state import StateManager
    
    config = ctx.obj["config"]
    state = StateManager(config)
    dlq = DeadLetterQueue(state.get_session)
    
    if dlq.resolve(entry_id, resolved_by="manual", notes=notes):
        console.print(f"[green]Entry {entry_id} marked as resolved[/green]")
    else:
        console.print(f"[red]Entry {entry_id} not found[/red]")


@recovery.command("retry-all")
@click.option("--pipeline", required=True, help="Pipeline name to retry")
@click.option("--dry-run", is_flag=True, help="Show what would be retried")
@click.pass_context
def retry_all(ctx: click.Context, pipeline: str, dry_run: bool) -> None:
    """Retry all failed runs for a pipeline."""
    from neuroflow.core.dead_letter import DeadLetterQueue
    from neuroflow.core.state import StateManager
    from neuroflow.workers.tasks import run_pipeline
    
    config = ctx.obj["config"]
    state = StateManager(config)
    dlq = DeadLetterQueue(state.get_session)
    
    entries = dlq.get_by_pipeline(pipeline)
    
    if not entries:
        console.print(f"[green]No failed entries for {pipeline}[/green]")
        return
    
    console.print(f"Found {len(entries)} failed entries for {pipeline}")
    
    if dry_run:
        console.print("[yellow]Dry run - no changes made[/yellow]")
        for entry in entries:
            entity = f"session {entry.session_id}" if entry.session_id else f"subject {entry.subject_id}"
            console.print(f"  Would retry: {entity}")
        return
    
    for entry in entries:
        new_run = state.create_pipeline_run(
            pipeline_name=entry.pipeline_name,
            session_id=entry.session_id,
            subject_id=entry.subject_id,
            attempt_number=entry.attempts + 1,
        )
        
        run_pipeline.delay(
            run_id=new_run.id,
            pipeline_name=entry.pipeline_name,
            session_id=entry.session_id,
            subject_id=entry.subject_id,
        )
        
        dlq.resolve(entry.id, resolved_by="batch_retry", notes=f"Retried as run {new_run.id}")
        
        entity = f"session {entry.session_id}" if entry.session_id else f"subject {entry.subject_id}"
        console.print(f"  Queued: {entity} -> run {new_run.id}")
    
    console.print(f"[green]Queued {len(entries)} retries[/green]")


@recovery.command("stats")
@click.pass_context
def show_stats(ctx: click.Context) -> None:
    """Show dead letter queue statistics."""
    from neuroflow.core.dead_letter import DeadLetterQueue
    from neuroflow.core.state import StateManager
    
    config = ctx.obj["config"]
    state = StateManager(config)
    dlq = DeadLetterQueue(state.get_session)
    
    stats = dlq.get_stats()
    
    console.print("[bold]Dead Letter Queue Statistics[/bold]\n")
    console.print(f"Total entries: {stats['total']}")
    console.print(f"Unresolved: {stats['unresolved']}")
    
    if stats['by_pipeline']:
        console.print("\n[bold]By Pipeline:[/bold]")
        for pipeline, count in stats['by_pipeline'].items():
            console.print(f"  {pipeline}: {count}")
```

## Integration with Pipeline Execution

### Updated task handling in `neuroflow/workers/tasks.py`:

```python
# Add to run_pipeline task

from neuroflow.core.dead_letter import DeadLetterQueue
from neuroflow.core.error_classifier import wrap_error
from neuroflow.core.retry import get_retry_policy, RetryContext

@shared_task(bind=True, ...)
def run_pipeline(self, run_id: int, pipeline_name: str, ...):
    # ... existing setup ...
    
    policy = get_retry_policy(pipeline_name)
    retry_ctx = RetryContext(run_id, policy)
    
    try:
        # ... existing execution code ...
        pass
    except Exception as exc:
        # Classify the error
        classified_error = wrap_error(exc, stderr=result.stderr if result else None)
        retry_ctx.record_error(classified_error)
        
        if retry_ctx.should_retry(classified_error):
            retry_ctx.increment_attempt()
            delay = retry_ctx.get_next_delay()
            
            log.warning(
                "pipeline.retry_scheduled",
                run_id=run_id,
                attempt=retry_ctx.attempt,
                delay_seconds=delay,
                error=str(classified_error),
            )
            
            # Re-raise for Celery retry
            raise self.retry(
                exc=classified_error,
                countdown=delay,
                max_retries=policy.max_attempts - 1,
            )
        else:
            # Add to dead letter queue
            dlq = DeadLetterQueue(state.get_session)
            dlq.add(
                pipeline_run_id=run_id,
                pipeline_name=pipeline_name,
                error_type=type(classified_error).__name__,
                error_message=str(classified_error),
                attempts=retry_ctx.attempt,
                retry_history=retry_ctx.errors,
                session_id=session_id,
                subject_id=subject_id,
            )
            
            log.error(
                "pipeline.failed_permanently",
                run_id=run_id,
                attempts=retry_ctx.attempt,
                error=str(classified_error),
            )
            
            raise
```

## Configuration

Add to `neuroflow.yaml`:

```yaml
# Error handling configuration
error_handling:
  # Default retry policy
  default_retry:
    max_attempts: 3
    initial_delay_minutes: 5
    max_delay_minutes: 60
    exponential_backoff: true
    jitter: true
  
  # Pipeline-specific overrides
  pipelines:
    qsiprep:
      max_attempts: 3
      initial_delay_minutes: 30
      max_delay_minutes: 120
    bids_conversion:
      max_attempts: 2
      initial_delay_minutes: 5
      max_delay_minutes: 30
  
  # Dead letter queue settings
  dead_letter:
    retention_days: 90
    auto_cleanup: true
    
  # Notifications
  notifications:
    on_dead_letter: true
    slack_webhook: ""
    email_recipients: []
```
