"""Tests for SQLAlchemy models."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as DBSession, sessionmaker

from neuroflow.models import (
    Base,
    PipelineRun,
    PipelineRunStatus,
    Session,
    SessionStatus,
    Subject,
    SubjectStatus,
)


@pytest.fixture
def db_session():
    """Create an in-memory database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    yield session
    session.close()


def test_create_subject(db_session: DBSession):
    """Test creating a subject."""
    subject = Subject(
        participant_id="sub-001",
        status=SubjectStatus.PENDING,
    )
    db_session.add(subject)
    db_session.commit()

    result = db_session.execute(
        select(Subject).where(Subject.participant_id == "sub-001")
    ).scalar_one()
    assert result.participant_id == "sub-001"
    assert result.status == SubjectStatus.PENDING
    assert result.session_count == 0


def test_subject_session_relationship(db_session: DBSession):
    """Test subject-session relationship."""
    from datetime import datetime, timezone

    subject = Subject(participant_id="sub-001")
    db_session.add(subject)
    db_session.flush()

    session = Session(
        subject_id=subject.id,
        session_id="ses-baseline",
        discovered_at=datetime.now(timezone.utc),
    )
    db_session.add(session)
    db_session.commit()

    result = db_session.execute(
        select(Subject).where(Subject.participant_id == "sub-001")
    ).scalar_one()
    assert len(result.sessions) == 1
    assert result.sessions[0].session_id == "ses-baseline"


def test_session_unique_constraint(db_session: DBSession):
    """Test that subject_id + session_id must be unique."""
    from datetime import datetime, timezone
    from sqlalchemy.exc import IntegrityError

    subject = Subject(participant_id="sub-001")
    db_session.add(subject)
    db_session.flush()

    now = datetime.now(timezone.utc)
    s1 = Session(subject_id=subject.id, session_id="ses-baseline", discovered_at=now)
    s2 = Session(subject_id=subject.id, session_id="ses-baseline", discovered_at=now)

    db_session.add(s1)
    db_session.flush()
    db_session.add(s2)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_pipeline_run_statuses(db_session: DBSession):
    """Test pipeline run status values."""
    assert PipelineRunStatus.PENDING.value == "pending"
    assert PipelineRunStatus.QUEUED.value == "queued"
    assert PipelineRunStatus.RUNNING.value == "running"
    assert PipelineRunStatus.COMPLETED.value == "completed"
    assert PipelineRunStatus.FAILED.value == "failed"
    assert PipelineRunStatus.CANCELLED.value == "cancelled"
    assert PipelineRunStatus.SKIPPED.value == "skipped"


def test_session_statuses():
    """Test session status values."""
    assert SessionStatus.DISCOVERED.value == "discovered"
    assert SessionStatus.VALIDATED.value == "validated"
    assert SessionStatus.INVALID.value == "invalid"
    assert SessionStatus.CONVERTING.value == "converting"
    assert SessionStatus.COMPLETED.value == "completed"
    assert SessionStatus.EXCLUDED.value == "excluded"
