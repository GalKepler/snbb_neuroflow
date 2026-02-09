"""Tests for CLI status command."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from click.testing import CliRunner

from neuroflow.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def yaml_config(tmp_path):
    cfg = tmp_path / "neuroflow.yaml"
    cfg.write_text(
        f"""\
paths:
  dicom_incoming: {tmp_path / 'incoming'}
  bids_root: {tmp_path / 'bids'}
  derivatives: {tmp_path / 'derivatives'}
execution:
  state_dir: {tmp_path / 'state'}
"""
    )
    for d in ("incoming", "bids", "derivatives"):
        (tmp_path / d).mkdir()
    return str(cfg)


class TestStatusSummary:
    @patch("neuroflow.cli.status._show_worker_status")
    @patch("neuroflow.state.SessionState")
    def test_empty_state(self, mock_state_cls, mock_worker_status, runner, yaml_config, tmp_path):
        mock_state = MagicMock()
        mock_state.state_dir = str(tmp_path / 'state')
        mock_state.get_session_table.return_value = pd.DataFrame(
            columns=["participant_id", "session_id", "status"]
        )
        mock_state.get_pipeline_summary.return_value = pd.DataFrame(
            columns=["pipeline_name", "status", "count"]
        )
        mock_state_cls.return_value = mock_state

        result = runner.invoke(cli, ["--config", yaml_config, "status"])
        assert result.exit_code == 0
        assert "No data yet" in result.output

    @patch("neuroflow.cli.status._show_worker_status")
    @patch("neuroflow.state.SessionState")
    def test_summary_with_sessions(self, mock_state_cls, mock_worker_status, runner, yaml_config, tmp_path):
        sessions_df = pd.DataFrame([
            {"participant_id": "sub-001", "session_id": "ses-01", "status": "validated"},
            {"participant_id": "sub-002", "session_id": "ses-01", "status": "discovered"},
            {"participant_id": "sub-003", "session_id": "ses-01", "status": "invalid"},
        ])
        mock_state = MagicMock()
        mock_state.state_dir = str(tmp_path / 'state')
        mock_state.get_session_table.return_value = sessions_df
        mock_state.get_pipeline_summary.return_value = pd.DataFrame(
            columns=["pipeline_name", "status", "count"]
        )
        mock_state_cls.return_value = mock_state

        result = runner.invoke(cli, ["--config", yaml_config, "status"])
        assert result.exit_code == 0
        assert "Sessions: 3" in result.output
        assert "validated" in result.output
        assert "discovered" in result.output

    @patch("neuroflow.cli.status._show_worker_status")
    @patch("neuroflow.state.SessionState")
    def test_summary_with_pipeline_runs(self, mock_state_cls, mock_worker_status, runner, yaml_config, tmp_path):
        sessions_df = pd.DataFrame([
            {"participant_id": "sub-001", "session_id": "ses-01", "status": "validated"},
        ])
        pipeline_df = pd.DataFrame([
            {"pipeline_name": "qsiprep", "status": "completed", "count": 5},
            {"pipeline_name": "qsiprep", "status": "failed", "count": 2},
        ])
        mock_state = MagicMock()
        mock_state.state_dir = str(tmp_path / 'state')
        mock_state.get_session_table.return_value = sessions_df
        mock_state.get_pipeline_summary.return_value = pipeline_df
        mock_state_cls.return_value = mock_state

        result = runner.invoke(cli, ["--config", yaml_config, "status"])
        assert result.exit_code == 0
        assert "qsiprep" in result.output
        assert "completed" in result.output


class TestStatusSessions:
    @patch("neuroflow.state.SessionState")
    def test_sessions_table_format(self, mock_state_cls, runner, yaml_config):
        sessions_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "status": "validated",
                "validation_message": "Valid: 2 scans",
                "dicom_path": "/data/sub-001/ses-01",
            }
        ])
        mock_state = MagicMock()
        mock_state.get_session_table.return_value = sessions_df
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--sessions"]
        )
        assert result.exit_code == 0
        assert "sub-001" in result.output
        assert "validated" in result.output

    @patch("neuroflow.state.SessionState")
    def test_sessions_csv_format(self, mock_state_cls, runner, yaml_config):
        sessions_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "status": "validated",
                "validation_message": "",
                "dicom_path": "/data/001",
            }
        ])
        mock_state = MagicMock()
        mock_state.get_session_table.return_value = sessions_df
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--sessions", "--format", "csv"]
        )
        assert result.exit_code == 0
        assert "participant_id" in result.output
        assert "sub-001" in result.output

    @patch("neuroflow.state.SessionState")
    def test_sessions_json_format(self, mock_state_cls, runner, yaml_config):
        sessions_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "status": "validated",
                "validation_message": "",
                "dicom_path": "/data/001",
            }
        ])
        mock_state = MagicMock()
        mock_state.get_session_table.return_value = sessions_df
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--sessions", "--format", "json"]
        )
        assert result.exit_code == 0
        assert "sub-001" in result.output

    @patch("neuroflow.state.SessionState")
    def test_sessions_empty(self, mock_state_cls, runner, yaml_config):
        mock_state = MagicMock()
        mock_state.get_session_table.return_value = pd.DataFrame(
            columns=["participant_id", "session_id", "status"]
        )
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--sessions"]
        )
        assert result.exit_code == 0
        assert "No sessions found" in result.output


class TestStatusPipelines:
    @patch("neuroflow.tasks.get_queue_details")
    @patch("neuroflow.tasks.configure_huey")
    @patch("neuroflow.state.SessionState")
    def test_pipelines_table_format(self, mock_state_cls, mock_configure_huey, mock_queue_details, runner, yaml_config, tmp_path):
        mock_queue_details.return_value = []
        runs_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "pipeline_name": "qsiprep",
                "status": "completed",
                "duration_seconds": "120.5",
                "exit_code": "0",
            }
        ])
        mock_state = MagicMock()
        mock_state.state_dir = str(tmp_path / 'state')
        mock_state.load_pipeline_runs.return_value = runs_df
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines"]
        )
        assert result.exit_code == 0
        assert "qsiprep" in result.output
        assert "120.5s" in result.output

    @patch("neuroflow.tasks.get_queue_details")
    @patch("neuroflow.tasks.configure_huey")
    @patch("neuroflow.state.SessionState")
    def test_pipelines_csv_format(self, mock_state_cls, mock_configure_huey, mock_queue_details, runner, yaml_config, tmp_path):
        mock_queue_details.return_value = []
        runs_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "pipeline_name": "qsiprep",
                "status": "completed",
                "duration_seconds": "60.0",
                "exit_code": "0",
            }
        ])
        mock_state = MagicMock()
        mock_state.state_dir = str(tmp_path / 'state')
        mock_state.load_pipeline_runs.return_value = runs_df
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines", "--format", "csv"]
        )
        assert result.exit_code == 0
        assert "pipeline_name" in result.output

    @patch("neuroflow.tasks.get_queue_details")
    @patch("neuroflow.tasks.configure_huey")
    @patch("neuroflow.state.SessionState")
    def test_pipelines_json_format(self, mock_state_cls, mock_configure_huey, mock_queue_details, runner, yaml_config, tmp_path):
        mock_queue_details.return_value = []
        runs_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "pipeline_name": "qsiprep",
                "status": "completed",
                "duration_seconds": "60.0",
                "exit_code": "0",
            }
        ])
        mock_state = MagicMock()
        mock_state.state_dir = str(tmp_path / 'state')
        mock_state.load_pipeline_runs.return_value = runs_df
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines", "--format", "json"]
        )
        assert result.exit_code == 0
        assert "qsiprep" in result.output

    @patch("neuroflow.tasks.get_queue_details")
    @patch("neuroflow.tasks.configure_huey")
    @patch("neuroflow.state.SessionState")
    def test_pipelines_empty(self, mock_state_cls, mock_configure_huey, mock_queue_details, runner, yaml_config, tmp_path):
        mock_queue_details.return_value = []
        mock_state = MagicMock()
        mock_state.state_dir = str(tmp_path / 'state')
        mock_state.load_pipeline_runs.return_value = pd.DataFrame(
            columns=["participant_id", "session_id", "pipeline_name", "status"]
        )
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines"]
        )
        assert result.exit_code == 0
        assert "No pipeline runs found" in result.output

    @patch("neuroflow.tasks.get_queue_details")
    @patch("neuroflow.tasks.configure_huey")
    @patch("neuroflow.state.SessionState")
    def test_pipelines_nan_duration(self, mock_state_cls, mock_configure_huey, mock_queue_details, runner, yaml_config, tmp_path):
        mock_queue_details.return_value = []
        runs_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "pipeline_name": "qsiprep",
                "status": "failed",
                "duration_seconds": "nan",
                "exit_code": "1",
            }
        ])
        mock_state = MagicMock()
        mock_state.state_dir = str(tmp_path / 'state')
        mock_state.load_pipeline_runs.return_value = runs_df
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines"]
        )
        assert result.exit_code == 0
        assert "qsiprep" in result.output

    @patch("neuroflow.tasks.get_queue_details")
    @patch("neuroflow.tasks.configure_huey")
    @patch("neuroflow.state.SessionState")
    def test_pipelines_missing_duration(self, mock_state_cls, mock_configure_huey, mock_queue_details, runner, yaml_config, tmp_path):
        mock_queue_details.return_value = []
        runs_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "pipeline_name": "qsiprep",
                "status": "running",
                "duration_seconds": "",
                "exit_code": "",
            }
        ])
        mock_state = MagicMock()
        mock_state.state_dir = str(tmp_path / 'state')
        mock_state.load_pipeline_runs.return_value = runs_df
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines"]
        )
        assert result.exit_code == 0
        assert "running" in result.output


class TestStatusPipelinesPhase4:
    """Tests for Phase 4 enhanced status features."""

    @patch("neuroflow.tasks.configure_huey")
    @patch("neuroflow.tasks.get_queue_details")
    @patch("neuroflow.state.SessionState")
    def test_pipelines_with_queued_tasks(
        self, mock_state_cls, mock_get_queue_details, mock_configure_huey, runner, yaml_config
    ):
        """Test that queued tasks from the queue are shown in pipelines."""
        # Mock completed runs
        runs_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "pipeline_name": "qsiprep",
                "status": "completed",
                "duration_seconds": "120.5",
                "exit_code": "0",
            }
        ])
        mock_state = MagicMock()
        mock_state.load_pipeline_runs.return_value = runs_df
        mock_state.state_dir = "/tmp/state"
        mock_state_cls.return_value = mock_state

        # Mock queued tasks
        mock_get_queue_details.return_value = [
            {
                "task_id": "abc12345-6789-abcd-ef01-23456789abcd",
                "pipeline_name": "fmriprep",
                "participant_id": "sub-002",
                "session_id": "ses-02",
                "status": "queued",
            }
        ]

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines"]
        )
        assert result.exit_code == 0
        assert "qsiprep" in result.output  # Completed
        assert "fmriprep" in result.output  # Queued
        assert "sub-002" in result.output
        assert "queued" in result.output

    @patch("neuroflow.tasks.configure_huey")
    @patch("neuroflow.tasks.get_queue_details")
    @patch("neuroflow.state.SessionState")
    def test_pipelines_filter_queued(
        self, mock_state_cls, mock_get_queue_details, mock_configure_huey, runner, yaml_config
    ):
        """Test filtering pipelines by queued status."""
        # Mock completed runs
        runs_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "pipeline_name": "qsiprep",
                "status": "completed",
                "duration_seconds": "120.5",
                "exit_code": "0",
            }
        ])
        mock_state = MagicMock()
        mock_state.load_pipeline_runs.return_value = runs_df
        mock_state.state_dir = "/tmp/state"
        mock_state_cls.return_value = mock_state

        # Mock queued tasks
        mock_get_queue_details.return_value = [
            {
                "task_id": "abc12345",
                "pipeline_name": "fmriprep",
                "participant_id": "sub-002",
                "session_id": "ses-02",
                "status": "queued",
            }
        ]

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines", "--filter", "queued"]
        )
        assert result.exit_code == 0
        assert "fmriprep" in result.output  # Queued task shown
        assert "qsiprep" not in result.output  # Completed task filtered out
        assert "filtered: queued" in result.output

    @patch("neuroflow.tasks.configure_huey")
    @patch("neuroflow.tasks.get_queue_details")
    @patch("neuroflow.state.SessionState")
    def test_pipelines_filter_completed(
        self, mock_state_cls, mock_get_queue_details, mock_configure_huey, runner, yaml_config
    ):
        """Test filtering pipelines by completed status."""
        # Mock completed runs
        runs_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "pipeline_name": "qsiprep",
                "status": "completed",
                "duration_seconds": "120.5",
                "exit_code": "0",
            }
        ])
        mock_state = MagicMock()
        mock_state.load_pipeline_runs.return_value = runs_df
        mock_state.state_dir = "/tmp/state"
        mock_state_cls.return_value = mock_state

        # Mock queued tasks
        mock_get_queue_details.return_value = [
            {
                "task_id": "abc12345",
                "pipeline_name": "fmriprep",
                "participant_id": "sub-002",
                "session_id": "ses-02",
                "status": "queued",
            }
        ]

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines", "--filter", "completed"]
        )
        assert result.exit_code == 0
        assert "qsiprep" in result.output  # Completed task shown
        assert "fmriprep" not in result.output  # Queued task filtered out

    @patch("neuroflow.tasks.configure_huey")
    @patch("neuroflow.tasks.get_queue_details")
    @patch("neuroflow.state.SessionState")
    def test_pipelines_filter_no_matches(
        self, mock_state_cls, mock_get_queue_details, mock_configure_huey, runner, yaml_config
    ):
        """Test filtering with no matching results."""
        # Mock completed runs only
        runs_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "pipeline_name": "qsiprep",
                "status": "completed",
                "duration_seconds": "120.5",
                "exit_code": "0",
            }
        ])
        mock_state = MagicMock()
        mock_state.load_pipeline_runs.return_value = runs_df
        mock_state.state_dir = "/tmp/state"
        mock_state_cls.return_value = mock_state

        # No queued tasks
        mock_get_queue_details.return_value = []

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines", "--filter", "queued"]
        )
        assert result.exit_code == 0
        assert "No pipeline runs with status 'queued'" in result.output

    @patch("neuroflow.tasks.configure_huey")
    @patch("neuroflow.tasks.get_queue_details")
    @patch("neuroflow.state.SessionState")
    def test_pipelines_deduplicates_queued_tasks(
        self, mock_state_cls, mock_get_queue_details, mock_configure_huey, runner, yaml_config
    ):
        """Test that duplicate queued entries (state + queue) are deduplicated."""
        # Mock state with a queued entry (without task_id)
        runs_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "pipeline_name": "qsiprep",
                "status": "queued",
                "duration_seconds": "",
                "exit_code": "",
            },
            {
                "participant_id": "sub-002",
                "session_id": "ses-01",
                "pipeline_name": "fmriprep",
                "status": "completed",
                "duration_seconds": "100.0",
                "exit_code": "0",
            }
        ])
        mock_state = MagicMock()
        mock_state.load_pipeline_runs.return_value = runs_df
        mock_state.state_dir = "/tmp/state"
        mock_state_cls.return_value = mock_state

        # Mock queue with the same queued task (with task_id)
        mock_get_queue_details.return_value = [
            {
                "task_id": "abc12345",
                "pipeline_name": "qsiprep",
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "status": "queued",
            }
        ]

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines"]
        )
        assert result.exit_code == 0
        # Should show task ID (from queue) not duplicate
        assert "abc12345" in result.output or "abc1234" in result.output  # First 8 chars
        # Count occurrences - sub-001 should appear only once
        assert result.output.count("sub-001") == 1


class TestStatusWorkerStatusPhase4:
    """Tests for Phase 4 worker status in summary."""

    @patch("neuroflow.cli.worker._read_pid")
    @patch("neuroflow.tasks.get_queue_stats")
    @patch("neuroflow.tasks.configure_huey")
    @patch("neuroflow.state.SessionState")
    def test_summary_shows_worker_running(
        self, mock_state_cls, mock_configure_huey, mock_get_queue_stats, mock_read_pid, runner, yaml_config
    ):
        """Test that summary shows worker status when running."""
        sessions_df = pd.DataFrame([
            {"participant_id": "sub-001", "session_id": "ses-01", "status": "validated"},
        ])
        mock_state = MagicMock()
        mock_state.get_session_table.return_value = sessions_df
        mock_state.get_pipeline_summary.return_value = pd.DataFrame(
            columns=["pipeline_name", "status", "count"]
        )
        mock_state.state_dir = "/tmp/state"
        mock_state_cls.return_value = mock_state

        # Mock worker running
        mock_read_pid.return_value = 12345
        mock_get_queue_stats.return_value = {"pending": 3, "scheduled": 1}

        result = runner.invoke(cli, ["--config", yaml_config, "status"])
        assert result.exit_code == 0
        assert "Worker:" in result.output
        assert "Running" in result.output
        assert "12345" in result.output
        assert "Queue:" in result.output
        assert "4" in result.output  # 3 + 1

    @patch("neuroflow.cli.worker._read_pid")
    @patch("neuroflow.tasks.get_queue_stats")
    @patch("neuroflow.tasks.configure_huey")
    @patch("neuroflow.state.SessionState")
    def test_summary_shows_worker_not_running(
        self, mock_state_cls, mock_configure_huey, mock_get_queue_stats, mock_read_pid, runner, yaml_config
    ):
        """Test that summary shows worker status when not running."""
        sessions_df = pd.DataFrame([
            {"participant_id": "sub-001", "session_id": "ses-01", "status": "validated"},
        ])
        mock_state = MagicMock()
        mock_state.get_session_table.return_value = sessions_df
        mock_state.get_pipeline_summary.return_value = pd.DataFrame(
            columns=["pipeline_name", "status", "count"]
        )
        mock_state.state_dir = "/tmp/state"
        mock_state_cls.return_value = mock_state

        # Mock worker not running
        mock_read_pid.return_value = None
        mock_get_queue_stats.return_value = {"pending": 0, "scheduled": 0}

        result = runner.invoke(cli, ["--config", yaml_config, "status"])
        assert result.exit_code == 0
        assert "Worker:" in result.output
        assert "Not running" in result.output


class TestStatusReadOnlyStateDir:
    """Tests for graceful handling of read-only state directories."""

    @patch("neuroflow.tasks.configure_huey")
    @patch("neuroflow.state.SessionState")
    def test_pipelines_with_readonly_state_dir(
        self, mock_state_cls, mock_configure_huey, runner, yaml_config
    ):
        """Test that pipelines display works even if state dir is read-only."""
        # Mock completed runs
        runs_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "pipeline_name": "qsiprep",
                "status": "completed",
                "duration_seconds": "120.5",
                "exit_code": "0",
            }
        ])
        mock_state = MagicMock()
        mock_state.load_pipeline_runs.return_value = runs_df
        mock_state.state_dir = "/tmp/state"
        mock_state_cls.return_value = mock_state

        # Simulate PermissionError when configure_huey tries to mkdir
        mock_configure_huey.side_effect = PermissionError("Read-only file system")

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines"]
        )
        
        # Should succeed and show completed runs, just skip queue info
        assert result.exit_code == 0
        assert "qsiprep" in result.output
        assert "completed" in result.output
        # Should NOT crash with PermissionError

    @patch("neuroflow.tasks.configure_huey")
    @patch("neuroflow.tasks.get_queue_stats")
    @patch("neuroflow.state.SessionState")
    def test_summary_with_readonly_state_dir(
        self, mock_state_cls, mock_get_queue_stats, mock_configure_huey, runner, yaml_config
    ):
        """Test that summary works even if state dir is read-only."""
        sessions_df = pd.DataFrame([
            {"participant_id": "sub-001", "session_id": "ses-01", "status": "validated"},
        ])
        mock_state = MagicMock()
        mock_state.get_session_table.return_value = sessions_df
        mock_state.get_pipeline_summary.return_value = pd.DataFrame(
            columns=["pipeline_name", "status", "count"]
        )
        mock_state.state_dir = "/tmp/state"
        mock_state_cls.return_value = mock_state

        # Simulate PermissionError when configure_huey tries to mkdir
        mock_configure_huey.side_effect = PermissionError("Read-only file system")

        result = runner.invoke(cli, ["--config", yaml_config, "status"])
        
        # Should succeed and show sessions, just skip worker status
        assert result.exit_code == 0
        assert "Sessions: 1" in result.output
        assert "Worker status: unavailable" in result.output
        # Should NOT crash with PermissionError
