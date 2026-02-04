"""Workflow manager for pipeline orchestration."""

import structlog
from sqlalchemy import func, select

from neuroflow.config import NeuroflowConfig, PipelineConfig
from neuroflow.core.state import StateManager
from neuroflow.models import (
    PipelineRun,
    PipelineRunStatus,
    Session,
    SessionStatus,
)

log = structlog.get_logger("workflow")


class WorkflowManager:
    """Manages pipeline workflow execution."""

    def __init__(
        self, config: NeuroflowConfig, state: StateManager | None = None
    ):
        self.config = config
        self.state = state or StateManager(config)

    def process_session(
        self,
        session_id: int,
        force: bool = False,
        pipeline_filter: str | None = None,
    ) -> list[int]:
        """Queue all applicable pipelines for a session.

        Args:
            session_id: Database ID of the session.
            force: If True, reprocess even if already completed.
            pipeline_filter: If set, only run this specific pipeline.

        Returns:
            List of pipeline run IDs that were queued.
        """
        with self.state.get_session() as db:
            session = db.get(Session, session_id)
            if not session:
                return []

            bids_suffixes = session.bids_suffixes or []
            subject_id = session.subject_id

            # Check existing completed/running pipelines
            existing_runs: dict[str, str] = {}
            if not force:
                runs = (
                    db.execute(
                        select(PipelineRun).where(
                            PipelineRun.session_id == session_id,
                            PipelineRun.status.in_([
                                PipelineRunStatus.COMPLETED,
                                PipelineRunStatus.RUNNING,
                                PipelineRunStatus.QUEUED,
                            ]),
                        )
                    )
                    .scalars()
                    .all()
                )
                existing_runs = {r.pipeline_name: r.status.value for r in runs}

        run_ids = []

        for pipeline in self.config.pipelines.session_level:
            if not pipeline.enabled:
                continue

            if pipeline_filter and pipeline.name != pipeline_filter:
                continue

            if not force and pipeline.name in existing_runs:
                log.debug(
                    "pipeline.skipped",
                    pipeline=pipeline.name,
                    reason=f"already {existing_runs[pipeline.name]}",
                )
                continue

            if not self._check_requirements(pipeline, bids_suffixes):
                log.debug(
                    "pipeline.skipped",
                    pipeline=pipeline.name,
                    reason="requirements not met",
                )
                continue

            # Create pipeline run record
            run = self.state.create_pipeline_run(
                pipeline_name=pipeline.name,
                pipeline_level="session",
                session_id=session_id,
                subject_id=subject_id,
                pipeline_version=(
                    pipeline.container.split(":")[-1] if pipeline.container else None
                ),
            )

            # Queue the task
            from neuroflow.workers.tasks import run_pipeline

            run_pipeline.delay(
                run_id=run.id,
                pipeline_name=pipeline.name,
                session_id=session_id,
            )

            run_ids.append(run.id)
            log.info("pipeline.queued", pipeline=pipeline.name, run_id=run.id)

        # Update session status
        if run_ids:
            self.state.update_session_status(
                session_id, SessionStatus.PROCESSING, triggered_by="workflow"
            )

        return run_ids

    def _check_requirements(
        self, pipeline: PipelineConfig, bids_suffixes: list[str]
    ) -> bool:
        """Check if pipeline requirements are met."""
        required = pipeline.requirements.get("bids_suffixes", [])
        if not required:
            return True
        return all(suffix in bids_suffixes for suffix in required)

    def trigger_subject_pipelines(
        self, subject_id: int, trigger_session_id: int
    ) -> list[int]:
        """Trigger subject-level pipelines when a new session is added."""
        run_ids = []

        for pipeline in self.config.pipelines.subject_level:
            if not pipeline.enabled:
                continue
            if not pipeline.trigger_on_new_session:
                continue

            # Check if minimum sessions requirement is met
            with self.state.get_session() as db:
                session_count = (
                    db.execute(
                        select(func.count(Session.id)).where(
                            Session.subject_id == subject_id,
                            Session.status == SessionStatus.COMPLETED,
                        )
                    ).scalar()
                    or 0
                )

            if session_count < pipeline.min_sessions:
                continue

            # Check dependencies
            depends_on = pipeline.requirements.get("depends_on", [])
            if depends_on:
                with self.state.get_session() as db:
                    # All sessions must have completed the dependency pipelines
                    sessions = (
                        db.execute(
                            select(Session).where(
                                Session.subject_id == subject_id,
                                Session.status == SessionStatus.COMPLETED,
                            )
                        )
                        .scalars()
                        .all()
                    )

                    all_deps_met = True
                    for sess in sessions:
                        for dep in depends_on:
                            dep_run = db.execute(
                                select(PipelineRun).where(
                                    PipelineRun.session_id == sess.id,
                                    PipelineRun.pipeline_name == dep,
                                    PipelineRun.status
                                    == PipelineRunStatus.COMPLETED,
                                )
                            ).scalar_one_or_none()
                            if not dep_run:
                                all_deps_met = False
                                break
                        if not all_deps_met:
                            break

                    if not all_deps_met:
                        continue

            # Check if already running/completed
            with self.state.get_session() as db:
                existing = db.execute(
                    select(PipelineRun).where(
                        PipelineRun.subject_id == subject_id,
                        PipelineRun.pipeline_name == pipeline.name,
                        PipelineRun.status.in_([
                            PipelineRunStatus.COMPLETED,
                            PipelineRunStatus.RUNNING,
                            PipelineRunStatus.QUEUED,
                        ]),
                    )
                ).scalar_one_or_none()

                if existing:
                    continue

            run = self.state.create_pipeline_run(
                pipeline_name=pipeline.name,
                pipeline_level="subject",
                subject_id=subject_id,
                trigger_reason="new_session",
                trigger_session_id=trigger_session_id,
            )

            from neuroflow.workers.tasks import run_pipeline

            run_pipeline.delay(
                run_id=run.id,
                pipeline_name=pipeline.name,
                subject_id=subject_id,
            )

            run_ids.append(run.id)
            log.info(
                "subject_pipeline.queued",
                pipeline=pipeline.name,
                subject_id=subject_id,
                trigger="new_session",
            )

        return run_ids
