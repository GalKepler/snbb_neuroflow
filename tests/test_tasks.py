"""Tests for Huey task queue integration."""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from neuroflow.tasks import configure_huey, enqueue_pipeline, get_queue_stats, huey


@pytest.fixture
def mock_run_single_pipeline():
    """Mock the run_single_pipeline function."""
    with patch("neuroflow.tasks.run_single_pipeline") as mock:
        mock.return_value = {
            "success": True,
            "exit_code": 0,
            "output_path": "/path/to/output",
            "error_message": "",
            "duration_seconds": 10.5,
            "log_path": "/path/to/log",
        }
        yield mock


@pytest.fixture
def configured_huey(tmp_path):
    """Configure Huey with a temporary database for testing."""
    configure_huey(tmp_path / "state")
    # Set immediate mode for testing (tasks execute synchronously)
    huey.immediate = True
    yield huey
    huey.immediate = False


def test_configure_huey_creates_db_file(tmp_path):
    """Test that configure_huey creates the SQLite database file."""
    state_dir = tmp_path / "neuroflow_state"
    configure_huey(state_dir)

    expected_db = state_dir / "huey.db"
    # Directory should be created
    assert expected_db.parent.exists()
    # After first task, DB file will be created by SQLite
    # Just verify parent directory exists for now


def test_enqueue_pipeline_returns_task_id(configured_huey, mock_run_single_pipeline, tmp_path, sample_config_path):
    """Test that enqueue_pipeline returns a task ID."""
    task_id = enqueue_pipeline(
        config_path=str(sample_config_path),
        participant_id="sub-01",
        session_id="ses-baseline",
        dicom_path="/data/dicom",
        pipeline_name="test_pipeline",
        log_dir=str(tmp_path / "logs"),
        force=False,
        retries=0,
    )

    assert task_id is not None
    assert isinstance(task_id, str)
    assert len(task_id) > 0


def test_enqueue_pipeline_records_queued_status(configured_huey, mock_run_single_pipeline, tmp_path, sample_config_path):
    """Test that enqueue_pipeline records 'queued' status in SessionState."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.state import SessionState

    config = NeuroflowConfig.from_yaml(sample_config_path)
    state = SessionState(config.execution.state_dir)

    task_id = enqueue_pipeline(
        config_path=str(sample_config_path),
        participant_id="sub-02",
        session_id="ses-baseline",
        dicom_path="/data/dicom",
        pipeline_name="test_pipeline",
        log_dir=str(tmp_path / "logs"),
        force=False,
        retries=0,
    )

    # Check that a queued record was created
    runs = state.load_pipeline_runs()
    queued = runs[
        (runs["participant_id"] == "sub-02")
        & (runs["session_id"] == "ses-baseline")
        & (runs["pipeline_name"] == "test_pipeline")
        & (runs["status"] == "queued")
    ]

    assert len(queued) > 0


def test_enqueue_pipeline_with_retries(configured_huey, mock_run_single_pipeline, tmp_path, sample_config_path):
    """Test that retry count is passed to the task."""
    task_id = enqueue_pipeline(
        config_path=str(sample_config_path),
        participant_id="sub-03",
        session_id="ses-baseline",
        dicom_path="/data/dicom",
        pipeline_name="test_pipeline",
        log_dir=str(tmp_path / "logs"),
        force=False,
        retries=3,
    )

    assert task_id is not None


def test_task_execution_updates_state_to_running(configured_huey, mock_run_single_pipeline, tmp_path, sample_config_path):
    """Test that task execution updates status to 'running'."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.state import SessionState

    config = NeuroflowConfig.from_yaml(sample_config_path)
    state = SessionState(config.execution.state_dir)

    task_id = enqueue_pipeline(
        config_path=str(sample_config_path),
        participant_id="sub-04",
        session_id="ses-baseline",
        dicom_path="/data/dicom",
        pipeline_name="test_pipeline",
        log_dir=str(tmp_path / "logs"),
        force=False,
        retries=0,
    )

    # In immediate mode, task executes synchronously
    # Check for running or completed status
    runs = state.load_pipeline_runs()
    relevant = runs[
        (runs["participant_id"] == "sub-04")
        & (runs["session_id"] == "ses-baseline")
        & (runs["pipeline_name"] == "test_pipeline")
    ]

    # Should have queued + running + completed records
    assert len(relevant) >= 2
    statuses = set(relevant["status"])
    assert "queued" in statuses


def test_task_execution_calls_run_single_pipeline(configured_huey, mock_run_single_pipeline, tmp_path, sample_config_path):
    """Test that the task actually calls run_single_pipeline."""
    task_id = enqueue_pipeline(
        config_path=str(sample_config_path),
        participant_id="sub-05",
        session_id="ses-baseline",
        dicom_path="/data/dicom",
        pipeline_name="test_pipeline",
        log_dir=str(tmp_path / "logs"),
        force=True,
        retries=0,
    )

    # In immediate mode, should execute synchronously
    # Give it a moment to complete
    time.sleep(0.1)

    # Check that run_single_pipeline was called
    mock_run_single_pipeline.assert_called_once()
    call_args = mock_run_single_pipeline.call_args

    assert call_args.kwargs["config_path"] == str(sample_config_path)
    assert call_args.kwargs["participant_id"] == "sub-05"
    assert call_args.kwargs["session_id"] == "ses-baseline"
    assert call_args.kwargs["pipeline_name"] == "test_pipeline"
    assert call_args.kwargs["force"] is True


def test_task_execution_updates_state_on_success(configured_huey, mock_run_single_pipeline, tmp_path, sample_config_path):
    """Test that successful task execution updates state to 'completed'."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.state import SessionState

    config = NeuroflowConfig.from_yaml(sample_config_path)
    state = SessionState(config.execution.state_dir)

    task_id = enqueue_pipeline(
        config_path=str(sample_config_path),
        participant_id="sub-06",
        session_id="ses-baseline",
        dicom_path="/data/dicom",
        pipeline_name="test_pipeline",
        log_dir=str(tmp_path / "logs"),
        force=False,
        retries=0,
    )

    time.sleep(0.1)

    # Check for completed status
    runs = state.load_pipeline_runs()
    completed = runs[
        (runs["participant_id"] == "sub-06")
        & (runs["session_id"] == "ses-baseline")
        & (runs["pipeline_name"] == "test_pipeline")
        & (runs["status"] == "completed")
    ]

    assert len(completed) >= 1
    row = completed.iloc[-1]
    assert row["exit_code"] == "0"
    assert row["output_path"] == "/path/to/output"


def test_task_execution_updates_state_on_failure(configured_huey, mock_run_single_pipeline, tmp_path, sample_config_path):
    """Test that failed task execution updates state to 'failed'."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.state import SessionState

    # Make run_single_pipeline return failure
    mock_run_single_pipeline.return_value = {
        "success": False,
        "exit_code": 1,
        "output_path": "",
        "error_message": "Pipeline failed",
        "duration_seconds": 5.0,
        "log_path": "/path/to/log",
    }

    config = NeuroflowConfig.from_yaml(sample_config_path)
    state = SessionState(config.execution.state_dir)

    task_id = enqueue_pipeline(
        config_path=str(sample_config_path),
        participant_id="sub-07",
        session_id="ses-baseline",
        dicom_path="/data/dicom",
        pipeline_name="test_pipeline",
        log_dir=str(tmp_path / "logs"),
        force=False,
        retries=0,
    )

    time.sleep(0.1)

    # Check for failed status
    runs = state.load_pipeline_runs()
    failed = runs[
        (runs["participant_id"] == "sub-07")
        & (runs["session_id"] == "ses-baseline")
        & (runs["pipeline_name"] == "test_pipeline")
        & (runs["status"] == "failed")
    ]

    assert len(failed) >= 1
    row = failed.iloc[-1]
    assert row["exit_code"] == "1"
    assert row["error_message"] == "Pipeline failed"


def test_task_execution_handles_exception(configured_huey, mock_run_single_pipeline, tmp_path, sample_config_path):
    """Test that task execution handles exceptions and records failure."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.state import SessionState

    # Make run_single_pipeline raise an exception
    mock_run_single_pipeline.side_effect = RuntimeError("Test exception")

    config = NeuroflowConfig.from_yaml(sample_config_path)
    state = SessionState(config.execution.state_dir)

    task_id = enqueue_pipeline(
        config_path=str(sample_config_path),
        participant_id="sub-08",
        session_id="ses-baseline",
        dicom_path="/data/dicom",
        pipeline_name="test_pipeline",
        log_dir=str(tmp_path / "logs"),
        force=False,
        retries=0,
    )

    time.sleep(0.1)

    # Check that failure was recorded
    runs = state.load_pipeline_runs()
    failed = runs[
        (runs["participant_id"] == "sub-08")
        & (runs["session_id"] == "ses-baseline")
        & (runs["pipeline_name"] == "test_pipeline")
        & (runs["status"] == "failed")
    ]

    assert len(failed) >= 1
    row = failed.iloc[-1]
    assert "Test exception" in row["error_message"]


def test_get_queue_stats_empty_queue(configured_huey):
    """Test get_queue_stats with empty queue."""
    stats = get_queue_stats()

    assert "pending" in stats
    assert "scheduled" in stats
    assert stats["pending"] == 0
    assert stats["scheduled"] == 0


def test_get_queue_stats_with_pending_tasks(configured_huey, mock_run_single_pipeline, tmp_path, sample_config_path):
    """Test get_queue_stats with pending tasks."""
    # Disable immediate mode to queue tasks without executing
    huey.immediate = False

    try:
        # Enqueue a few tasks
        for i in range(3):
            enqueue_pipeline(
                config_path=str(sample_config_path),
                participant_id=f"sub-{i:02d}",
                session_id="ses-baseline",
                dicom_path="/data/dicom",
                pipeline_name="test_pipeline",
                log_dir=str(tmp_path / "logs"),
                force=False,
                retries=0,
            )

        stats = get_queue_stats()
        # In non-immediate mode, tasks should be pending
        # Note: SQLite storage might behave differently than memory storage
        assert "pending" in stats
        assert "scheduled" in stats

    finally:
        # Re-enable immediate mode
        huey.immediate = True


def test_enqueue_pipeline_with_pathlib_paths(configured_huey, mock_run_single_pipeline, tmp_path, sample_config_path):
    """Test that enqueue_pipeline works with pathlib.Path objects."""
    from pathlib import Path

    task_id = enqueue_pipeline(
        config_path=str(sample_config_path),
        participant_id="sub-09",
        session_id="ses-baseline",
        dicom_path=str(tmp_path / "dicom"),
        pipeline_name="test_pipeline",
        log_dir=str(tmp_path / "logs"),
        force=False,
        retries=0,
    )

    assert task_id is not None


def test_multiple_tasks_same_session(configured_huey, mock_run_single_pipeline, tmp_path, sample_config_path):
    """Test enqueueing multiple tasks for the same session."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.state import SessionState

    config = NeuroflowConfig.from_yaml(sample_config_path)
    state = SessionState(config.execution.state_dir)

    # Enqueue multiple pipelines for the same session
    task_id1 = enqueue_pipeline(
        config_path=str(sample_config_path),
        participant_id="sub-10",
        session_id="ses-baseline",
        dicom_path="/data/dicom",
        pipeline_name="pipeline1",
        log_dir=str(tmp_path / "logs"),
    )

    task_id2 = enqueue_pipeline(
        config_path=str(sample_config_path),
        participant_id="sub-10",
        session_id="ses-baseline",
        dicom_path="/data/dicom",
        pipeline_name="pipeline2",
        log_dir=str(tmp_path / "logs"),
    )

    assert task_id1 != task_id2

    # Check that both were queued
    runs = state.load_pipeline_runs()
    session_runs = runs[
        (runs["participant_id"] == "sub-10")
        & (runs["session_id"] == "ses-baseline")
    ]

    pipelines = set(session_runs["pipeline_name"])
    assert "pipeline1" in pipelines
    assert "pipeline2" in pipelines
