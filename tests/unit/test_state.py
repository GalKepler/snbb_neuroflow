"""Tests for StateManager."""

import pytest

from neuroflow.core.state import StateManager
from neuroflow.models import (
    AuditLog,
    PipelineRun,
    PipelineRunStatus,
    Session,
    SessionStatus,
    Subject,
    SubjectStatus,
)


def test_create_subject(state: StateManager):
    """Test creating a new subject."""
    subject = state.get_or_create_subject("sub-001")
    assert subject.participant_id == "sub-001"
    assert subject.id is not None


def test_get_existing_subject(state: StateManager):
    """Test retrieving an existing subject."""
    sub1 = state.get_or_create_subject("sub-001")
    sub2 = state.get_or_create_subject("sub-001")
    assert sub1.id == sub2.id


def test_register_session(state: StateManager):
    """Test registering a new session."""
    subject = state.get_or_create_subject("sub-001")
    session = state.register_session(
        subject_id=subject.id,
        session_id="ses-baseline",
        dicom_path="/data/sub-001/ses-baseline",
    )
    assert session is not None
    assert session.session_id == "ses-baseline"
    assert session.status == SessionStatus.DISCOVERED


def test_register_duplicate_session(state: StateManager):
    """Test that duplicate session registration returns None."""
    subject = state.get_or_create_subject("sub-001")
    state.register_session(
        subject_id=subject.id,
        session_id="ses-baseline",
        dicom_path="/data/sub-001/ses-baseline",
    )
    duplicate = state.register_session(
        subject_id=subject.id,
        session_id="ses-baseline",
        dicom_path="/data/sub-001/ses-baseline",
    )
    assert duplicate is None


def test_update_session_validation(state: StateManager):
    """Test updating session with validation results."""
    subject = state.get_or_create_subject("sub-001")
    session = state.register_session(
        subject_id=subject.id,
        session_id="ses-baseline",
        dicom_path="/data/sub-001/ses-baseline",
    )

    state.update_session_validation(
        session_db_id=session.id,
        is_valid=True,
        scans_found={"T1w": 176, "FLAIR": 48},
        validation_message="Session valid",
    )

    with state.get_session() as db:
        updated = db.get(Session, session.id)
        assert updated.status == SessionStatus.VALIDATED
        assert updated.is_valid is True
        assert updated.scans_found == {"T1w": 176, "FLAIR": 48}


def test_create_pipeline_run(state: StateManager):
    """Test creating a pipeline run."""
    subject = state.get_or_create_subject("sub-001")
    session = state.register_session(
        subject_id=subject.id,
        session_id="ses-baseline",
        dicom_path="/data/sub-001/ses-baseline",
    )

    run = state.create_pipeline_run(
        pipeline_name="freesurfer",
        pipeline_level="session",
        session_id=session.id,
        subject_id=subject.id,
        pipeline_version="7.4.1",
    )
    assert run.pipeline_name == "freesurfer"
    assert run.attempt_number == 1
    assert run.status == PipelineRunStatus.QUEUED


def test_update_pipeline_run(state: StateManager):
    """Test updating a pipeline run status."""
    subject = state.get_or_create_subject("sub-001")
    session = state.register_session(
        subject_id=subject.id,
        session_id="ses-baseline",
        dicom_path="/data/sub-001/ses-baseline",
    )
    run = state.create_pipeline_run(
        pipeline_name="freesurfer",
        pipeline_level="session",
        session_id=session.id,
        subject_id=subject.id,
    )

    state.update_pipeline_run(
        run_id=run.id,
        status=PipelineRunStatus.RUNNING,
    )

    with state.get_session() as db:
        updated = db.get(PipelineRun, run.id)
        assert updated.status == PipelineRunStatus.RUNNING
        assert updated.started_at is not None


def test_pipeline_run_completion_updates_counts(state: StateManager):
    """Test that completing a pipeline run updates session counts."""
    subject = state.get_or_create_subject("sub-001")
    session = state.register_session(
        subject_id=subject.id,
        session_id="ses-baseline",
        dicom_path="/data/sub-001/ses-baseline",
    )
    run = state.create_pipeline_run(
        pipeline_name="freesurfer",
        pipeline_level="session",
        session_id=session.id,
        subject_id=subject.id,
    )

    state.update_pipeline_run(
        run_id=run.id,
        status=PipelineRunStatus.COMPLETED,
        exit_code=0,
    )

    with state.get_session() as db:
        updated_session = db.get(Session, session.id)
        assert updated_session.pipelines_completed == 1
        assert updated_session.pipelines_failed == 0


def test_audit_log_created(state: StateManager):
    """Test that audit log entries are created."""
    subject = state.get_or_create_subject("sub-001")

    from sqlalchemy import select

    with state.get_session() as db:
        entries = db.execute(
            select(AuditLog).where(AuditLog.entity_type == "subject")
        ).scalars().all()
        assert len(entries) >= 1
        assert entries[0].action == "created"
        assert entries[0].new_value == "sub-001"


def test_update_subject_status(state: StateManager):
    """Test updating subject status."""
    subject = state.get_or_create_subject("sub-001")
    state.update_subject_status(subject.id, SubjectStatus.PROCESSING)

    with state.get_session() as db:
        updated = db.get(Subject, subject.id)
        assert updated.status == SubjectStatus.PROCESSING


def test_get_session_by_ids(state: StateManager):
    """Test looking up session by participant + session IDs."""
    subject = state.get_or_create_subject("sub-001")
    state.register_session(
        subject_id=subject.id,
        session_id="ses-baseline",
        dicom_path="/data/sub-001/ses-baseline",
    )

    result = state.get_session_by_ids("sub-001", "ses-baseline")
    assert result is not None
    assert result.session_id == "ses-baseline"

    result = state.get_session_by_ids("sub-999", "ses-baseline")
    assert result is None
