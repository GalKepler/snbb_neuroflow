# Logging and Monitoring

## Overview

This document describes the comprehensive logging system, metrics collection, and monitoring setup for neuroflow workflows.

## Logging Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          LOGGING ARCHITECTURE                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────┐ │
│  │ Neuroflow    │    │ Celery       │    │ VoxelOps / Pipeline      │ │
│  │ Core Logs    │    │ Task Logs    │    │ Logs                     │ │
│  └──────┬───────┘    └──────┬───────┘    └────────────┬─────────────┘ │
│         │                   │                         │               │
│         ▼                   ▼                         ▼               │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                    STRUCTLOG PROCESSOR                           │ │
│  │  - Add timestamps                                                │ │
│  │  - Add context (run_id, session_id, etc.)                       │ │
│  │  - Format as JSON or console                                     │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                │                                       │
│         ┌──────────────────────┼──────────────────────┐               │
│         ▼                      ▼                      ▼               │
│  ┌─────────────┐      ┌─────────────┐        ┌─────────────────┐     │
│  │ Console     │      │ File        │        │ External        │     │
│  │ Output      │      │ Rotation    │        │ Aggregation     │     │
│  └─────────────┘      └─────────────┘        └─────────────────┘     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Enhanced Logging Configuration

### File: `neuroflow/core/logging.py`

```python
"""Structured logging configuration using structlog."""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import structlog
from structlog.types import Processor


def add_workflow_context(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Add workflow context to log events."""
    event_dict["@timestamp"] = datetime.now(timezone.utc).isoformat()
    event_dict["service"] = "neuroflow"
    return event_dict


def setup_logging(
    level: str = "INFO",
    format: Literal["json", "console"] = "json",
    log_file: Path | None = None,
    log_dir: Path | None = None,
) -> None:
    """Configure structured logging for neuroflow."""
    
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        add_workflow_context,
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

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, level.upper()),
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    
    logging.getLogger("celery").setLevel(logging.WARNING)
    logging.getLogger("kombu").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a logger instance."""
    log = structlog.get_logger()
    if name:
        log = log.bind(component=name)
    return log


class WorkflowLogContext:
    """Context manager for workflow logging context."""
    
    def __init__(
        self,
        workflow_run_id: int | None = None,
        stage: str | None = None,
        pipeline: str | None = None,
        session_id: int | None = None,
        subject_id: int | None = None,
    ):
        self.context = {}
        if workflow_run_id:
            self.context["workflow_run_id"] = workflow_run_id
        if stage:
            self.context["stage"] = stage
        if pipeline:
            self.context["pipeline"] = pipeline
        if session_id:
            self.context["session_id"] = session_id
        if subject_id:
            self.context["subject_id"] = subject_id
    
    def __enter__(self) -> structlog.BoundLogger:
        structlog.contextvars.bind_contextvars(**self.context)
        return structlog.get_logger()
    
    def __exit__(self, *args) -> None:
        structlog.contextvars.unbind_contextvars(*self.context.keys())
```

## Log Event Taxonomy

### Standard Events

```python
# Workflow lifecycle
log.info("workflow.started", workflow_run_id=123, trigger="scheduled")
log.info("workflow.completed", workflow_run_id=123, duration=3600, stages=5)
log.error("workflow.failed", workflow_run_id=123, error="Stage qsiprep failed")

# Stage events
log.info("stage.started", stage="bids_conversion", workflow_run_id=123)
log.info("stage.completed", stage="bids_conversion", tasks_queued=5, duration=120)
log.error("stage.failed", stage="bids_conversion", errors=["timeout"])

# Pipeline events
log.info("pipeline.queued", pipeline="qsiprep", run_id=456, subject_id=789)
log.info("pipeline.started", pipeline="qsiprep", run_id=456)
log.info("pipeline.completed", pipeline="qsiprep", run_id=456, duration=3600)
log.error("pipeline.failed", pipeline="qsiprep", run_id=456, error="Memory limit")

# Discovery events
log.info("discovery.started", path="/data/dicom")
log.info("discovery.session_found", subject="sub-001", session="ses-01")
log.info("discovery.completed", sessions_found=10)
```

## Pipeline Log Capture

### File: `neuroflow/core/pipeline_logger.py`

```python
"""Pipeline output logging and capture."""

import io
from datetime import datetime, timezone
from pathlib import Path

import structlog

log = structlog.get_logger("pipeline_output")


class PipelineLogCapture:
    """Captures stdout/stderr from pipeline execution."""
    
    def __init__(self, run_id: int, pipeline_name: str, log_dir: Path):
        self.run_id = run_id
        self.pipeline_name = pipeline_name
        self.log_dir = log_dir
        self.log_file: Path | None = None
        self._stdout_buffer = io.StringIO()
        self._stderr_buffer = io.StringIO()
    
    def __enter__(self) -> "PipelineLogCapture":
        self.log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"{self.pipeline_name}_{self.run_id}_{timestamp}.log"
        log.debug("pipeline_log.capture_started", run_id=self.run_id, log_file=str(self.log_file))
        return self
    
    def __exit__(self, *args) -> None:
        if self.log_file:
            with open(self.log_file, "w") as f:
                f.write("=== STDOUT ===\n")
                f.write(self._stdout_buffer.getvalue())
                f.write("\n=== STDERR ===\n")
                f.write(self._stderr_buffer.getvalue())
        log.debug("pipeline_log.capture_completed", run_id=self.run_id)
    
    def write_stdout(self, text: str) -> None:
        self._stdout_buffer.write(text)
    
    def write_stderr(self, text: str) -> None:
        self._stderr_buffer.write(text)
    
    @property
    def stdout(self) -> str:
        return self._stdout_buffer.getvalue()
    
    @property
    def stderr(self) -> str:
        return self._stderr_buffer.getvalue()
```

## Metrics Collection

### File: `neuroflow/core/metrics.py`

```python
"""Metrics collection for neuroflow workflows."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

log = structlog.get_logger("metrics")


@dataclass
class WorkflowMetrics:
    """Metrics for a workflow run."""
    workflow_run_id: int
    started_at: datetime
    completed_at: datetime | None = None
    
    stages_executed: int = 0
    stages_successful: int = 0
    stages_failed: int = 0
    
    pipelines_queued: int = 0
    pipelines_completed: int = 0
    pipelines_failed: int = 0
    
    stage_durations: dict[str, float] = field(default_factory=dict)
    total_duration_seconds: float = 0.0
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_run_id": self.workflow_run_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "stages_executed": self.stages_executed,
            "stages_successful": self.stages_successful,
            "stages_failed": self.stages_failed,
            "pipelines_queued": self.pipelines_queued,
            "pipelines_completed": self.pipelines_completed,
            "pipelines_failed": self.pipelines_failed,
            "stage_durations": self.stage_durations,
            "total_duration_seconds": self.total_duration_seconds,
        }


class MetricsCollector:
    """Collects and aggregates workflow metrics."""
    
    def __init__(self):
        self._current_metrics: dict[int, WorkflowMetrics] = {}
    
    def start_workflow(self, workflow_run_id: int) -> None:
        self._current_metrics[workflow_run_id] = WorkflowMetrics(
            workflow_run_id=workflow_run_id,
            started_at=datetime.now(timezone.utc),
        )
    
    def record_stage(
        self,
        workflow_run_id: int,
        stage: str,
        success: bool,
        duration_seconds: float,
        tasks_queued: int = 0,
    ) -> None:
        metrics = self._current_metrics.get(workflow_run_id)
        if not metrics:
            return
        
        metrics.stages_executed += 1
        if success:
            metrics.stages_successful += 1
        else:
            metrics.stages_failed += 1
        
        metrics.stage_durations[stage] = duration_seconds
        metrics.pipelines_queued += tasks_queued
    
    def complete_workflow(self, workflow_run_id: int) -> WorkflowMetrics | None:
        metrics = self._current_metrics.pop(workflow_run_id, None)
        if not metrics:
            return None
        
        metrics.completed_at = datetime.now(timezone.utc)
        metrics.total_duration_seconds = (
            metrics.completed_at - metrics.started_at
        ).total_seconds()
        
        log.info("metrics.workflow_completed", metrics=metrics.to_dict())
        return metrics


_collector: MetricsCollector | None = None

def get_metrics_collector() -> MetricsCollector:
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector
```

## CLI Log Commands

### File: `neuroflow/cli/logs.py`

```python
"""Log access CLI commands."""

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def logs() -> None:
    """Log viewing commands."""


@logs.command("show")
@click.option("--component", default=None, help="Filter by component")
@click.option("--level", default=None, help="Filter by log level")
@click.option("--tail", default=50, type=int, help="Number of lines")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.pass_context
def show_logs(ctx: click.Context, component: str | None, level: str | None, tail: int, follow: bool) -> None:
    """Show recent logs."""
    import subprocess
    
    config = ctx.obj["config"]
    log_file = config.paths.log_dir / "neuroflow.log"
    
    cmd = ["tail", f"-n{tail}"]
    if follow:
        cmd.append("-f")
    cmd.append(str(log_file))
    subprocess.run(cmd)


@logs.command("pipeline")
@click.argument("run_id", type=int)
@click.pass_context
def show_pipeline_log(ctx: click.Context, run_id: int) -> None:
    """Show logs for a specific pipeline run."""
    from neuroflow.core.state import StateManager
    
    config = ctx.obj["config"]
    state = StateManager(config)
    
    run = state.get_pipeline_run(run_id)
    if not run:
        console.print(f"[red]Pipeline run {run_id} not found[/red]")
        return
    
    log_dir = config.paths.log_dir / "pipelines" / run.pipeline_name
    log_files = list(log_dir.glob(f"*_{run_id}_*.log"))
    
    if not log_files:
        console.print(f"[yellow]No log file found for run {run_id}[/yellow]")
        return
    
    with open(log_files[0]) as f:
        console.print(f.read())


@logs.command("audit")
@click.option("--entity", default=None, help="Entity type")
@click.option("--entity-id", default=None, type=int, help="Entity ID")
@click.option("--limit", default=50, type=int, help="Number of entries")
@click.pass_context
def show_audit_log(ctx: click.Context, entity: str | None, entity_id: int | None, limit: int) -> None:
    """Show audit log entries."""
    from neuroflow.core.state import StateManager
    
    config = ctx.obj["config"]
    state = StateManager(config)
    
    entries = state.get_audit_log(entity_type=entity, entity_id=entity_id, limit=limit)
    
    if not entries:
        console.print("[yellow]No audit log entries found[/yellow]")
        return
    
    table = Table(title="Audit Log")
    table.add_column("Timestamp", style="dim")
    table.add_column("Entity")
    table.add_column("Action")
    table.add_column("Message")
    
    for entry in entries:
        table.add_row(
            entry.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            f"{entry.entity_type}:{entry.entity_id}",
            entry.action,
            entry.message or "",
        )
    
    console.print(table)


@logs.command("workflow")
@click.argument("workflow_run_id", type=int, required=False)
@click.option("--list", "-l", "list_runs", is_flag=True, help="List recent workflow runs")
@click.pass_context
def show_workflow_log(ctx: click.Context, workflow_run_id: int | None, list_runs: bool) -> None:
    """Show workflow run history and details."""
    from neuroflow.core.state import StateManager
    
    config = ctx.obj["config"]
    state = StateManager(config)
    
    if list_runs or workflow_run_id is None:
        runs = state.get_workflow_run_history(limit=10)
        
        table = Table(title="Recent Workflow Runs")
        table.add_column("ID", style="bold")
        table.add_column("Status")
        table.add_column("Started")
        table.add_column("Duration")
        table.add_column("Stages")
        
        for run in runs:
            duration = ""
            if run.duration_seconds:
                hours, remainder = divmod(int(run.duration_seconds), 3600)
                minutes, _ = divmod(remainder, 60)
                duration = f"{hours}h {minutes}m"
            
            status_style = {
                "completed": "green",
                "running": "blue",
                "failed": "red",
            }.get(run.status.value, "white")
            
            table.add_row(
                str(run.id),
                f"[{status_style}]{run.status.value}[/{status_style}]",
                run.started_at.strftime("%Y-%m-%d %H:%M") if run.started_at else "-",
                duration or "-",
                str(len(run.stages_completed)),
            )
        
        console.print(table)
```

## Dashboard Queries

### File: `neuroflow/core/dashboard_queries.py`

```python
"""Queries for dashboard and monitoring."""

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from neuroflow.models import PipelineRun, PipelineRunStatus, Session, SessionStatus, WorkflowRun


class DashboardQueries:
    """Query methods for dashboard metrics."""
    
    def __init__(self, db_session):
        self.db = db_session
    
    def get_overview_stats(self) -> dict[str, Any]:
        """Get high-level overview statistics."""
        now = datetime.now(timezone.utc)
        last_24h = now - timedelta(hours=24)
        
        return {
            "total_sessions": self.db.execute(select(func.count(Session.id))).scalar(),
            "sessions_completed": self.db.execute(
                select(func.count(Session.id)).where(Session.status == SessionStatus.COMPLETED)
            ).scalar(),
            "sessions_failed": self.db.execute(
                select(func.count(Session.id)).where(Session.status == SessionStatus.FAILED)
            ).scalar(),
            "pipeline_runs_24h": self.db.execute(
                select(func.count(PipelineRun.id)).where(PipelineRun.created_at >= last_24h)
            ).scalar(),
        }
    
    def get_pipeline_stats_by_type(self) -> list[dict]:
        """Get pipeline statistics grouped by type."""
        results = self.db.execute(
            select(
                PipelineRun.pipeline_name,
                func.count(PipelineRun.id).label("total"),
                func.sum(func.case((PipelineRun.status == PipelineRunStatus.COMPLETED, 1), else_=0)).label("completed"),
                func.sum(func.case((PipelineRun.status == PipelineRunStatus.FAILED, 1), else_=0)).label("failed"),
                func.avg(PipelineRun.duration_seconds).label("avg_duration"),
            ).group_by(PipelineRun.pipeline_name)
        ).all()
        
        return [
            {
                "pipeline": row.pipeline_name,
                "total": row.total,
                "completed": row.completed,
                "failed": row.failed,
                "success_rate": row.completed / row.total if row.total else 0,
                "avg_duration_minutes": row.avg_duration / 60 if row.avg_duration else None,
            }
            for row in results
        ]
    
    def get_recent_failures(self, limit: int = 10) -> list[dict]:
        """Get recent pipeline failures."""
        results = self.db.execute(
            select(PipelineRun)
            .where(PipelineRun.status == PipelineRunStatus.FAILED)
            .order_by(PipelineRun.updated_at.desc())
            .limit(limit)
        ).scalars().all()
        
        return [
            {
                "run_id": run.id,
                "pipeline": run.pipeline_name,
                "session_id": run.session_id,
                "error": run.error_message,
                "failed_at": run.updated_at.isoformat(),
            }
            for run in results
        ]
    
    def get_processing_queue_depth(self) -> dict[str, int]:
        """Get current queue depth by status."""
        results = self.db.execute(
            select(PipelineRun.status, func.count(PipelineRun.id))
            .where(PipelineRun.status.in_([
                PipelineRunStatus.PENDING,
                PipelineRunStatus.QUEUED,
                PipelineRunStatus.RUNNING,
            ]))
            .group_by(PipelineRun.status)
        ).all()
        
        return {row[0].value: row[1] for row in results}
```

## Log File Structure

```
/var/log/neuroflow/
├── neuroflow.log              # Main application log
├── workflow.log               # Workflow-specific events
├── celery/
│   ├── worker.log            # Celery worker logs
│   └── beat.log              # Celery beat logs
├── pipelines/
│   ├── bids_conversion/
│   │   └── run_123_20240101_120000.log
│   ├── qsiprep/
│   │   └── run_125_20240102_160000.log
│   ├── qsirecon/
│   │   └── run_126_20240103_080000.log
│   └── qsiparc/
│       └── run_127_20240103_100000.log
└── audit/
    └── audit_2024_01.jsonl   # Monthly audit logs
```

## Configuration

Add to `neuroflow.yaml`:

```yaml
logging:
  level: INFO
  format: json  # json or console
  log_dir: /var/log/neuroflow
  
  rotation:
    max_size_mb: 100
    backup_count: 10
  
  components:
    celery: WARNING
    sqlalchemy: WARNING
    workflow: INFO
    pipeline: DEBUG
```
