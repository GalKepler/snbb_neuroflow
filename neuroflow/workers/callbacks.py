"""Celery task callbacks."""

import structlog

from neuroflow.models import PipelineRunStatus

log = structlog.get_logger("callbacks")


def on_pipeline_success(run_id: int, pipeline_name: str) -> None:
    """Handle successful pipeline completion."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.core.state import StateManager

    config = NeuroflowConfig.find_and_load()
    state = StateManager(config)

    log.info("callback.success", run_id=run_id, pipeline=pipeline_name)

    # Check if all session pipelines are complete
    # and trigger subject-level pipelines if needed
    with state.get_session() as db:
        from neuroflow.models import PipelineRun, Session

        run = db.get(PipelineRun, run_id)
        if not run or not run.session_id:
            return

        session = db.get(Session, run.session_id)
        if not session:
            return

        # Check if all pending pipelines are done
        if session.pipelines_pending == 0 and session.pipelines_failed == 0:
            from neuroflow.models import SessionStatus

            state.update_session_status(
                session.id, SessionStatus.COMPLETED, triggered_by="callback"
            )

            # Trigger subject-level pipelines
            from neuroflow.orchestrator.workflow import WorkflowManager

            workflow = WorkflowManager(config, state)
            workflow.trigger_subject_pipelines(
                session.subject_id, trigger_session_id=session.id
            )


def on_pipeline_failure(run_id: int, pipeline_name: str, error: str) -> None:
    """Handle pipeline failure."""
    log.error(
        "callback.failure",
        run_id=run_id,
        pipeline=pipeline_name,
        error=error,
    )
