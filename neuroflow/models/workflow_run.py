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
