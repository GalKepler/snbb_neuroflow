"""StateManager: handles all database operations with audit logging."""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

import structlog
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import make_transient, sessionmaker

from neuroflow.config import NeuroflowConfig
from neuroflow.models import (
    AuditLog,
    Base,
    PipelineRun,
    PipelineRunStatus,
    Session,
    SessionStatus,
    Subject,
    SubjectStatus,
)

log = structlog.get_logger("state")


class StateManager:
    """Manages all database state and audit logging."""

    def __init__(self, config: NeuroflowConfig):
        self.config = config
        connect_args = {}
        if config.database.url.startswith("sqlite"):
            connect_args["check_same_thread"] = False

        self.engine = create_engine(
            config.database.url,
            connect_args=connect_args,
            pool_pre_ping=True,
        )
        self.SessionFactory = sessionmaker(bind=self.engine)

    def init_db(self) -> None:
        """Create all tables."""
        url = self.config.database.url
        if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
            db_path = Path(url.replace("sqlite:///", "", 1))
            db_path.parent.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(self.engine)
        log.info("database.initialized", url=url)

    def drop_db(self) -> None:
        """Drop all tables."""
        Base.metadata.drop_all(self.engine)
        log.info("database.dropped")

    @contextmanager
    def get_session(self) -> Generator[DBSession, None, None]:
        """Get a database session as a context manager."""
        session = self.SessionFactory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # --- Audit Logging ---

    def _audit(
        self,
        db: DBSession,
        entity_type: str,
        entity_id: int,
        action: str,
        old_value: str | None = None,
        new_value: str | None = None,
        triggered_by: str = "system",
        message: str | None = None,
        details: dict | None = None,
        subject_id: int | None = None,
        session_id: int | None = None,
    ) -> AuditLog:
        """Create an audit log entry."""
        entry = AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            old_value=old_value,
            new_value=new_value,
            triggered_by=triggered_by,
            message=message,
            details=details,
            subject_id=subject_id,
            session_id=session_id,
        )
        db.add(entry)
        return entry

    # --- Subject Operations ---

    def get_or_create_subject(
        self, participant_id: str, recruitment_id: str | None = None
    ) -> Subject:
        """Get an existing subject or create a new one."""
        with self.get_session() as db:
            subject = db.execute(
                select(Subject).where(Subject.participant_id == participant_id)
            ).scalar_one_or_none()

            if subject:
                db.expunge(subject)
                make_transient(subject)
                return subject

            subject = Subject(
                participant_id=participant_id,
                recruitment_id=recruitment_id,
                status=SubjectStatus.PENDING,
            )
            db.add(subject)
            db.flush()

            self._audit(
                db,
                entity_type="subject",
                entity_id=subject.id,
                action="created",
                new_value=participant_id,
                message=f"Subject {participant_id} registered",
                subject_id=subject.id,
            )

            log.info("subject.created", participant_id=participant_id)
            db.expunge(subject)
            make_transient(subject)
            return subject

    def update_subject_status(
        self,
        subject_id: int,
        status: SubjectStatus,
        triggered_by: str = "system",
    ) -> None:
        """Update subject status with audit logging."""
        with self.get_session() as db:
            subject = db.get(Subject, subject_id)
            if not subject:
                return

            old_status = subject.status.value
            subject.status = status
            subject.updated_at = datetime.now(timezone.utc)

            self._audit(
                db,
                entity_type="subject",
                entity_id=subject_id,
                action="status_changed",
                old_value=old_status,
                new_value=status.value,
                triggered_by=triggered_by,
                message=f"Subject status: {old_status} -> {status.value}",
                subject_id=subject_id,
            )

    # --- Session Operations ---

    def register_session(
        self,
        subject_id: int,
        session_id: str,
        dicom_path: str,
        last_dicom_modified: datetime | None = None,
    ) -> Session | None:
        """Register a newly discovered session."""
        with self.get_session() as db:
            # Check if already registered
            existing = db.execute(
                select(Session).where(
                    Session.subject_id == subject_id,
                    Session.session_id == session_id,
                )
            ).scalar_one_or_none()

            if existing:
                log.debug(
                    "session.already_registered",
                    subject_id=subject_id,
                    session_id=session_id,
                )
                return None

            now = datetime.now(timezone.utc)
            session = Session(
                subject_id=subject_id,
                session_id=session_id,
                dicom_path=dicom_path,
                discovered_at=now,
                last_dicom_modified=last_dicom_modified or now,
                status=SessionStatus.DISCOVERED,
            )
            db.add(session)
            db.flush()

            # Update subject session count
            subject = db.get(Subject, subject_id)
            if subject:
                subject.session_count = (
                    db.execute(
                        select(func.count(Session.id)).where(
                            Session.subject_id == subject_id
                        )
                    ).scalar()
                    or 0
                )

            self._audit(
                db,
                entity_type="session",
                entity_id=session.id,
                action="created",
                new_value=session_id,
                message=f"Session {session_id} discovered at {dicom_path}",
                subject_id=subject_id,
                session_id=session.id,
            )

            log.info(
                "session.registered",
                subject_id=subject_id,
                session_id=session_id,
                dicom_path=dicom_path,
            )
            db.expunge(session)
            make_transient(session)
            return session

    def update_session_validation(
        self,
        session_db_id: int,
        is_valid: bool,
        scans_found: dict[str, int],
        validation_message: str,
    ) -> None:
        """Update session with validation results."""
        with self.get_session() as db:
            session = db.get(Session, session_db_id)
            if not session:
                return

            old_status = session.status.value
            session.is_valid = is_valid
            session.scans_found = scans_found
            session.validation_message = validation_message
            session.validated_at = datetime.now(timezone.utc)
            session.status = (
                SessionStatus.VALIDATED if is_valid else SessionStatus.INVALID
            )
            session.updated_at = datetime.now(timezone.utc)

            self._audit(
                db,
                entity_type="session",
                entity_id=session_db_id,
                action="validated",
                old_value=old_status,
                new_value=session.status.value,
                message=validation_message,
                subject_id=session.subject_id,
                session_id=session_db_id,
                details={"scans_found": scans_found, "is_valid": is_valid},
            )

    def update_session_status(
        self,
        session_db_id: int,
        status: SessionStatus,
        triggered_by: str = "system",
        **kwargs: Any,
    ) -> None:
        """Update session status with audit logging."""
        with self.get_session() as db:
            session = db.get(Session, session_db_id)
            if not session:
                return

            old_status = session.status.value
            session.status = status
            session.updated_at = datetime.now(timezone.utc)

            for key, value in kwargs.items():
                if hasattr(session, key):
                    setattr(session, key, value)

            self._audit(
                db,
                entity_type="session",
                entity_id=session_db_id,
                action="status_changed",
                old_value=old_status,
                new_value=status.value,
                triggered_by=triggered_by,
                message=f"Session status: {old_status} -> {status.value}",
                subject_id=session.subject_id,
                session_id=session_db_id,
            )

    # --- Pipeline Run Operations ---

    def create_pipeline_run(
        self,
        pipeline_name: str,
        pipeline_level: str,
        session_id: int | None = None,
        subject_id: int | None = None,
        pipeline_version: str | None = None,
        trigger_reason: str | None = None,
        trigger_session_id: int | None = None,
    ) -> PipelineRun:
        """Create a new pipeline run record."""
        with self.get_session() as db:
            # Determine attempt number
            attempt = 1
            if session_id:
                prev = db.execute(
                    select(func.max(PipelineRun.attempt_number)).where(
                        PipelineRun.session_id == session_id,
                        PipelineRun.pipeline_name == pipeline_name,
                    )
                ).scalar()
                if prev:
                    attempt = prev + 1

            now = datetime.now(timezone.utc)
            run = PipelineRun(
                session_id=session_id,
                subject_id=subject_id,
                pipeline_name=pipeline_name,
                pipeline_version=pipeline_version,
                pipeline_level=pipeline_level,
                attempt_number=attempt,
                status=PipelineRunStatus.QUEUED,
                queued_at=now,
                trigger_reason=trigger_reason,
                trigger_session_id=trigger_session_id,
            )
            db.add(run)
            db.flush()

            self._audit(
                db,
                entity_type="pipeline_run",
                entity_id=run.id,
                action="created",
                new_value=pipeline_name,
                message=f"Pipeline {pipeline_name} (attempt {attempt}) queued",
                subject_id=subject_id,
                session_id=session_id,
            )

            log.info(
                "pipeline_run.created",
                run_id=run.id,
                pipeline=pipeline_name,
                attempt=attempt,
            )
            db.expunge(run)
            make_transient(run)
            return run

    def update_pipeline_run(
        self,
        run_id: int,
        status: PipelineRunStatus,
        celery_task_id: str | None = None,
        exit_code: int | None = None,
        output_path: str | None = None,
        error_message: str | None = None,
        error_traceback: str | None = None,
        metrics: dict | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        """Update a pipeline run with results."""
        with self.get_session() as db:
            run = db.get(PipelineRun, run_id)
            if not run:
                return

            old_status = run.status.value
            now = datetime.now(timezone.utc)

            run.status = status
            run.updated_at = now

            if celery_task_id is not None:
                run.celery_task_id = celery_task_id
            if exit_code is not None:
                run.exit_code = exit_code
            if output_path is not None:
                run.output_path = output_path
            if error_message is not None:
                run.error_message = error_message
            if error_traceback is not None:
                run.error_traceback = error_traceback
            if metrics is not None:
                run.metrics = metrics
            if duration_seconds is not None:
                run.duration_seconds = duration_seconds

            if status == PipelineRunStatus.RUNNING:
                run.started_at = now
            elif status in (
                PipelineRunStatus.COMPLETED,
                PipelineRunStatus.FAILED,
                PipelineRunStatus.CANCELLED,
            ):
                run.completed_at = now
                if run.started_at and duration_seconds is None:
                    run.duration_seconds = (now - run.started_at).total_seconds()

            # Update session pipeline counts
            if run.session_id:
                session = db.get(Session, run.session_id)
                if session:
                    session.pipelines_completed = (
                        db.execute(
                            select(func.count(PipelineRun.id)).where(
                                PipelineRun.session_id == run.session_id,
                                PipelineRun.status == PipelineRunStatus.COMPLETED,
                            )
                        ).scalar()
                        or 0
                    )
                    session.pipelines_failed = (
                        db.execute(
                            select(func.count(PipelineRun.id)).where(
                                PipelineRun.session_id == run.session_id,
                                PipelineRun.status == PipelineRunStatus.FAILED,
                            )
                        ).scalar()
                        or 0
                    )
                    session.pipelines_pending = (
                        db.execute(
                            select(func.count(PipelineRun.id)).where(
                                PipelineRun.session_id == run.session_id,
                                PipelineRun.status.in_(
                                    [
                                        PipelineRunStatus.PENDING,
                                        PipelineRunStatus.QUEUED,
                                        PipelineRunStatus.RUNNING,
                                    ]
                                ),
                            )
                        ).scalar()
                        or 0
                    )

            self._audit(
                db,
                entity_type="pipeline_run",
                entity_id=run_id,
                action="status_changed",
                old_value=old_status,
                new_value=status.value,
                message=f"Pipeline run {run_id}: {old_status} -> {status.value}",
                subject_id=run.subject_id,
                session_id=run.session_id,
                details={
                    "exit_code": exit_code,
                    "error_message": error_message,
                },
            )

    def find_stale_runs(self, hours: int = 24) -> list[PipelineRun]:
        """Find pipeline runs that appear stuck."""
        with self.get_session() as db:
            cutoff = datetime.now(timezone.utc)
            from datetime import timedelta

            cutoff = cutoff - timedelta(hours=hours)

            runs = (
                db.execute(
                    select(PipelineRun).where(
                        PipelineRun.status == PipelineRunStatus.RUNNING,
                        PipelineRun.started_at < cutoff,
                    )
                )
                .scalars()
                .all()
            )
            return list(runs)

    def get_session_by_ids(
        self, participant_id: str, session_id: str
    ) -> Session | None:
        """Look up a session by participant and session IDs."""
        with self.get_session() as db:
            result = db.execute(
                select(Session)
                .join(Subject)
                .where(
                    Subject.participant_id == participant_id,
                    Session.session_id == session_id,
                )
            ).scalar_one_or_none()
            if result:
                db.expunge(result)
                make_transient(result)
            return result
