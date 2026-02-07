# State Machine and Models

## Overview

This document describes the state machines for sessions and subjects, the new WorkflowRun model, and the enhanced state transitions.

## Session State Machine

```
                              ┌──────────────────────────────────────────────┐
                              │           SESSION STATE MACHINE              │
                              └──────────────────────────────────────────────┘

    ┌───────────┐     ┌───────────┐     ┌───────────┐     ┌───────────┐
    │ DISCOVERED│────▶│VALIDATING │────▶│ VALIDATED │────▶│CONVERTING │
    └───────────┘     └───────────┘     └─────┬─────┘     └─────┬─────┘
                                              │                 │
                                              │ (invalid)       │ (success)
                                              ▼                 ▼
                                        ┌───────────┐     ┌───────────┐
                                        │  INVALID  │     │ CONVERTED │
                                        └───────────┘     └─────┬─────┘
                                                                │
                                                                ▼
                              ┌───────────┐     ┌───────────────────────────┐
                              │  FAILED   │◀────│       PROCESSING          │
                              └───────────┘     └─────────────┬─────────────┘
                                    ▲                         │
                                    │      (all complete)     ▼
                                    │                   ┌───────────┐
                                    └───────────────────│ COMPLETED │
                                      (retry exhausted) └───────────┘
```

### Session Status Definitions

| Status | Description | Transitions To |
|--------|-------------|----------------|
| `DISCOVERED` | Session folder found in DICOM directory | `VALIDATING` |
| `VALIDATING` | Validation in progress | `VALIDATED`, `INVALID` |
| `VALIDATED` | Session passes protocol validation | `CONVERTING`, `EXCLUDED` |
| `INVALID` | Session fails protocol validation | `EXCLUDED` |
| `CONVERTING` | BIDS conversion in progress | `CONVERTED`, `FAILED` |
| `CONVERTED` | BIDS conversion complete | `PROCESSING` |
| `PROCESSING` | One or more pipelines running | `COMPLETED`, `FAILED` |
| `COMPLETED` | All pipelines complete | - |
| `FAILED` | Pipeline failed (retries exhausted) | `PROCESSING` (manual retry) |
| `EXCLUDED` | Manually excluded from processing | - |

## Subject State Machine

```
                              ┌──────────────────────────────────────────────┐
                              │           SUBJECT STATE MACHINE              │
                              └──────────────────────────────────────────────┘

    ┌───────────┐     ┌───────────┐     ┌───────────┐
    │  PENDING  │────▶│PROCESSING │────▶│ COMPLETED │
    └───────────┘     └─────┬─────┘     └───────────┘
                            │
                            │ (pipeline failed)
                            ▼
                      ┌───────────┐
                      │  FAILED   │
                      └───────────┘
```

### Subject Status Definitions

| Status | Description | Transitions To |
|--------|-------------|----------------|
| `PENDING` | Subject registered, no processing started | `PROCESSING` |
| `PROCESSING` | Subject-level pipelines running | `COMPLETED`, `FAILED` |
| `COMPLETED` | All subject-level pipelines complete | `PROCESSING` (new session) |
| `FAILED` | Subject-level pipeline failed | `PROCESSING` (retry) |

## New Model: WorkflowRun

### File: `neuroflow/models/workflow_run.py`

```python
"""WorkflowRun model for tracking workflow executions."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class WorkflowRunStatus(str, Enum):
    """Status of a workflow run."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowRun(Base, TimestampMixin):
    """Tracks a complete workflow execution cycle.
    
    A workflow run represents a single execution of the master workflow,
    which processes all pending work through the pipeline stages.
    """
    __tablename__ = "workflow_runs"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    
    # Status
    status: Mapped[WorkflowRunStatus] = mapped_column(
        String(32),
        default=WorkflowRunStatus.PENDING,
        index=True,
    )
    
    # Trigger info
    trigger_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )  # "scheduled", "manual", "event"
    trigger_details: Mapped[Optional[dict]] = mapped_column(JSON)
    
    # Timing
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Stage tracking
    stages_completed: Mapped[list] = mapped_column(JSON, default=list)
    current_stage: Mapped[Optional[str]] = mapped_column(String(64))
    
    # Metrics - count of items processed in each stage
    sessions_discovered: Mapped[int] = mapped_column(Integer, default=0)
    sessions_converted: Mapped[int] = mapped_column(Integer, default=0)
    subjects_preprocessed: Mapped[int] = mapped_column(Integer, default=0)
    sessions_reconstructed: Mapped[int] = mapped_column(Integer, default=0)
    sessions_parcellated: Mapped[int] = mapped_column(Integer, default=0)
    
    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    error_stage: Mapped[Optional[str]] = mapped_column(String(64))
    error_details: Mapped[Optional[dict]] = mapped_column(JSON)
    
    # Relationships
    pipeline_runs: Mapped[list["PipelineRun"]] = relationship(
        back_populates="workflow_run",
        foreign_keys="PipelineRun.workflow_run_id",
    )
    
    def __repr__(self) -> str:
        return f"<WorkflowRun(id={self.id}, status={self.status.value})>"
    
    @property
    def duration_seconds(self) -> float | None:
        """Calculate workflow duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    @property
    def total_pipeline_runs(self) -> int:
        """Total number of pipeline runs in this workflow."""
        return len(self.pipeline_runs) if self.pipeline_runs else 0
    
    @property
    def successful_runs(self) -> int:
        """Number of successful pipeline runs."""
        if not self.pipeline_runs:
            return 0
        from neuroflow.models.pipeline_run import PipelineRunStatus
        return sum(1 for r in self.pipeline_runs if r.status == PipelineRunStatus.COMPLETED)
    
    @property
    def failed_runs(self) -> int:
        """Number of failed pipeline runs."""
        if not self.pipeline_runs:
            return 0
        from neuroflow.models.pipeline_run import PipelineRunStatus
        return sum(1 for r in self.pipeline_runs if r.status == PipelineRunStatus.FAILED)
```

## Modified Model: PipelineRun

Add relationship to WorkflowRun:

```python
# In neuroflow/models/pipeline_run.py

# Add to imports
from sqlalchemy import ForeignKey

# Add new column
workflow_run_id: Mapped[Optional[int]] = mapped_column(
    ForeignKey("workflow_runs.id"),
    index=True,
)

# Add relationship
workflow_run: Mapped[Optional["WorkflowRun"]] = relationship(
    back_populates="pipeline_runs",
    foreign_keys=[workflow_run_id],
)
```

## Modified Model: Session

Add processing flags:

```python
# In neuroflow/models/session.py

# Add new columns
needs_rerun: Mapped[bool] = mapped_column(Boolean, default=False)
last_failure_reason: Mapped[Optional[str]] = mapped_column(Text)
last_bids_conversion_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
last_qsirecon_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
last_qsiparc_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
```

## Modified Model: Subject

Add processing flags:

```python
# In neuroflow/models/subject.py

# Add new columns
needs_qsiprep: Mapped[bool] = mapped_column(Boolean, default=False)
qsiprep_last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
sessions_at_last_qsiprep: Mapped[int] = mapped_column(Integer, default=0)
```

## Update Models __init__.py

```python
# neuroflow/models/__init__.py

from .audit import AuditLog
from .base import Base, TimestampMixin
from .pipeline_run import PipelineRun, PipelineRunStatus
from .session import Session, SessionStatus
from .subject import Subject, SubjectStatus
from .workflow_run import WorkflowRun, WorkflowRunStatus

__all__ = [
    "Base",
    "TimestampMixin",
    "Subject",
    "SubjectStatus",
    "Session",
    "SessionStatus",
    "PipelineRun",
    "PipelineRunStatus",
    "WorkflowRun",
    "WorkflowRunStatus",
    "AuditLog",
]
```

## Database Migration

### File: `alembic/versions/001_add_workflow_runs.py`

```python
"""Add workflow_runs table and enhance existing models.

Revision ID: 001_add_workflow_runs
Revises: 
Create Date: 2024-XX-XX
"""

from alembic import op
import sqlalchemy as sa

revision = '001_add_workflow_runs'
down_revision = None  # Or previous revision
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create workflow_runs table
    op.create_table(
        'workflow_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('status', sa.String(32), nullable=False, default='pending'),
        sa.Column('trigger_type', sa.String(32), nullable=False),
        sa.Column('trigger_details', sa.JSON()),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('stages_completed', sa.JSON(), default=[]),
        sa.Column('current_stage', sa.String(64)),
        sa.Column('sessions_discovered', sa.Integer(), default=0),
        sa.Column('sessions_converted', sa.Integer(), default=0),
        sa.Column('subjects_preprocessed', sa.Integer(), default=0),
        sa.Column('sessions_reconstructed', sa.Integer(), default=0),
        sa.Column('sessions_parcellated', sa.Integer(), default=0),
        sa.Column('error_message', sa.Text()),
        sa.Column('error_stage', sa.String(64)),
        sa.Column('error_details', sa.JSON()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_workflow_runs_status', 'workflow_runs', ['status'])
    op.create_index('idx_workflow_runs_started_at', 'workflow_runs', ['started_at'])
    
    # Add workflow_run_id to pipeline_runs
    op.add_column(
        'pipeline_runs',
        sa.Column('workflow_run_id', sa.Integer(), sa.ForeignKey('workflow_runs.id'))
    )
    op.create_index('idx_pipeline_runs_workflow', 'pipeline_runs', ['workflow_run_id'])
    
    # Add new columns to sessions
    op.add_column('sessions', sa.Column('needs_rerun', sa.Boolean(), default=False))
    op.add_column('sessions', sa.Column('last_failure_reason', sa.Text()))
    op.add_column('sessions', sa.Column('last_bids_conversion_at', sa.DateTime(timezone=True)))
    op.add_column('sessions', sa.Column('last_qsirecon_at', sa.DateTime(timezone=True)))
    op.add_column('sessions', sa.Column('last_qsiparc_at', sa.DateTime(timezone=True)))
    
    # Add new columns to subjects
    op.add_column('subjects', sa.Column('needs_qsiprep', sa.Boolean(), default=False))
    op.add_column('subjects', sa.Column('qsiprep_last_run_at', sa.DateTime(timezone=True)))
    op.add_column('subjects', sa.Column('sessions_at_last_qsiprep', sa.Integer(), default=0))


def downgrade() -> None:
    # Remove columns from subjects
    op.drop_column('subjects', 'sessions_at_last_qsiprep')
    op.drop_column('subjects', 'qsiprep_last_run_at')
    op.drop_column('subjects', 'needs_qsiprep')
    
    # Remove columns from sessions
    op.drop_column('sessions', 'last_qsiparc_at')
    op.drop_column('sessions', 'last_qsirecon_at')
    op.drop_column('sessions', 'last_bids_conversion_at')
    op.drop_column('sessions', 'last_failure_reason')
    op.drop_column('sessions', 'needs_rerun')
    
    # Remove workflow_run_id from pipeline_runs
    op.drop_index('idx_pipeline_runs_workflow')
    op.drop_column('pipeline_runs', 'workflow_run_id')
    
    # Drop workflow_runs table
    op.drop_index('idx_workflow_runs_started_at')
    op.drop_index('idx_workflow_runs_status')
    op.drop_table('workflow_runs')
```

## StateManager Updates

### Add workflow run operations to `neuroflow/core/state.py`:

```python
# Add to StateManager class

def create_workflow_run(
    self,
    trigger_type: str,
    trigger_details: dict | None = None,
) -> WorkflowRun:
    """Create a new workflow run record."""
    from neuroflow.models.workflow_run import WorkflowRun, WorkflowRunStatus
    
    with self.get_session() as db:
        run = WorkflowRun(
            status=WorkflowRunStatus.RUNNING,
            trigger_type=trigger_type,
            trigger_details=trigger_details,
            started_at=datetime.now(timezone.utc),
            stages_completed=[],
        )
        db.add(run)
        db.flush()
        
        self._audit(
            db,
            entity_type="workflow_run",
            entity_id=run.id,
            action="created",
            new_value=trigger_type,
            message=f"Workflow run started ({trigger_type})",
        )
        
        log.info("workflow_run.created", workflow_run_id=run.id, trigger_type=trigger_type)
        
        db.expunge(run)
        make_transient(run)
        return run

def update_workflow_run(
    self,
    workflow_run_id: int,
    status: WorkflowRunStatus | None = None,
    current_stage: str | None = None,
    stages_completed: list[str] | None = None,
    error_message: str | None = None,
    error_stage: str | None = None,
    **metrics,
) -> None:
    """Update a workflow run record."""
    from neuroflow.models.workflow_run import WorkflowRun
    
    with self.get_session() as db:
        run = db.get(WorkflowRun, workflow_run_id)
        if not run:
            return
        
        old_status = run.status.value if status else None
        
        if status:
            run.status = status
        if current_stage is not None:
            run.current_stage = current_stage
        if stages_completed is not None:
            run.stages_completed = stages_completed
        if error_message:
            run.error_message = error_message
        if error_stage:
            run.error_stage = error_stage
        
        # Update metrics
        for key, value in metrics.items():
            if hasattr(run, key):
                setattr(run, key, value)
        
        if status in (WorkflowRunStatus.COMPLETED, WorkflowRunStatus.FAILED, WorkflowRunStatus.CANCELLED):
            run.completed_at = datetime.now(timezone.utc)
        
        run.updated_at = datetime.now(timezone.utc)
        
        if old_status:
            self._audit(
                db,
                entity_type="workflow_run",
                entity_id=workflow_run_id,
                action="status_changed",
                old_value=old_status,
                new_value=status.value,
                message=f"Workflow status: {old_status} -> {status.value}",
            )

def get_latest_workflow_run(self) -> WorkflowRun | None:
    """Get the most recent workflow run."""
    from neuroflow.models.workflow_run import WorkflowRun
    
    with self.get_session() as db:
        run = db.execute(
            select(WorkflowRun).order_by(WorkflowRun.started_at.desc()).limit(1)
        ).scalar_one_or_none()
        
        if run:
            db.expunge(run)
            make_transient(run)
        return run

def get_workflow_run_history(
    self,
    limit: int = 10,
    status: WorkflowRunStatus | None = None,
) -> list[WorkflowRun]:
    """Get workflow run history."""
    from neuroflow.models.workflow_run import WorkflowRun
    
    with self.get_session() as db:
        query = select(WorkflowRun).order_by(WorkflowRun.started_at.desc())
        
        if status:
            query = query.where(WorkflowRun.status == status)
        
        query = query.limit(limit)
        
        runs = db.execute(query).scalars().all()
        
        for run in runs:
            db.expunge(run)
            make_transient(run)
        
        return list(runs)

def mark_session_for_rerun(
    self,
    session_id: int,
    reason: str,
) -> None:
    """Mark a session for reprocessing."""
    with self.get_session() as db:
        session = db.get(Session, session_id)
        if session:
            session.needs_rerun = True
            session.last_failure_reason = reason
            session.updated_at = datetime.now(timezone.utc)
            
            self._audit(
                db,
                entity_type="session",
                entity_id=session_id,
                action="marked_for_rerun",
                message=reason,
                session_id=session_id,
                subject_id=session.subject_id,
            )

def mark_subject_for_qsiprep(
    self,
    subject_id: int,
    reason: str = "new_session",
) -> None:
    """Mark a subject for QSIPrep reprocessing."""
    with self.get_session() as db:
        subject = db.get(Subject, subject_id)
        if subject:
            subject.needs_qsiprep = True
            subject.updated_at = datetime.now(timezone.utc)
            
            self._audit(
                db,
                entity_type="subject",
                entity_id=subject_id,
                action="marked_for_qsiprep",
                message=reason,
                subject_id=subject_id,
            )
```

## State Transition Logic

### Automatic Transitions

The following transitions happen automatically:

1. **DISCOVERED → VALIDATING**: When validation task starts
2. **VALIDATING → VALIDATED/INVALID**: Based on validation result
3. **VALIDATED → CONVERTING**: When BIDS conversion task starts
4. **CONVERTING → CONVERTED/FAILED**: Based on conversion result
5. **CONVERTED → PROCESSING**: When first pipeline task starts
6. **PROCESSING → COMPLETED**: When all pipelines complete successfully
7. **PROCESSING → FAILED**: When a pipeline fails and retries exhausted

### Trigger Conditions for Marking Rerun

```python
def should_rerun_qsiprep(subject: Subject) -> bool:
    """Check if subject needs QSIPrep rerun."""
    # Flag is set
    if subject.needs_qsiprep:
        return True
    
    # New sessions since last run
    if subject.session_count > subject.sessions_at_last_qsiprep:
        return True
    
    return False

def should_rerun_session_pipeline(
    session: Session,
    pipeline_name: str,
) -> bool:
    """Check if a session pipeline should be rerun."""
    # Explicit flag
    if session.needs_rerun:
        return True
    
    # Check for failed run that can be retried
    # ... (check retry count against max)
    
    return False
```
