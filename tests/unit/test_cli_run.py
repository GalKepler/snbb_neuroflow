"""Tests for CLI run commands."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from click.testing import CliRunner

from neuroflow.adapters.voxelops import PipelineResult
from neuroflow.cli.main import cli
from neuroflow.runner import RunResult, RunRequest


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
  max_workers: 1
  state_dir: {tmp_path / 'state'}
pipelines:
  session_level:
    - name: qsiprep
      enabled: true
      runner: voxelops.runners.qsiprep
      timeout_minutes: 720
"""
    )
    for d in ("incoming", "bids", "derivatives"):
        (tmp_path / d).mkdir()
    return str(cfg)


class TestRunPipelineCommand:
    @patch("neuroflow.runner.PipelineRunner")
    @patch("neuroflow.state.SessionState")
    def test_no_pending_sessions(self, mock_state_cls, mock_runner_cls, runner, yaml_config):
        mock_state = MagicMock()
        mock_state.get_pending_sessions.return_value = pd.DataFrame(
            columns=["participant_id", "session_id", "dicom_path"]
        )
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "run", "pipeline", "qsiprep"]
        )
        assert result.exit_code == 0
        assert "No pending sessions" in result.output

    @patch("neuroflow.runner.PipelineRunner")
    @patch("neuroflow.state.SessionState")
    def test_dry_run_shows_table(self, mock_state_cls, mock_runner_cls, runner, yaml_config):
        pending_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "dicom_path": "/data/001",
            }
        ])
        mock_state = MagicMock()
        mock_state.get_pending_sessions.return_value = pending_df
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "--dry-run", "run", "pipeline", "qsiprep"]
        )
        assert result.exit_code == 0
        assert "Dry run" in result.output
        assert "sub-001" in result.output

    @patch("neuroflow.runner.PipelineRunner")
    @patch("neuroflow.state.SessionState")
    def test_successful_run_sync(self, mock_state_cls, mock_runner_cls, runner, yaml_config):
        """Test synchronous (blocking) execution with --sync flag."""
        pending_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "dicom_path": "/data/001",
            }
        ])
        mock_state = MagicMock()
        mock_state.get_pending_sessions.return_value = pending_df
        mock_state_cls.return_value = mock_state

        req = RunRequest("sub-001", "ses-01", "/data/001", "qsiprep")
        mock_pipeline_runner = MagicMock()
        mock_pipeline_runner.run_batch.return_value = [
            RunResult(
                request=req,
                pipeline_result=PipelineResult(
                    success=True, exit_code=0, duration_seconds=120.0
                ),
                log_path="/logs/test.log",
            )
        ]
        mock_runner_cls.return_value = mock_pipeline_runner

        result = runner.invoke(
            cli, ["--config", yaml_config, "run", "pipeline", "qsiprep", "--sync"]
        )
        assert result.exit_code == 0
        assert "Succeeded" in result.output
        assert "synchronously" in result.output
        mock_state.record_pipeline_run.assert_called_once()

    @patch("neuroflow.state.SessionState")
    def test_successful_run_async(self, mock_state_cls, runner, yaml_config):
        """Test asynchronous (background queue) execution (default)."""
        import sys
        from unittest.mock import Mock

        # Create a mock tasks module
        mock_tasks = Mock()
        mock_tasks.enqueue_pipeline = Mock(return_value="task-uuid-123")
        mock_tasks.get_queue_stats = Mock(return_value={"pending": 1, "scheduled": 0})
        sys.modules['neuroflow.tasks'] = mock_tasks

        try:
            pending_df = pd.DataFrame([
                {
                    "participant_id": "sub-001",
                    "session_id": "ses-01",
                    "dicom_path": "/data/001",
                }
            ])
            mock_state = MagicMock()
            mock_state.get_pending_sessions.return_value = pending_df
            mock_state_cls.return_value = mock_state

            result = runner.invoke(
                cli, ["--config", yaml_config, "run", "pipeline", "qsiprep"]
            )
            assert result.exit_code == 0
            assert "Enqueued" in result.output or "Enqueueing" in result.output
            mock_tasks.enqueue_pipeline.assert_called()
        finally:
            # Clean up
            if 'neuroflow.tasks' in sys.modules:
                del sys.modules['neuroflow.tasks']

    @patch("neuroflow.runner.PipelineRunner")
    @patch("neuroflow.state.SessionState")
    def test_failed_run_shows_details_sync(self, mock_state_cls, mock_runner_cls, runner, yaml_config):
        """Test failed run with --sync flag shows error details."""
        pending_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "dicom_path": "/data/001",
            }
        ])
        mock_state = MagicMock()
        mock_state.get_pending_sessions.return_value = pending_df
        mock_state_cls.return_value = mock_state

        req = RunRequest("sub-001", "ses-01", "/data/001", "qsiprep")
        mock_pipeline_runner = MagicMock()
        mock_pipeline_runner.run_batch.return_value = [
            RunResult(
                request=req,
                pipeline_result=PipelineResult(
                    success=False,
                    exit_code=1,
                    error_message="Container died",
                    duration_seconds=5.0,
                ),
                log_path="/logs/test.log",
            )
        ]
        mock_runner_cls.return_value = mock_pipeline_runner

        result = runner.invoke(
            cli, ["--config", yaml_config, "run", "pipeline", "qsiprep", "--sync"]
        )
        assert result.exit_code == 0
        assert "Failed" in result.output or "failed" in result.output
        assert "Container died" in result.output

    @patch("neuroflow.runner.PipelineRunner")
    @patch("neuroflow.state.SessionState")
    def test_error_without_pipeline_result_sync(
        self, mock_state_cls, mock_runner_cls, runner, yaml_config
    ):
        """Test error handling with --sync flag."""
        pending_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "dicom_path": "/data/001",
            }
        ])
        mock_state = MagicMock()
        mock_state.get_pending_sessions.return_value = pending_df
        mock_state_cls.return_value = mock_state

        req = RunRequest("sub-001", "ses-01", "/data/001", "qsiprep")
        mock_pipeline_runner = MagicMock()
        mock_pipeline_runner.run_batch.return_value = [
            RunResult(
                request=req,
                pipeline_result=None,
                error="Worker process crashed",
            )
        ]
        mock_runner_cls.return_value = mock_pipeline_runner

        result = runner.invoke(
            cli, ["--config", yaml_config, "run", "pipeline", "qsiprep", "--sync"]
        )
        assert result.exit_code == 0
        mock_state.record_pipeline_run.assert_called_once()
        call_kwargs = mock_state.record_pipeline_run.call_args[1]
        assert call_kwargs["status"] == "failed"

    @patch("neuroflow.runner.PipelineRunner")
    @patch("neuroflow.state.SessionState")
    def test_force_flag_passed(self, mock_state_cls, mock_runner_cls, runner, yaml_config):
        mock_state = MagicMock()
        mock_state.get_pending_sessions.return_value = pd.DataFrame(
            columns=["participant_id", "session_id", "dicom_path"]
        )
        mock_state_cls.return_value = mock_state

        runner.invoke(
            cli, ["--config", yaml_config, "run", "pipeline", "qsiprep", "--force"]
        )
        mock_state.get_pending_sessions.assert_called_once_with(
            for_pipeline="qsiprep", force=True
        )

    @patch("neuroflow.runner.PipelineRunner")
    @patch("neuroflow.state.SessionState")
    def test_participant_filter(self, mock_state_cls, mock_runner_cls, runner, yaml_config):
        pending_df = pd.DataFrame([
            {"participant_id": "sub-001", "session_id": "ses-01", "dicom_path": "/data/001"},
            {"participant_id": "sub-002", "session_id": "ses-01", "dicom_path": "/data/002"},
        ])
        mock_state = MagicMock()
        mock_state.get_pending_sessions.return_value = pending_df
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli,
            [
                "--config", yaml_config,
                "--dry-run",
                "run", "pipeline", "qsiprep",
                "--participant", "sub-001",
            ],
        )
        assert result.exit_code == 0
        assert "sub-001" in result.output
        assert "sub-002" not in result.output


class TestRunAllCommand:
    @patch("neuroflow.runner.PipelineRunner")
    @patch("neuroflow.state.SessionState")
    def test_run_all_no_pipelines(self, mock_state_cls, mock_runner_cls, runner, tmp_path):
        cfg = tmp_path / "neuroflow.yaml"
        cfg.write_text(
            f"""\
paths:
  dicom_incoming: {tmp_path / 'incoming'}
  bids_root: {tmp_path / 'bids'}
  derivatives: {tmp_path / 'derivatives'}
execution:
  state_dir: {tmp_path / 'state'}
pipelines:
  bids_conversion:
    enabled: false
  session_level: []
  subject_level: []
"""
        )
        for d in ("incoming", "bids", "derivatives"):
            (tmp_path / d).mkdir(exist_ok=True)

        result = runner.invoke(cli, ["--config", str(cfg), "run", "all"])
        assert result.exit_code == 0
        assert "No enabled pipelines" in result.output

    @patch("neuroflow.runner.PipelineRunner")
    @patch("neuroflow.state.SessionState")
    def test_run_all_invokes_pipeline(self, mock_state_cls, mock_runner_cls, runner, yaml_config):
        mock_state = MagicMock()
        mock_state.get_pending_sessions.return_value = pd.DataFrame(
            columns=["participant_id", "session_id", "dicom_path"]
        )
        mock_state_cls.return_value = mock_state

        result = runner.invoke(cli, ["--config", yaml_config, "run", "all"])
        assert result.exit_code == 0
        assert "qsiprep" in result.output
