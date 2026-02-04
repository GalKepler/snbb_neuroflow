"""AuditLog model."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )

    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)

    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    old_value: Mapped[Optional[str]] = mapped_column(Text)
    new_value: Mapped[Optional[str]] = mapped_column(Text)

    triggered_by: Mapped[Optional[str]] = mapped_column(String(64))
    user_id: Mapped[Optional[str]] = mapped_column(String(64))

    message: Mapped[Optional[str]] = mapped_column(Text)
    details: Mapped[Optional[dict]] = mapped_column(JSON)

    subject_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("subjects.id"), index=True
    )
    session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sessions.id"), index=True
    )
