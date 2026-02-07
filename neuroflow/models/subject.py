"""Subject model."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .pipeline_run import PipelineRun
    from .session import Session


class SubjectStatus(str, Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    VALID = "valid"
    INVALID = "invalid"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Subject(Base, TimestampMixin):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    recruitment_id: Mapped[Optional[str]] = mapped_column(String(128))

    status: Mapped[SubjectStatus] = mapped_column(default=SubjectStatus.PENDING)

    session_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_pipelines: Mapped[int] = mapped_column(Integer, default=0)
    failed_pipelines: Mapped[int] = mapped_column(Integer, default=0)

    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON)

    # Workflow tracking
    needs_qsiprep: Mapped[bool] = mapped_column(Boolean, default=False)
    qsiprep_last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sessions_at_last_qsiprep: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    sessions: Mapped[list["Session"]] = relationship(back_populates="subject")
    pipeline_runs: Mapped[list["PipelineRun"]] = relationship(back_populates="subject")
