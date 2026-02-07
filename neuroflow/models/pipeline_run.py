"""PipelineRun model."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .session import Session
    from .subject import Subject
    from .workflow_run import WorkflowRun


class PipelineRunStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class PipelineRun(Base, TimestampMixin):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)

    session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sessions.id"), index=True
    )
    subject_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("subjects.id"), index=True
    )

    # Workflow tracking
    workflow_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("workflow_runs.id"), index=True
    )

    pipeline_name: Mapped[str] = mapped_column(String(64), index=True)
    pipeline_version: Mapped[Optional[str]] = mapped_column(String(32))
    pipeline_level: Mapped[str] = mapped_column(String(16))  # "session" or "subject"

    sessions_included: Mapped[Optional[list]] = mapped_column(JSON)

    attempt_number: Mapped[int] = mapped_column(Integer, default=1)

    status: Mapped[PipelineRunStatus] = mapped_column(
        default=PipelineRunStatus.PENDING, index=True
    )

    queued_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)

    output_path: Mapped[Optional[str]] = mapped_column(String(1024))
    exit_code: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    error_traceback: Mapped[Optional[str]] = mapped_column(Text)

    log_path: Mapped[Optional[str]] = mapped_column(String(1024))
    metrics: Mapped[Optional[dict]] = mapped_column(JSON)

    celery_task_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    trigger_reason: Mapped[Optional[str]] = mapped_column(String(32))
    trigger_session_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sessions.id"))

    # Relationships
    session: Mapped[Optional["Session"]] = relationship(
        back_populates="pipeline_runs", foreign_keys=[session_id]
    )
    subject: Mapped[Optional["Subject"]] = relationship(back_populates="pipeline_runs")
    workflow_run: Mapped[Optional["WorkflowRun"]] = relationship(
        back_populates="pipeline_runs", foreign_keys=[workflow_run_id]
    )
