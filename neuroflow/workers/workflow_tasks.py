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
