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

    task_log = structlog.get_logger().bind(
        task_id=self.request.id,
        run_id=run_id,
        pipeline=pipeline_name,
    )

    config = NeuroflowConfig.find_and_load()
    state = StateManager(config)
    adapter = VoxelopsAdapter(config)

    state.update_pipeline_run(
        run_id=run_id,
        status=PipelineRunStatus.RUNNING,
        celery_task_id=self.request.id,
    )

    task_log.info("pipeline.started")

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
        )

        return {"success": result.success, "run_id": run_id}

    except SoftTimeLimitExceeded:
        task_log.error("pipeline.timeout")
        state.update_pipeline_run(
            run_id=run_id,
            status=PipelineRunStatus.FAILED,
            error_message="Task exceeded time limit",
        )
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

    return {"sessions_found": len(found)}


@shared_task(name="neuroflow.workers.tasks.run_bids_conversion")
def run_bids_conversion(
    run_id: int,
    session_id: int,
) -> dict:
    """Run BIDS conversion for a session."""
    from neuroflow.adapters.voxelops import VoxelopsAdapter
    from neuroflow.config import NeuroflowConfig
    from neuroflow.core.state import StateManager

    config = NeuroflowConfig.find_and_load()
    state = StateManager(config)
    adapter = VoxelopsAdapter(config)

    state.update_pipeline_run(
        run_id=run_id,
        status=PipelineRunStatus.RUNNING,
    )

    log.info("bids_conversion.started", run_id=run_id, session_id=session_id)

    try:
        result = adapter.run(
            pipeline_name="bids_conversion",
            session_id=session_id,
        )

        final_status = (
            PipelineRunStatus.COMPLETED if result.success else PipelineRunStatus.FAILED
        )

        state.update_pipeline_run(
            run_id=run_id,
            status=final_status,
            exit_code=result.exit_code,
            error_message=result.error_message,
            duration_seconds=result.duration_seconds,
        )

        return {"success": result.success, "run_id": run_id}

    except SoftTimeLimitExceeded:
        state.update_pipeline_run(
            run_id=run_id,
            status=PipelineRunStatus.FAILED,
            error_message="BIDS conversion exceeded time limit",
        )
        raise
