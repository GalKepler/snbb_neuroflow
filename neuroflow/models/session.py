"""Session model."""

from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .pipeline_run import PipelineRun
    from .subject import Subject


class SessionStatus(str, Enum):
    DISCOVERED = "discovered"
    VALIDATING = "validating"
    VALIDATED = "validated"
    INVALID = "invalid"
    CONVERTING = "converting"
    CONVERTED = "converted"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXCLUDED = "excluded"


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"
    __table_args__ = (UniqueConstraint("subject_id", "session_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(64))

    dicom_path: Mapped[Optional[str]] = mapped_column(String(1024))
    bids_path: Mapped[Optional[str]] = mapped_column(String(1024))

    discovered_at: Mapped[datetime] = mapped_column(DateTime)
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_dicom_modified: Mapped[Optional[datetime]] = mapped_column(DateTime)

    is_valid: Mapped[Optional[bool]] = mapped_column(Boolean)
    validation_message: Mapped[Optional[str]] = mapped_column(Text)
    scans_found: Mapped[Optional[dict]] = mapped_column(JSON)

    status: Mapped[SessionStatus] = mapped_column(default=SessionStatus.DISCOVERED, index=True)

    pipelines_pending: Mapped[int] = mapped_column(Integer, default=0)
    pipelines_completed: Mapped[int] = mapped_column(Integer, default=0)
    pipelines_failed: Mapped[int] = mapped_column(Integer, default=0)

    bids_suffixes: Mapped[Optional[list]] = mapped_column(JSON)

    acquisition_date: Mapped[Optional[date]] = mapped_column(Date)
    scanner_id: Mapped[Optional[str]] = mapped_column(String(64))
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON)

    # Workflow tracking
    needs_rerun: Mapped[bool] = mapped_column(Boolean, default=False)
    last_failure_reason: Mapped[Optional[str]] = mapped_column(Text)
    last_bids_conversion_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_qsirecon_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_qsiparc_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    subject: Mapped["Subject"] = relationship(back_populates="sessions")
    pipeline_runs: Mapped[list["PipelineRun"]] = relationship(
        back_populates="session", foreign_keys="PipelineRun.session_id"
    )
