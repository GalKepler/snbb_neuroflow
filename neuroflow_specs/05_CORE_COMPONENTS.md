# Neuroflow - Core Components Specification

## Overview

This document covers the core components: structured logging, Celery task queue, state management, and the voxelops adapter.

---

## 1. Structured Logging with Structlog

### Configuration

```python
# neuroflow/core/logging.py

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
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(
            file=open(log_file, "a") if log_file else sys.stdout
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a logger instance, optionally bound to a name."""
    log = structlog.get_logger()
    if name:
        log = log.bind(component=name)
    return log
```

### Usage Patterns

```python
import structlog
from neuroflow.core.logging import get_logger

log = get_logger("discovery")

# Basic logging
log.info("scan.started", path="/data/incoming")

# With context that persists
log = log.bind(subject_id="sub-001", session_id="ses-baseline")
log.info("validation.started")
log.info("validation.completed", scans_found=5, is_valid=True)

# Error logging with exception info
try:
    # ... processing
except Exception as e:
    log.error("processing.failed", error=str(e), exc_info=True)
```

---

## 2. Celery Task Queue

### Celery Application

```python
# neuroflow/workers/celery_app.py

from celery import Celery
from kombu import Queue
from neuroflow.config import NeuroflowConfig


def create_celery_app(config: NeuroflowConfig) -> Celery:
    """Create and configure the Celery application."""
    
    app = Celery("neuroflow")
    
    app.conf.update(
        broker_url=config.redis.url,
        result_backend=config.redis.url,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_soft_time_limit=config.celery.task_soft_time_limit,
        task_time_limit=config.celery.task_time_limit,
        worker_prefetch_multiplier=1,
        worker_concurrency=config.celery.worker_concurrency,
        result_expires=86400,
        task_queues=(
            Queue("default", routing_key="default"),
            Queue("bids", routing_key="bids"),
            Queue("processing", routing_key="processing"),
        ),
        task_default_queue="default",
        beat_schedule={
            "scan-for-new-sessions": {
                "task": "neuroflow.workers.tasks.scan_directories",
                "schedule": 300.0,
            },
        },
    )
    
    return app
```

### Task Definitions

```python
# neuroflow/workers/tasks.py

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
import structlog

from neuroflow.workers.celery_app import celery_app
from neuroflow.core.state import StateManager
from neuroflow.adapters.voxelops import VoxelopsAdapter
from neuroflow.models import PipelineRunStatus

log = structlog.get_logger("worker")


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=3600,
)
def run_pipeline(
    self,
    run_id: int,
    pipeline_name: str,
    session_id: int | None = None,
    subject_id: int | None = None,
) -> dict:
    """Execute a pipeline for a session or subject."""
    
    log = structlog.get_logger().bind(
        task_id=self.request.id,
        run_id=run_id,
        pipeline=pipeline_name,
    )
    
    state = StateManager()
    adapter = VoxelopsAdapter()
    
    state.update_pipeline_run(
        run_id=run_id,
        status=PipelineRunStatus.RUNNING,
        celery_task_id=self.request.id,
    )
    
    log.info("pipeline.started")
    
    try:
        result = adapter.run(
            pipeline_name=pipeline_name,
            session_id=session_id,
            subject_id=subject_id,
        )
        
        state.update_pipeline_run(
            run_id=run_id,
            status=PipelineRunStatus.COMPLETED if result.success else PipelineRunStatus.FAILED,
            exit_code=result.exit_code,
            output_path=str(result.output_path) if result.output_path else None,
            error_message=result.error_message,
            metrics=result.metrics,
        )
        
        return {"success": result.success, "run_id": run_id}
        
    except SoftTimeLimitExceeded:
        log.error("pipeline.timeout")
        state.update_pipeline_run(
            run_id=run_id,
            status=PipelineRunStatus.FAILED,
            error_message="Task exceeded time limit",
        )
        raise


@celery_app.task
def scan_directories() -> dict:
    """Periodic task to scan for new DICOM sessions."""
    from neuroflow.discovery.scanner import SessionScanner
    
    scanner = SessionScanner()
    found = scanner.scan_all()
    
    return {"sessions_found": len(found)}
```

---

## 3. State Manager

The StateManager handles all database operations with automatic audit logging. See `03_DATABASE_SCHEMA.md` for the full implementation.

Key methods:
- `get_or_create_subject(participant_id)` - Register new subjects
- `register_session(subject_id, session_id, dicom_path)` - Register discovered sessions
- `update_session_validation(session_id, is_valid, scans_found)` - Store validation results
- `create_pipeline_run(pipeline_name, ...)` - Create pipeline run records
- `update_pipeline_run(run_id, status, ...)` - Update run with results
- `find_stale_runs(hours)` - Find stuck tasks

---

## 4. Voxelops Adapter

```python
# neuroflow/adapters/voxelops.py

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import subprocess
import structlog

from neuroflow.config import NeuroflowConfig

log = structlog.get_logger("voxelops")


@dataclass
class PipelineResult:
    """Result of a pipeline execution."""
    success: bool
    exit_code: int
    output_path: Path | None = None
    error_message: str | None = None
    duration_seconds: float | None = None
    metrics: dict | None = None
    logs: str | None = None


class VoxelopsAdapter:
    """Adapter for calling voxelops procedures."""
    
    def __init__(self, config: NeuroflowConfig | None = None):
        if config is None:
            config = NeuroflowConfig.from_yaml("neuroflow.yaml")
        self.config = config
    
    def run(
        self,
        pipeline_name: str,
        session_id: int | None = None,
        subject_id: int | None = None,
        **kwargs: Any,
    ) -> PipelineResult:
        """Run a pipeline via voxelops."""
        
        pipeline_config = self._get_pipeline_config(pipeline_name)
        if not pipeline_config:
            return PipelineResult(
                success=False,
                exit_code=-1,
                error_message=f"Unknown pipeline: {pipeline_name}",
            )
        
        try:
            # Option 1: Direct voxelops import
            return self._run_via_import(pipeline_config, session_id, subject_id, **kwargs)
        except ImportError:
            # Option 2: Container execution
            return self._run_via_container(pipeline_config, session_id, subject_id, **kwargs)
    
    def _run_via_container(
        self,
        pipeline_config,
        session_id: int | None,
        subject_id: int | None,
        **kwargs,
    ) -> PipelineResult:
        """Run pipeline via container (apptainer/docker)."""
        import time
        
        start_time = time.time()
        cmd = self._build_container_command(pipeline_config, session_id, subject_id, **kwargs)
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=pipeline_config.timeout_minutes * 60,
            )
            
            return PipelineResult(
                success=result.returncode == 0,
                exit_code=result.returncode,
                duration_seconds=time.time() - start_time,
                error_message=result.stderr if result.returncode != 0 else None,
                logs=result.stdout,
            )
            
        except subprocess.TimeoutExpired:
            return PipelineResult(
                success=False,
                exit_code=-1,
                error_message=f"Timeout after {pipeline_config.timeout_minutes} minutes",
            )
    
    def _build_container_command(self, pipeline_config, session_id, subject_id, **kwargs) -> list[str]:
        """Build the container execution command."""
        runtime = self.config.container_runtime
        
        if runtime == "apptainer":
            cmd = ["apptainer", "run"]
        elif runtime == "docker":
            cmd = ["docker", "run", "--rm"]
        else:
            cmd = ["singularity", "run"]
        
        # Add bind mounts
        for mount in self.config.container.bind_mounts:
            if runtime == "apptainer":
                cmd.extend(["--bind", mount])
            else:
                cmd.extend(["-v", mount])
        
        # Add container image
        cmd.append(pipeline_config.container)
        
        # Add pipeline-specific arguments
        # This would be customized based on each pipeline's CLI
        
        return cmd
    
    def _get_pipeline_config(self, pipeline_name: str):
        """Get pipeline configuration by name."""
        for p in self.config.pipelines.session_level:
            if p.name == pipeline_name:
                return p
        for p in self.config.pipelines.subject_level:
            if p.name == pipeline_name:
                return p
        return None
```

---

## 5. Discovery Components

### DICOM Watcher

```python
# neuroflow/discovery/watcher.py

from pathlib import Path
from datetime import datetime, timedelta
import structlog

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, DirCreatedEvent

from neuroflow.config import NeuroflowConfig
from neuroflow.core.state import StateManager

log = structlog.get_logger("watcher")


class DicomEventHandler(FileSystemEventHandler):
    """Handle new DICOM directory events."""
    
    def __init__(self, config: NeuroflowConfig, state: StateManager):
        self.config = config
        self.state = state
        self.pending_sessions: dict[str, datetime] = {}
    
    def on_created(self, event):
        if isinstance(event, DirCreatedEvent):
            self._handle_new_directory(Path(event.src_path))
    
    def _handle_new_directory(self, path: Path):
        """Handle a newly created directory."""
        from neuroflow.discovery.scanner import parse_dicom_path
        
        parsed = parse_dicom_path(path, self.config.dataset.dicom_participant_first)
        if parsed:
            participant_id, session_id = parsed
            log.info(
                "dicom.detected",
                participant_id=participant_id,
                session_id=session_id,
                path=str(path),
            )
            self.pending_sessions[str(path)] = datetime.utcnow()


class DicomWatcher:
    """Watch DICOM incoming directory for new data."""
    
    def __init__(self, config: NeuroflowConfig):
        self.config = config
        self.state = StateManager(config)
        self.observer = Observer()
        self.handler = DicomEventHandler(config, self.state)
    
    def start(self):
        """Start watching for new DICOM data."""
        watch_path = self.config.paths.dicom_incoming
        self.observer.schedule(self.handler, str(watch_path), recursive=True)
        self.observer.start()
        log.info("watcher.started", path=str(watch_path))
    
    def stop(self):
        """Stop the watcher."""
        self.observer.stop()
        self.observer.join()
        log.info("watcher.stopped")
```

### Session Scanner

```python
# neuroflow/discovery/scanner.py

from pathlib import Path
from dataclasses import dataclass
import re
import pydicom
import structlog

from neuroflow.config import NeuroflowConfig
from neuroflow.core.state import StateManager

log = structlog.get_logger("scanner")


@dataclass
class ScanInfo:
    series_description: str
    file_count: int
    series_uid: str


@dataclass  
class SessionScanResult:
    session_path: Path
    subject_id: str
    session_id: str
    scans: list[ScanInfo]


def parse_dicom_path(path: Path, participant_first: bool) -> tuple[str, str] | None:
    """Extract subject and session IDs from DICOM path."""
    parts = path.parts
    if len(parts) < 2:
        return None
    
    if participant_first:
        # /Raw_Data/SUBJECT/SESSION/
        subject_id = parts[-2]
        session_id = parts[-1]
    else:
        # /Raw_Data/SESSION/SUBJECT/
        session_id = parts[-2]
        subject_id = parts[-1]
    
    return subject_id, session_id


class SessionScanner:
    """Scan directories for DICOM sessions."""
    
    def __init__(self, config: NeuroflowConfig | None = None):
        if config is None:
            config = NeuroflowConfig.from_yaml("neuroflow.yaml")
        self.config = config
        self.state = StateManager(config)
    
    def scan_all(self) -> list[SessionScanResult]:
        """Scan all configured directories for new sessions."""
        results = []
        incoming = self.config.paths.dicom_incoming
        
        log.info("scan.started", path=str(incoming))
        
        for session_path in self._find_session_dirs(incoming):
            result = self._scan_session(session_path)
            if result:
                results.append(result)
                self._register_session(result)
        
        log.info("scan.completed", sessions_found=len(results))
        return results
    
    def _find_session_dirs(self, root: Path) -> list[Path]:
        """Find directories that look like DICOM sessions."""
        sessions = []
        
        if self.config.dataset.dicom_participant_first:
            # /root/subject/session/
            for subject_dir in root.iterdir():
                if subject_dir.is_dir():
                    for session_dir in subject_dir.iterdir():
                        if session_dir.is_dir() and self._has_dicoms(session_dir):
                            sessions.append(session_dir)
        else:
            # /root/session/subject/
            for session_dir in root.iterdir():
                if session_dir.is_dir():
                    for subject_dir in session_dir.iterdir():
                        if subject_dir.is_dir() and self._has_dicoms(subject_dir):
                            sessions.append(subject_dir)
        
        return sessions
    
    def _has_dicoms(self, path: Path) -> bool:
        """Check if directory contains DICOM files."""
        for f in path.rglob("*"):
            if f.is_file() and f.suffix.lower() in (".dcm", ".ima", ""):
                try:
                    pydicom.dcmread(f, stop_before_pixels=True)
                    return True
                except:
                    continue
        return False
    
    def _scan_session(self, session_path: Path) -> SessionScanResult | None:
        """Scan a session directory for DICOM series."""
        parsed = parse_dicom_path(session_path, self.config.dataset.dicom_participant_first)
        if not parsed:
            return None
        
        subject_id, session_id = parsed
        scans = self._identify_scans(session_path)
        
        return SessionScanResult(
            session_path=session_path,
            subject_id=subject_id,
            session_id=session_id,
            scans=scans,
        )
    
    def _identify_scans(self, session_path: Path) -> list[ScanInfo]:
        """Identify all scans in a session directory."""
        series: dict[str, ScanInfo] = {}
        
        for dcm_file in session_path.rglob("*"):
            if not dcm_file.is_file():
                continue
            try:
                ds = pydicom.dcmread(dcm_file, stop_before_pixels=True)
                uid = str(ds.SeriesInstanceUID)
                desc = str(getattr(ds, "SeriesDescription", "Unknown"))
                
                if uid not in series:
                    series[uid] = ScanInfo(
                        series_description=desc,
                        file_count=1,
                        series_uid=uid,
                    )
                else:
                    series[uid].file_count += 1
            except:
                continue
        
        return list(series.values())
    
    def _register_session(self, result: SessionScanResult) -> None:
        """Register a discovered session in the database."""
        subject = self.state.get_or_create_subject(result.subject_id)
        self.state.register_session(
            subject_id=subject.id,
            session_id=result.session_id,
            dicom_path=str(result.session_path),
        )
```

---

## 6. Workflow Manager

```python
# neuroflow/orchestrator/workflow.py

from typing import Any
import structlog

from neuroflow.config import NeuroflowConfig, PipelineConfig
from neuroflow.core.state import StateManager
from neuroflow.models import Session, PipelineRunStatus
from neuroflow.workers.tasks import run_pipeline

log = structlog.get_logger("workflow")


class WorkflowManager:
    """Manages pipeline workflow execution."""
    
    def __init__(self, config: NeuroflowConfig | None = None):
        if config is None:
            config = NeuroflowConfig.from_yaml("neuroflow.yaml")
        self.config = config
        self.state = StateManager(config)
    
    def process_session(self, session_id: int) -> list[int]:
        """Queue all applicable pipelines for a session."""
        with self.state.get_session() as db:
            session = db.get(Session, session_id)
            if not session:
                return []
            
            bids_suffixes = session.bids_suffixes or []
        
        run_ids = []
        
        for pipeline in self.config.pipelines.session_level:
            if not pipeline.enabled:
                continue
            
            if not self._check_requirements(pipeline, bids_suffixes):
                log.debug("pipeline.skipped", 
                         pipeline=pipeline.name, 
                         reason="requirements not met")
                continue
            
            # Create pipeline run record
            run = self.state.create_pipeline_run(
                pipeline_name=pipeline.name,
                pipeline_level="session",
                session_id=session_id,
                pipeline_version=pipeline.container.split(":")[-1] if pipeline.container else None,
            )
            
            # Queue the task
            run_pipeline.delay(
                run_id=run.id,
                pipeline_name=pipeline.name,
                session_id=session_id,
            )
            
            run_ids.append(run.id)
            log.info("pipeline.queued", pipeline=pipeline.name, run_id=run.id)
        
        return run_ids
    
    def _check_requirements(self, pipeline: PipelineConfig, bids_suffixes: list[str]) -> bool:
        """Check if pipeline requirements are met."""
        required = pipeline.requirements.get("bids_suffixes", [])
        return all(suffix in bids_suffixes for suffix in required)
    
    def trigger_subject_pipelines(self, subject_id: int, trigger_session_id: int) -> list[int]:
        """Trigger subject-level pipelines when a new session is added."""
        run_ids = []
        
        for pipeline in self.config.pipelines.subject_level:
            if not pipeline.enabled:
                continue
            if not pipeline.trigger_on_new_session:
                continue
            
            # Check if minimum sessions requirement is met
            with self.state.get_session() as db:
                from sqlalchemy import select, func
                from neuroflow.models import Session, SessionStatus
                
                session_count = db.execute(
                    select(func.count(Session.id))
                    .where(Session.subject_id == subject_id)
                    .where(Session.status == SessionStatus.COMPLETED)
                ).scalar()
            
            min_sessions = pipeline.min_sessions if hasattr(pipeline, 'min_sessions') else 2
            if session_count < min_sessions:
                continue
            
            run = self.state.create_pipeline_run(
                pipeline_name=pipeline.name,
                pipeline_level="subject",
                subject_id=subject_id,
                trigger_reason="new_session",
                trigger_session_id=trigger_session_id,
            )
            
            run_pipeline.delay(
                run_id=run.id,
                pipeline_name=pipeline.name,
                subject_id=subject_id,
            )
            
            run_ids.append(run.id)
            log.info("subject_pipeline.queued", 
                    pipeline=pipeline.name, 
                    subject_id=subject_id,
                    trigger="new_session")
        
        return run_ids
```
