# Workflow Scheduler Implementation

## Overview

The Workflow Scheduler is the central orchestration component that manages the complete processing workflow. It executes stages in order, handles dependencies, and coordinates resource allocation.

## File: `neuroflow/orchestrator/scheduler.py`

### Complete Implementation

```python
"""Master Workflow Scheduler - Orchestrates the complete processing workflow.

This module provides the central orchestration for neuroflow's processing pipeline.
The scheduler runs through stages sequentially, identifies work to be done, and
dispatches tasks to Celery workers while respecting dependencies and resource limits.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import and_, func, or_, select

from neuroflow.config import NeuroflowConfig
from neuroflow.core.state import StateManager
from neuroflow.models import (
    PipelineRun,
    PipelineRunStatus,
    Session,
    SessionStatus,
    Subject,
    SubjectStatus,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession

log = structlog.get_logger("scheduler")


class WorkflowStage(str, Enum):
    """Stages in the workflow execution."""
    DISCOVERY = "discovery"
    BIDS_CONVERSION = "bids_conversion"
    QSIPREP = "qsiprep"
    QSIRECON = "qsirecon"
    QSIPARC = "qsiparc"


class WorkflowStatus(str, Enum):
    """Status of a workflow run."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class StageResult:
    """Result of executing a workflow stage."""
    stage: WorkflowStage
    success: bool
    tasks_queued: int
    tasks_skipped: int
    errors: list[str]
    duration_seconds: float


@dataclass 
class WorkflowResult:
    """Result of a complete workflow execution."""
    workflow_run_id: int
    status: WorkflowStatus
    stages_completed: list[WorkflowStage]
    stage_results: dict[WorkflowStage, StageResult]
    total_duration_seconds: float
    error_message: str | None


class WorkflowScheduler:
    """Master scheduler for the complete workflow cycle.
    
    The scheduler orchestrates the following stages:
    1. Discovery - Scan DICOM directories and register new sessions
    2. BIDS Conversion - Convert DICOM to BIDS for new/failed sessions
    3. QSIPrep - Preprocess subjects with new sessions
    4. QSIRecon - Reconstruct sessions with completed QSIPrep
    5. QSIParc - Parcellate sessions with completed QSIRecon
    
    Each stage identifies eligible work, checks dependencies, and queues tasks
    to Celery workers. The scheduler can run synchronously (waiting for each
    stage to complete) or asynchronously (dispatching all tasks immediately).
    """
    
    def __init__(
        self,
        config: NeuroflowConfig,
        state: StateManager | None = None,
    ):
        """Initialize the workflow scheduler.
        
        Args:
            config: Neuroflow configuration
            state: Optional StateManager instance
        """
        self.config = config
        self.state = state or StateManager(config)
        self._workflow_config = getattr(config, 'workflow', None) or {}
        
    def run_workflow(
        self,
        sync: bool = False,
        force_stage: WorkflowStage | None = None,
        dry_run: bool = False,
    ) -> WorkflowResult:
        """Execute the complete workflow cycle.
        
        Args:
            sync: If True, wait for each stage to complete before proceeding
            force_stage: If set, only run this specific stage
            dry_run: If True, don't actually execute pipelines
            
        Returns:
            WorkflowResult with execution details
        """
        start_time = time.time()
        workflow_run_id = self._create_workflow_run()
        
        log.info(
            "workflow.started",
            workflow_run_id=workflow_run_id,
            sync=sync,
            force_stage=force_stage.value if force_stage else None,
        )
        
        stages_to_run = (
            [force_stage] if force_stage else list(WorkflowStage)
        )
        
        stages_completed: list[WorkflowStage] = []
        stage_results: dict[WorkflowStage, StageResult] = {}
        error_message: str | None = None
        final_status = WorkflowStatus.COMPLETED
        
        try:
            for stage in stages_to_run:
                self._update_workflow_run(
                    workflow_run_id,
                    current_stage=stage.value,
                )
                
                log.info("workflow.stage.starting", stage=stage.value)
                
                result = self._run_stage(
                    stage,
                    workflow_run_id,
                    sync=sync,
                    dry_run=dry_run,
                )
                
                stage_results[stage] = result
                
                if result.success:
                    stages_completed.append(stage)
                    log.info(
                        "workflow.stage.completed",
                        stage=stage.value,
                        tasks_queued=result.tasks_queued,
                        duration=result.duration_seconds,
                    )
                else:
                    error_message = f"Stage {stage.value} failed: {result.errors}"
                    final_status = WorkflowStatus.FAILED
                    log.error(
                        "workflow.stage.failed",
                        stage=stage.value,
                        errors=result.errors,
                    )
                    break
                    
        except Exception as e:
            error_message = str(e)
            final_status = WorkflowStatus.FAILED
            log.exception("workflow.error", error=str(e))
        
        total_duration = time.time() - start_time
        
        self._update_workflow_run(
            workflow_run_id,
            status=final_status,
            completed_at=datetime.now(timezone.utc),
            stages_completed=[s.value for s in stages_completed],
            current_stage=None,
            error_message=error_message,
        )
        
        log.info(
            "workflow.completed",
            workflow_run_id=workflow_run_id,
            status=final_status.value,
            stages_completed=len(stages_completed),
            total_duration=total_duration,
        )
        
        return WorkflowResult(
            workflow_run_id=workflow_run_id,
            status=final_status,
            stages_completed=stages_completed,
            stage_results=stage_results,
            total_duration_seconds=total_duration,
            error_message=error_message,
        )
    
    def _run_stage(
        self,
        stage: WorkflowStage,
        workflow_run_id: int,
        sync: bool = False,
        dry_run: bool = False,
    ) -> StageResult:
        """Execute a single workflow stage.
        
        Args:
            stage: The stage to execute
            workflow_run_id: ID of the parent workflow run
            sync: Whether to wait for tasks to complete
            dry_run: Whether to skip actual execution
            
        Returns:
            StageResult with execution details
        """
        start_time = time.time()
        
        stage_handlers = {
            WorkflowStage.DISCOVERY: self._run_discovery_stage,
            WorkflowStage.BIDS_CONVERSION: self._run_bids_conversion_stage,
            WorkflowStage.QSIPREP: self._run_qsiprep_stage,
            WorkflowStage.QSIRECON: self._run_qsirecon_stage,
            WorkflowStage.QSIPARC: self._run_qsiparc_stage,
        }
        
        handler = stage_handlers[stage]
        
        try:
            tasks_queued, tasks_skipped, errors = handler(
                workflow_run_id, 
                sync=sync,
                dry_run=dry_run,
            )
            success = len(errors) == 0
        except Exception as e:
            tasks_queued, tasks_skipped = 0, 0
            errors = [str(e)]
            success = False
            log.exception("stage.error", stage=stage.value, error=str(e))
        
        return StageResult(
            stage=stage,
            success=success,
            tasks_queued=tasks_queued,
            tasks_skipped=tasks_skipped,
            errors=errors,
            duration_seconds=time.time() - start_time,
        )
    
    # -------------------------------------------------------------------------
    # Stage Implementations
    # -------------------------------------------------------------------------
    
    def _run_discovery_stage(
        self,
        workflow_run_id: int,
        sync: bool = False,
        dry_run: bool = False,
    ) -> tuple[int, int, list[str]]:
        """Stage 1: Scan DICOM directory and register new sessions.
        
        This stage:
        1. Fetches the latest Google Sheet mapping
        2. Scans the DICOM incoming directory for new folders
        3. Associates folders with subject codes
        4. Registers new sessions in the database
        5. Validates sessions against protocol requirements
        
        Returns:
            Tuple of (sessions_registered, sessions_skipped, errors)
        """
        from neuroflow.discovery.scanner import SessionScanner
        from neuroflow.discovery.validator import SessionValidator
        
        log.info("stage.discovery.starting", workflow_run_id=workflow_run_id)
        
        errors: list[str] = []
        
        if dry_run:
            log.info("stage.discovery.dry_run")
            return 0, 0, errors
        
        try:
            scanner = SessionScanner(self.config, self.state)
            results = scanner.scan_all()
            
            sessions_registered = len(results)
            sessions_skipped = 0
            
            # Validate newly registered sessions
            validator = SessionValidator(self.config)
            
            with self.state.get_session() as db:
                for result in results:
                    # Find the registered session
                    session = db.execute(
                        select(Session)
                        .join(Subject)
                        .where(
                            Subject.participant_id == result.subject_id,
                            Session.session_id == result.session_id,
                        )
                    ).scalar_one_or_none()
                    
                    if session:
                        validation = validator.validate(result.scans)
                        self.state.update_session_validation(
                            session.id,
                            is_valid=validation.is_valid,
                            scans_found=validation.scans_found,
                            validation_message=validation.message,
                        )
            
            log.info(
                "stage.discovery.completed",
                sessions_registered=sessions_registered,
                sessions_skipped=sessions_skipped,
            )
            
            return sessions_registered, sessions_skipped, errors
            
        except Exception as e:
            errors.append(f"Discovery failed: {str(e)}")
            log.exception("stage.discovery.error", error=str(e))
            return 0, 0, errors
    
    def _run_bids_conversion_stage(
        self,
        workflow_run_id: int,
        sync: bool = False,
        dry_run: bool = False,
    ) -> tuple[int, int, list[str]]:
        """Stage 2: Convert DICOM to BIDS for eligible sessions.
        
        Eligible sessions are:
        - New sessions (status=VALIDATED, no BIDS conversion run)
        - Sessions with failed BIDS conversion (can be retried)
        
        Returns:
            Tuple of (tasks_queued, tasks_skipped, errors)
        """
        log.info("stage.bids_conversion.starting", workflow_run_id=workflow_run_id)
        
        errors: list[str] = []
        tasks_queued = 0
        tasks_skipped = 0
        
        # Get max concurrent from config
        max_concurrent = self._get_max_concurrent("bids_conversion")
        
        # Find eligible sessions
        eligible_sessions = self._get_sessions_for_bids_conversion()
        
        log.info(
            "stage.bids_conversion.eligible",
            count=len(eligible_sessions),
            max_concurrent=max_concurrent,
        )
        
        if dry_run:
            return len(eligible_sessions), 0, errors
        
        # Queue tasks up to max_concurrent
        for session_id, subject_id, participant_id, session_label in eligible_sessions[:max_concurrent]:
            try:
                run = self.state.create_pipeline_run(
                    pipeline_name="bids_conversion",
                    pipeline_level="session",
                    session_id=session_id,
                    subject_id=subject_id,
                    trigger_reason="workflow",
                )
                
                # Import here to avoid circular imports
                from neuroflow.workers.tasks import run_pipeline
                
                task = run_pipeline.apply_async(
                    kwargs={
                        "run_id": run.id,
                        "pipeline_name": "bids_conversion",
                        "session_id": session_id,
                    },
                    queue="bids",
                )
                
                self.state.update_pipeline_run(
                    run.id,
                    status=PipelineRunStatus.QUEUED,
                    celery_task_id=task.id,
                )
                
                tasks_queued += 1
                log.info(
                    "stage.bids_conversion.queued",
                    session_id=session_id,
                    participant=participant_id,
                    session=session_label,
                    run_id=run.id,
                )
                
            except Exception as e:
                errors.append(f"Failed to queue BIDS for session {session_id}: {str(e)}")
                log.exception(
                    "stage.bids_conversion.queue_error",
                    session_id=session_id,
                    error=str(e),
                )
        
        tasks_skipped = len(eligible_sessions) - tasks_queued
        
        # If sync mode, wait for tasks to complete
        if sync and tasks_queued > 0:
            self._wait_for_pipeline_runs(workflow_run_id, "bids_conversion")
        
        return tasks_queued, tasks_skipped, errors
    
    def _run_qsiprep_stage(
        self,
        workflow_run_id: int,
        sync: bool = False,
        dry_run: bool = False,
    ) -> tuple[int, int, list[str]]:
        """Stage 3: Run QSIPrep for eligible subjects.
        
        Eligible subjects are:
        - Subjects with new sessions that have completed BIDS conversion
        - Subjects flagged for reprocessing (needs_qsiprep=True)
        - Subjects where QSIPrep previously failed (can be retried)
        
        Note: QSIPrep is subject-level - it processes all sessions together.
        
        Returns:
            Tuple of (tasks_queued, tasks_skipped, errors)
        """
        log.info("stage.qsiprep.starting", workflow_run_id=workflow_run_id)
        
        errors: list[str] = []
        tasks_queued = 0
        tasks_skipped = 0
        
        # Get max concurrent (typically 1 for heavy jobs)
        max_concurrent = self._get_max_concurrent("qsiprep")
        
        # Find eligible subjects
        eligible_subjects = self._get_subjects_for_qsiprep()
        
        log.info(
            "stage.qsiprep.eligible",
            count=len(eligible_subjects),
            max_concurrent=max_concurrent,
        )
        
        if dry_run:
            return len(eligible_subjects), 0, errors
        
        for subject_id, participant_id in eligible_subjects[:max_concurrent]:
            try:
                run = self.state.create_pipeline_run(
                    pipeline_name="qsiprep",
                    pipeline_level="subject",
                    subject_id=subject_id,
                    trigger_reason="workflow",
                )
                
                from neuroflow.workers.tasks import run_pipeline
                
                task = run_pipeline.apply_async(
                    kwargs={
                        "run_id": run.id,
                        "pipeline_name": "qsiprep",
                        "subject_id": subject_id,
                    },
                    queue="heavy_processing",
                )
                
                self.state.update_pipeline_run(
                    run.id,
                    status=PipelineRunStatus.QUEUED,
                    celery_task_id=task.id,
                )
                
                tasks_queued += 1
                log.info(
                    "stage.qsiprep.queued",
                    subject_id=subject_id,
                    participant=participant_id,
                    run_id=run.id,
                )
                
            except Exception as e:
                errors.append(f"Failed to queue QSIPrep for subject {subject_id}: {str(e)}")
                log.exception(
                    "stage.qsiprep.queue_error",
                    subject_id=subject_id,
                    error=str(e),
                )
        
        tasks_skipped = len(eligible_subjects) - tasks_queued
        
        if sync and tasks_queued > 0:
            self._wait_for_pipeline_runs(workflow_run_id, "qsiprep")
        
        return tasks_queued, tasks_skipped, errors
    
    def _run_qsirecon_stage(
        self,
        workflow_run_id: int,
        sync: bool = False,
        dry_run: bool = False,
    ) -> tuple[int, int, list[str]]:
        """Stage 4: Run QSIRecon for eligible sessions.
        
        Eligible sessions are:
        - Sessions with completed QSIPrep (subject-level)
        - Sessions without completed QSIRecon
        - Sessions with failed QSIRecon (can be retried)
        
        Returns:
            Tuple of (tasks_queued, tasks_skipped, errors)
        """
        log.info("stage.qsirecon.starting", workflow_run_id=workflow_run_id)
        
        errors: list[str] = []
        tasks_queued = 0
        tasks_skipped = 0
        
        max_concurrent = self._get_max_concurrent("qsirecon")
        eligible_sessions = self._get_sessions_for_qsirecon()
        
        log.info(
            "stage.qsirecon.eligible",
            count=len(eligible_sessions),
            max_concurrent=max_concurrent,
        )
        
        if dry_run:
            return len(eligible_sessions), 0, errors
        
        for session_id, subject_id, participant_id, session_label in eligible_sessions[:max_concurrent]:
            try:
                run = self.state.create_pipeline_run(
                    pipeline_name="qsirecon",
                    pipeline_level="session",
                    session_id=session_id,
                    subject_id=subject_id,
                    trigger_reason="workflow",
                )
                
                from neuroflow.workers.tasks import run_pipeline
                
                task = run_pipeline.apply_async(
                    kwargs={
                        "run_id": run.id,
                        "pipeline_name": "qsirecon",
                        "session_id": session_id,
                        "subject_id": subject_id,
                    },
                    queue="processing",
                )
                
                self.state.update_pipeline_run(
                    run.id,
                    status=PipelineRunStatus.QUEUED,
                    celery_task_id=task.id,
                )
                
                tasks_queued += 1
                log.info(
                    "stage.qsirecon.queued",
                    session_id=session_id,
                    participant=participant_id,
                    session=session_label,
                    run_id=run.id,
                )
                
            except Exception as e:
                errors.append(f"Failed to queue QSIRecon for session {session_id}: {str(e)}")
                log.exception(
                    "stage.qsirecon.queue_error",
                    session_id=session_id,
                    error=str(e),
                )
        
        tasks_skipped = len(eligible_sessions) - tasks_queued
        
        if sync and tasks_queued > 0:
            self._wait_for_pipeline_runs(workflow_run_id, "qsirecon")
        
        return tasks_queued, tasks_skipped, errors
    
    def _run_qsiparc_stage(
        self,
        workflow_run_id: int,
        sync: bool = False,
        dry_run: bool = False,
    ) -> tuple[int, int, list[str]]:
        """Stage 5: Run QSIParc for eligible sessions.
        
        Eligible sessions are:
        - Sessions with completed QSIRecon
        - Sessions without completed QSIParc
        - Sessions with failed QSIParc (can be retried)
        
        Returns:
            Tuple of (tasks_queued, tasks_skipped, errors)
        """
        log.info("stage.qsiparc.starting", workflow_run_id=workflow_run_id)
        
        errors: list[str] = []
        tasks_queued = 0
        tasks_skipped = 0
        
        max_concurrent = self._get_max_concurrent("qsiparc")
        eligible_sessions = self._get_sessions_for_qsiparc()
        
        log.info(
            "stage.qsiparc.eligible",
            count=len(eligible_sessions),
            max_concurrent=max_concurrent,
        )
        
        if dry_run:
            return len(eligible_sessions), 0, errors
        
        for session_id, subject_id, participant_id, session_label in eligible_sessions[:max_concurrent]:
            try:
                run = self.state.create_pipeline_run(
                    pipeline_name="qsiparc",
                    pipeline_level="session",
                    session_id=session_id,
                    subject_id=subject_id,
                    trigger_reason="workflow",
                )
                
                from neuroflow.workers.tasks import run_pipeline
                
                task = run_pipeline.apply_async(
                    kwargs={
                        "run_id": run.id,
                        "pipeline_name": "qsiparc",
                        "session_id": session_id,
                        "subject_id": subject_id,
                    },
                    queue="processing",
                )
                
                self.state.update_pipeline_run(
                    run.id,
                    status=PipelineRunStatus.QUEUED,
                    celery_task_id=task.id,
                )
                
                tasks_queued += 1
                log.info(
                    "stage.qsiparc.queued",
                    session_id=session_id,
                    participant=participant_id,
                    session=session_label,
                    run_id=run.id,
                )
                
            except Exception as e:
                errors.append(f"Failed to queue QSIParc for session {session_id}: {str(e)}")
                log.exception(
                    "stage.qsiparc.queue_error",
                    session_id=session_id,
                    error=str(e),
                )
        
        tasks_skipped = len(eligible_sessions) - tasks_queued
        
        if sync and tasks_queued > 0:
            self._wait_for_pipeline_runs(workflow_run_id, "qsiparc")
        
        return tasks_queued, tasks_skipped, errors
    
    # -------------------------------------------------------------------------
    # Eligibility Queries
    # -------------------------------------------------------------------------
    
    def _get_sessions_for_bids_conversion(self) -> list[tuple[int, int, str, str]]:
        """Get sessions eligible for BIDS conversion.
        
        Returns list of (session_id, subject_id, participant_id, session_label)
        """
        with self.state.get_session() as db:
            # Subquery: sessions with completed or running BIDS conversion
            has_bids = (
                select(PipelineRun.session_id)
                .where(
                    PipelineRun.pipeline_name == "bids_conversion",
                    PipelineRun.status.in_([
                        PipelineRunStatus.COMPLETED,
                        PipelineRunStatus.RUNNING,
                        PipelineRunStatus.QUEUED,
                    ]),
                )
            )
            
            # Query: validated sessions without successful BIDS
            query = (
                select(
                    Session.id,
                    Session.subject_id,
                    Subject.participant_id,
                    Session.session_id,
                )
                .join(Subject)
                .where(
                    Session.status == SessionStatus.VALIDATED,
                    Session.is_valid == True,
                    ~Session.id.in_(has_bids),
                )
                .order_by(Session.discovered_at)
            )
            
            results = db.execute(query).all()
            
            # Also get sessions with failed BIDS that can be retried
            max_retries = self._get_max_retries("bids_conversion")
            
            failed_query = (
                select(
                    Session.id,
                    Session.subject_id,
                    Subject.participant_id,
                    Session.session_id,
                )
                .join(Subject)
                .join(PipelineRun, PipelineRun.session_id == Session.id)
                .where(
                    PipelineRun.pipeline_name == "bids_conversion",
                    PipelineRun.status == PipelineRunStatus.FAILED,
                )
                .group_by(Session.id, Session.subject_id, Subject.participant_id, Session.session_id)
                .having(func.max(PipelineRun.attempt_number) < max_retries)
            )
            
            failed_results = db.execute(failed_query).all()
            
            return list(results) + list(failed_results)
    
    def _get_subjects_for_qsiprep(self) -> list[tuple[int, str]]:
        """Get subjects eligible for QSIPrep.
        
        Returns list of (subject_id, participant_id)
        """
        with self.state.get_session() as db:
            # Subjects with at least one converted session
            has_converted = (
                select(Session.subject_id)
                .where(Session.status == SessionStatus.CONVERTED)
                .distinct()
            )
            
            # Subjects with completed QSIPrep
            has_qsiprep = (
                select(PipelineRun.subject_id)
                .where(
                    PipelineRun.pipeline_name == "qsiprep",
                    PipelineRun.status.in_([
                        PipelineRunStatus.COMPLETED,
                        PipelineRunStatus.RUNNING,
                        PipelineRunStatus.QUEUED,
                    ]),
                )
            )
            
            # Subjects needing QSIPrep
            query = (
                select(Subject.id, Subject.participant_id)
                .where(
                    Subject.id.in_(has_converted),
                    or_(
                        ~Subject.id.in_(has_qsiprep),
                        Subject.needs_qsiprep == True,
                    ),
                )
                .order_by(Subject.updated_at)
            )
            
            results = db.execute(query).all()
            
            # Also check for subjects with new sessions since last QSIPrep
            # (This requires comparing session counts)
            
            return list(results)
    
    def _get_sessions_for_qsirecon(self) -> list[tuple[int, int, str, str]]:
        """Get sessions eligible for QSIRecon.
        
        Returns list of (session_id, subject_id, participant_id, session_label)
        """
        with self.state.get_session() as db:
            # Subjects with completed QSIPrep
            qsiprep_completed = (
                select(PipelineRun.subject_id)
                .where(
                    PipelineRun.pipeline_name == "qsiprep",
                    PipelineRun.status == PipelineRunStatus.COMPLETED,
                )
            )
            
            # Sessions with completed QSIRecon
            has_qsirecon = (
                select(PipelineRun.session_id)
                .where(
                    PipelineRun.pipeline_name == "qsirecon",
                    PipelineRun.status.in_([
                        PipelineRunStatus.COMPLETED,
                        PipelineRunStatus.RUNNING,
                        PipelineRunStatus.QUEUED,
                    ]),
                )
            )
            
            # Sessions ready for QSIRecon
            query = (
                select(
                    Session.id,
                    Session.subject_id,
                    Subject.participant_id,
                    Session.session_id,
                )
                .join(Subject)
                .where(
                    Session.subject_id.in_(qsiprep_completed),
                    Session.status == SessionStatus.CONVERTED,
                    ~Session.id.in_(has_qsirecon),
                )
                .order_by(Session.discovered_at)
            )
            
            results = db.execute(query).all()
            
            return list(results)
    
    def _get_sessions_for_qsiparc(self) -> list[tuple[int, int, str, str]]:
        """Get sessions eligible for QSIParc.
        
        Returns list of (session_id, subject_id, participant_id, session_label)
        """
        with self.state.get_session() as db:
            # Sessions with completed QSIRecon
            qsirecon_completed = (
                select(PipelineRun.session_id)
                .where(
                    PipelineRun.pipeline_name == "qsirecon",
                    PipelineRun.status == PipelineRunStatus.COMPLETED,
                )
            )
            
            # Sessions with completed QSIParc
            has_qsiparc = (
                select(PipelineRun.session_id)
                .where(
                    PipelineRun.pipeline_name == "qsiparc",
                    PipelineRun.status.in_([
                        PipelineRunStatus.COMPLETED,
                        PipelineRunStatus.RUNNING,
                        PipelineRunStatus.QUEUED,
                    ]),
                )
            )
            
            # Sessions ready for QSIParc
            query = (
                select(
                    Session.id,
                    Session.subject_id,
                    Subject.participant_id,
                    Session.session_id,
                )
                .join(Subject)
                .where(
                    Session.id.in_(qsirecon_completed),
                    ~Session.id.in_(has_qsiparc),
                )
                .order_by(Session.discovered_at)
            )
            
            results = db.execute(query).all()
            
            return list(results)
    
    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------
    
    def _create_workflow_run(self) -> int:
        """Create a new workflow run record."""
        from neuroflow.models.workflow_run import WorkflowRun, WorkflowRunStatus
        
        with self.state.get_session() as db:
            run = WorkflowRun(
                status=WorkflowRunStatus.RUNNING,
                trigger_type="scheduled",
                started_at=datetime.now(timezone.utc),
                stages_completed=[],
            )
            db.add(run)
            db.flush()
            
            # Audit log
            self.state._audit(
                db,
                entity_type="workflow_run",
                entity_id=run.id,
                action="created",
                message="Workflow run started",
            )
            
            return run.id
    
    def _update_workflow_run(
        self,
        workflow_run_id: int,
        **kwargs,
    ) -> None:
        """Update a workflow run record."""
        from neuroflow.models.workflow_run import WorkflowRun
        
        with self.state.get_session() as db:
            run = db.get(WorkflowRun, workflow_run_id)
            if run:
                for key, value in kwargs.items():
                    if hasattr(run, key):
                        setattr(run, key, value)
                run.updated_at = datetime.now(timezone.utc)
    
    def _get_max_concurrent(self, pipeline: str) -> int:
        """Get maximum concurrent tasks for a pipeline."""
        defaults = {
            "bids_conversion": 4,
            "qsiprep": 1,
            "qsirecon": 2,
            "qsiparc": 4,
        }
        
        if self._workflow_config and "max_concurrent" in self._workflow_config:
            return self._workflow_config["max_concurrent"].get(
                pipeline, defaults.get(pipeline, 2)
            )
        return defaults.get(pipeline, 2)
    
    def _get_max_retries(self, pipeline: str) -> int:
        """Get maximum retry attempts for a pipeline."""
        default = 3
        
        if self._workflow_config and "retry" in self._workflow_config:
            return self._workflow_config["retry"].get("max_attempts", default)
        return default
    
    def _wait_for_pipeline_runs(
        self,
        workflow_run_id: int,
        pipeline_name: str,
        poll_interval: int = 30,
        timeout: int = 86400,
    ) -> None:
        """Wait for all pipeline runs of a type to complete.
        
        Args:
            workflow_run_id: ID of the workflow run
            pipeline_name: Name of the pipeline to wait for
            poll_interval: Seconds between status checks
            timeout: Maximum seconds to wait
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            with self.state.get_session() as db:
                # Check for any running/queued tasks
                pending = db.execute(
                    select(func.count(PipelineRun.id))
                    .where(
                        PipelineRun.pipeline_name == pipeline_name,
                        PipelineRun.trigger_reason == "workflow",
                        PipelineRun.status.in_([
                            PipelineRunStatus.QUEUED,
                            PipelineRunStatus.RUNNING,
                        ]),
                    )
                ).scalar()
                
                if pending == 0:
                    log.info(
                        "workflow.wait.completed",
                        pipeline=pipeline_name,
                        elapsed=time.time() - start_time,
                    )
                    return
            
            log.debug(
                "workflow.wait.polling",
                pipeline=pipeline_name,
                pending=pending,
            )
            time.sleep(poll_interval)
        
        log.warning(
            "workflow.wait.timeout",
            pipeline=pipeline_name,
            timeout=timeout,
        )
```

## Usage Examples

### Running the Workflow Manually

```python
from neuroflow.config import NeuroflowConfig
from neuroflow.orchestrator.scheduler import WorkflowScheduler

config = NeuroflowConfig.from_yaml("neuroflow.yaml")
scheduler = WorkflowScheduler(config)

# Run complete workflow asynchronously (dispatch and return)
result = scheduler.run_workflow(sync=False)

# Run complete workflow synchronously (wait for completion)
result = scheduler.run_workflow(sync=True)

# Run only a specific stage
from neuroflow.orchestrator.scheduler import WorkflowStage
result = scheduler.run_workflow(force_stage=WorkflowStage.BIDS_CONVERSION)

# Dry run (show what would be done)
result = scheduler.run_workflow(dry_run=True)
```

### Via CLI

```bash
# Run complete workflow
neuroflow workflow run

# Run specific stage
neuroflow workflow run --stage bids_conversion

# Dry run
neuroflow workflow run --dry-run

# Check workflow status
neuroflow workflow status

# List recent workflow runs
neuroflow workflow list
```
