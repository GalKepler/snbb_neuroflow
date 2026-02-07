# Celery Configuration

## Overview

This document describes the Celery configuration for task scheduling, queue management, and worker setup.

## Enhanced Celery App Configuration

### File: `neuroflow/workers/celery_app.py`

```python
"""Celery application configuration."""

from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from neuroflow.config import NeuroflowConfig

# Module-level app, lazily initialized
_celery_app: Celery | None = None


def create_celery_app(config: NeuroflowConfig | None = None) -> Celery:
    """Create and configure the Celery application."""
    global _celery_app

    if _celery_app is not None:
        return _celery_app

    if config is None:
        config = NeuroflowConfig.find_and_load()

    app = Celery("neuroflow")
    
    # Define exchanges
    default_exchange = Exchange("neuroflow", type="direct")
    
    # Define queues with routing
    app.conf.task_queues = (
        # High priority - workflow orchestration
        Queue(
            "workflow",
            exchange=default_exchange,
            routing_key="workflow",
            queue_arguments={"x-max-priority": 10},
        ),
        # High priority - discovery
        Queue(
            "discovery",
            exchange=default_exchange,
            routing_key="discovery",
            queue_arguments={"x-max-priority": 8},
        ),
        # Medium priority - BIDS conversion
        Queue(
            "bids",
            exchange=default_exchange,
            routing_key="bids",
            queue_arguments={"x-max-priority": 5},
        ),
        # Low priority - heavy processing (QSIPrep)
        Queue(
            "heavy_processing",
            exchange=default_exchange,
            routing_key="heavy",
            queue_arguments={"x-max-priority": 2},
        ),
        # Medium priority - standard processing (QSIRecon, QSIParc)
        Queue(
            "processing",
            exchange=default_exchange,
            routing_key="processing",
            queue_arguments={"x-max-priority": 4},
        ),
        # Default queue
        Queue(
            "default",
            exchange=default_exchange,
            routing_key="default",
        ),
    )
    
    # Task routing
    app.conf.task_routes = {
        # Workflow tasks -> workflow queue
        "neuroflow.workers.workflow_tasks.run_master_workflow": {"queue": "workflow"},
        "neuroflow.workers.workflow_tasks.run_discovery_stage": {"queue": "discovery"},
        "neuroflow.workers.workflow_tasks.run_bids_stage": {"queue": "bids"},
        "neuroflow.workers.workflow_tasks.run_qsiprep_stage": {"queue": "heavy_processing"},
        "neuroflow.workers.workflow_tasks.run_qsirecon_stage": {"queue": "processing"},
        "neuroflow.workers.workflow_tasks.run_qsiparc_stage": {"queue": "processing"},
        
        # Discovery tasks
        "neuroflow.workers.tasks.scan_directories": {"queue": "discovery"},
        "neuroflow.workers.tasks.validate_session": {"queue": "discovery"},
        
        # Pipeline execution tasks
        "neuroflow.workers.tasks.run_pipeline": {"queue": "default"},  # Routed dynamically
        "neuroflow.workers.tasks.run_bids_conversion": {"queue": "bids"},
    }

    # Celery beat schedule
    workflow_config = getattr(config, 'workflow', None) or {}
    schedule_cron = workflow_config.get('schedule', '0 2 */3 * *')  # Default: 2 AM every 3 days
    
    # Parse cron expression (minute, hour, day_of_month, month, day_of_week)
    cron_parts = schedule_cron.split()
    if len(cron_parts) == 5:
        minute, hour, day_of_month, month, day_of_week = cron_parts
        workflow_schedule = crontab(
            minute=minute,
            hour=hour,
            day_of_month=day_of_month,
            month_of_year=month,
            day_of_week=day_of_week,
        )
    else:
        # Default fallback
        workflow_schedule = crontab(minute=0, hour=2)
    
    app.conf.beat_schedule = {
        # Master workflow - runs every few days
        "master-workflow": {
            "task": "neuroflow.workers.workflow_tasks.run_master_workflow",
            "schedule": workflow_schedule,
            "options": {"queue": "workflow"},
        },
        # Quick scan for new sessions - runs hourly
        "hourly-scan": {
            "task": "neuroflow.workers.tasks.scan_directories",
            "schedule": crontab(minute=0),  # Every hour
            "options": {"queue": "discovery"},
        },
        # Cleanup stale runs - runs daily
        "daily-cleanup": {
            "task": "neuroflow.workers.tasks.cleanup_stale_runs",
            "schedule": crontab(minute=0, hour=3),  # 3 AM daily
            "options": {"queue": "default"},
        },
    }

    # Core configuration
    app.conf.update(
        broker_url=config.redis.url,
        result_backend=config.redis.url,
        
        # Serialization
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        
        # Time limits from config
        task_soft_time_limit=config.celery.task_soft_time_limit,
        task_time_limit=config.celery.task_time_limit,
        
        # Worker settings
        worker_prefetch_multiplier=1,  # Don't prefetch tasks
        worker_concurrency=config.celery.worker_concurrency,
        
        # Result settings
        result_expires=86400 * 7,  # 7 days
        result_extended=True,  # Store task args/kwargs
        
        # Task settings
        task_acks_late=True,  # Acknowledge after completion
        task_reject_on_worker_lost=True,  # Requeue on worker crash
        task_track_started=True,  # Track when tasks start
        
        # Retry settings
        task_default_retry_delay=config.celery.default_retry_delay,
        
        # Priority
        task_default_queue="default",
        task_queue_max_priority=10,
        task_default_priority=5,
        
        # Timezone
        timezone="UTC",
        enable_utc=True,
    )

    # Auto-discover tasks
    app.autodiscover_tasks([
        "neuroflow.workers",
    ])

    # Store config reference
    app.config_obj = config

    _celery_app = app
    return app


def get_celery_app() -> Celery:
    """Get or create the Celery app."""
    if _celery_app is None:
        return create_celery_app()
    return _celery_app
```

## Workflow Tasks

### File: `neuroflow/workers/workflow_tasks.py`

```python
"""Celery tasks for workflow orchestration."""

import structlog
from celery import shared_task

from neuroflow.models import PipelineRunStatus

log = structlog.get_logger("workflow_tasks")


@shared_task(
    bind=True,
    name="neuroflow.workers.workflow_tasks.run_master_workflow",
    max_retries=0,  # Don't retry workflow - stages handle their own retries
    queue="workflow",
)
def run_master_workflow(self, sync: bool = False, dry_run: bool = False) -> dict:
    """Master workflow task - runs the complete cycle.
    
    This is the main entry point for scheduled workflow execution.
    It orchestrates all stages in sequence.
    """
    from neuroflow.config import NeuroflowConfig
    from neuroflow.orchestrator.scheduler import WorkflowScheduler
    
    task_log = log.bind(task_id=self.request.id)
    task_log.info("workflow.master.started", sync=sync, dry_run=dry_run)
    
    try:
        config = NeuroflowConfig.find_and_load()
        scheduler = WorkflowScheduler(config)
        
        result = scheduler.run_workflow(sync=sync, dry_run=dry_run)
        
        task_log.info(
            "workflow.master.completed",
            workflow_run_id=result.workflow_run_id,
            status=result.status.value,
            stages_completed=len(result.stages_completed),
        )
        
        return {
            "workflow_run_id": result.workflow_run_id,
            "status": result.status.value,
            "stages_completed": [s.value for s in result.stages_completed],
            "error": result.error_message,
        }
        
    except Exception as e:
        task_log.exception("workflow.master.error", error=str(e))
        raise


@shared_task(
    bind=True,
    name="neuroflow.workers.workflow_tasks.run_discovery_stage",
    queue="discovery",
)
def run_discovery_stage(self, workflow_run_id: int) -> dict:
    """Discovery stage - scan for new sessions."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.orchestrator.scheduler import WorkflowScheduler, WorkflowStage
    
    task_log = log.bind(task_id=self.request.id, workflow_run_id=workflow_run_id)
    task_log.info("workflow.stage.discovery.started")
    
    config = NeuroflowConfig.find_and_load()
    scheduler = WorkflowScheduler(config)
    
    result = scheduler._run_stage(
        WorkflowStage.DISCOVERY,
        workflow_run_id,
        sync=False,
        dry_run=False,
    )
    
    return {
        "stage": result.stage.value,
        "success": result.success,
        "tasks_queued": result.tasks_queued,
        "errors": result.errors,
    }


@shared_task(
    bind=True,
    name="neuroflow.workers.workflow_tasks.run_bids_stage",
    queue="bids",
)
def run_bids_stage(self, workflow_run_id: int) -> dict:
    """BIDS conversion stage."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.orchestrator.scheduler import WorkflowScheduler, WorkflowStage
    
    task_log = log.bind(task_id=self.request.id, workflow_run_id=workflow_run_id)
    task_log.info("workflow.stage.bids.started")
    
    config = NeuroflowConfig.find_and_load()
    scheduler = WorkflowScheduler(config)
    
    result = scheduler._run_stage(
        WorkflowStage.BIDS_CONVERSION,
        workflow_run_id,
        sync=False,
        dry_run=False,
    )
    
    return {
        "stage": result.stage.value,
        "success": result.success,
        "tasks_queued": result.tasks_queued,
        "errors": result.errors,
    }


@shared_task(
    bind=True,
    name="neuroflow.workers.workflow_tasks.run_qsiprep_stage",
    queue="heavy_processing",
)
def run_qsiprep_stage(self, workflow_run_id: int) -> dict:
    """QSIPrep preprocessing stage."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.orchestrator.scheduler import WorkflowScheduler, WorkflowStage
    
    task_log = log.bind(task_id=self.request.id, workflow_run_id=workflow_run_id)
    task_log.info("workflow.stage.qsiprep.started")
    
    config = NeuroflowConfig.find_and_load()
    scheduler = WorkflowScheduler(config)
    
    result = scheduler._run_stage(
        WorkflowStage.QSIPREP,
        workflow_run_id,
        sync=False,
        dry_run=False,
    )
    
    return {
        "stage": result.stage.value,
        "success": result.success,
        "tasks_queued": result.tasks_queued,
        "errors": result.errors,
    }


@shared_task(
    bind=True,
    name="neuroflow.workers.workflow_tasks.run_qsirecon_stage",
    queue="processing",
)
def run_qsirecon_stage(self, workflow_run_id: int) -> dict:
    """QSIRecon reconstruction stage."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.orchestrator.scheduler import WorkflowScheduler, WorkflowStage
    
    task_log = log.bind(task_id=self.request.id, workflow_run_id=workflow_run_id)
    task_log.info("workflow.stage.qsirecon.started")
    
    config = NeuroflowConfig.find_and_load()
    scheduler = WorkflowScheduler(config)
    
    result = scheduler._run_stage(
        WorkflowStage.QSIRECON,
        workflow_run_id,
        sync=False,
        dry_run=False,
    )
    
    return {
        "stage": result.stage.value,
        "success": result.success,
        "tasks_queued": result.tasks_queued,
        "errors": result.errors,
    }


@shared_task(
    bind=True,
    name="neuroflow.workers.workflow_tasks.run_qsiparc_stage",
    queue="processing",
)
def run_qsiparc_stage(self, workflow_run_id: int) -> dict:
    """QSIParc parcellation stage."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.orchestrator.scheduler import WorkflowScheduler, WorkflowStage
    
    task_log = log.bind(task_id=self.request.id, workflow_run_id=workflow_run_id)
    task_log.info("workflow.stage.qsiparc.started")
    
    config = NeuroflowConfig.find_and_load()
    scheduler = WorkflowScheduler(config)
    
    result = scheduler._run_stage(
        WorkflowStage.QSIPARC,
        workflow_run_id,
        sync=False,
        dry_run=False,
    )
    
    return {
        "stage": result.stage.value,
        "success": result.success,
        "tasks_queued": result.tasks_queued,
        "errors": result.errors,
    }
```

## Enhanced Pipeline Tasks

### Updated `neuroflow/workers/tasks.py`

```python
"""Celery task definitions."""

import structlog
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from neuroflow.models import PipelineRunStatus

log = structlog.get_logger("worker")


@shared_task(
    bind=True,
    name="neuroflow.workers.tasks.run_pipeline",
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
    from neuroflow.adapters.voxelops import VoxelopsAdapter
    from neuroflow.config import NeuroflowConfig
    from neuroflow.core.state import StateManager
    from neuroflow.orchestrator.registry import get_registry

    task_log = structlog.get_logger().bind(
        task_id=self.request.id,
        run_id=run_id,
        pipeline=pipeline_name,
    )

    config = NeuroflowConfig.find_and_load()
    state = StateManager(config)
    adapter = VoxelopsAdapter(config)
    registry = get_registry()
    
    # Get queue from registry
    pipeline_def = registry.get(pipeline_name)
    queue = pipeline_def.queue if pipeline_def else "default"

    state.update_pipeline_run(
        run_id=run_id,
        status=PipelineRunStatus.RUNNING,
        celery_task_id=self.request.id,
    )

    task_log.info("pipeline.started", queue=queue)

    try:
        result = adapter.run(
            pipeline_name=pipeline_name,
            session_id=session_id,
            subject_id=subject_id,
        )

        final_status = (
            PipelineRunStatus.COMPLETED if result.success else PipelineRunStatus.FAILED
        )

        state.update_pipeline_run(
            run_id=run_id,
            status=final_status,
            exit_code=result.exit_code,
            output_path=str(result.output_path) if result.output_path else None,
            error_message=result.error_message,
            metrics=result.metrics,
            duration_seconds=result.duration_seconds,
        )

        task_log.info(
            "pipeline.finished",
            success=result.success,
            exit_code=result.exit_code,
            duration=result.duration_seconds,
        )
        
        # Trigger callbacks on success
        if result.success:
            from neuroflow.workers.callbacks import on_pipeline_success
            on_pipeline_success(run_id, pipeline_name)
        else:
            from neuroflow.workers.callbacks import on_pipeline_failure
            on_pipeline_failure(run_id, pipeline_name, result.error_message or "Unknown error")

        return {"success": result.success, "run_id": run_id}

    except SoftTimeLimitExceeded:
        task_log.error("pipeline.timeout")
        state.update_pipeline_run(
            run_id=run_id,
            status=PipelineRunStatus.FAILED,
            error_message="Task exceeded time limit",
        )
        
        # Mark for potential retry
        if session_id:
            state.mark_session_for_rerun(session_id, "Timeout during pipeline execution")
        
        raise


@shared_task(name="neuroflow.workers.tasks.scan_directories")
def scan_directories() -> dict:
    """Periodic task to scan for new DICOM sessions."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.core.state import StateManager
    from neuroflow.discovery.scanner import SessionScanner

    config = NeuroflowConfig.find_and_load()
    state = StateManager(config)
    scanner = SessionScanner(config, state)
    found = scanner.scan_all()

    log.info("scan.completed", sessions_found=len(found))
    return {"sessions_found": len(found)}


@shared_task(name="neuroflow.workers.tasks.cleanup_stale_runs")
def cleanup_stale_runs(hours: int = 48) -> dict:
    """Clean up stale pipeline runs that appear stuck."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.core.state import StateManager
    
    config = NeuroflowConfig.find_and_load()
    state = StateManager(config)
    
    stale_runs = state.find_stale_runs(hours=hours)
    
    cancelled = 0
    for run in stale_runs:
        state.update_pipeline_run(
            run.id,
            status=PipelineRunStatus.CANCELLED,
            error_message=f"Cancelled: stale after {hours} hours",
        )
        cancelled += 1
        log.warning("cleanup.cancelled_stale", run_id=run.id, pipeline=run.pipeline_name)
    
    return {"stale_found": len(stale_runs), "cancelled": cancelled}


@shared_task(
    bind=True,
    name="neuroflow.workers.tasks.run_bids_conversion",
    queue="bids",
)
def run_bids_conversion(self, run_id: int, session_id: int) -> dict:
    """Run BIDS conversion for a session."""
    return run_pipeline(
        run_id=run_id,
        pipeline_name="bids_conversion",
        session_id=session_id,
    )
```

## Configuration Updates

### Add to `neuroflow.yaml`:

```yaml
# Workflow configuration
workflow:
  # Cron schedule: minute hour day_of_month month day_of_week
  # Default: 2 AM every 3 days
  schedule: "0 2 */3 * *"
  
  # Maximum concurrent pipelines per type
  max_concurrent:
    bids_conversion: 4
    qsiprep: 1
    qsirecon: 2
    qsiparc: 4
  
  # Retry configuration
  retry:
    max_attempts: 3
    initial_delay_minutes: 5
    max_delay_minutes: 60
    exponential_backoff: true
  
  # Notifications (optional)
  notifications:
    slack_webhook: ""
    email_recipients: []
    on_workflow_complete: true
    on_stage_failure: true

# Celery configuration
celery:
  worker_concurrency: 4
  task_soft_time_limit: 43200  # 12 hours
  task_time_limit: 86400  # 24 hours
  default_retry_delay: 300  # 5 minutes
  max_retries: 3
```

## Worker Deployment

### Running Workers

```bash
# Single worker for all queues
neuroflow run worker

# Worker for specific queues
celery -A neuroflow.workers.celery_app worker -Q workflow,discovery -c 2

# Heavy processing worker (single concurrent task)
celery -A neuroflow.workers.celery_app worker -Q heavy_processing -c 1

# Standard processing worker
celery -A neuroflow.workers.celery_app worker -Q bids,processing -c 4

# Beat scheduler
neuroflow run beat
# or
celery -A neuroflow.workers.celery_app beat
```

### Docker Compose Worker Configuration

```yaml
# docker-compose.yml

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data

  neuroflow-workflow:
    build: .
    command: neuroflow run worker
    depends_on:
      - redis
    environment:
      - NEUROFLOW_REDIS__URL=redis://redis:6379/0
    volumes:
      - ./neuroflow.yaml:/app/neuroflow.yaml
      - /data/brainbank:/data/brainbank

  neuroflow-heavy:
    build: .
    command: celery -A neuroflow.workers.celery_app worker -Q heavy_processing -c 1
    depends_on:
      - redis
    environment:
      - NEUROFLOW_REDIS__URL=redis://redis:6379/0
    volumes:
      - ./neuroflow.yaml:/app/neuroflow.yaml
      - /data/brainbank:/data/brainbank
    deploy:
      resources:
        limits:
          memory: 32G
          cpus: "8"

  neuroflow-beat:
    build: .
    command: neuroflow run beat
    depends_on:
      - redis
    environment:
      - NEUROFLOW_REDIS__URL=redis://redis:6379/0

volumes:
  redis-data:
```

## Monitoring

### Flower Dashboard

```bash
# Install flower
pip install flower

# Run flower
celery -A neuroflow.workers.celery_app flower --port=5555
```

### Celery Events

```bash
# Monitor events
celery -A neuroflow.workers.celery_app events

# Real-time monitoring
celery -A neuroflow.workers.celery_app events -c
```
