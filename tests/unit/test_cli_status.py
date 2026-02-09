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
    @patch("neuroflow.state.SessionState")
    def test_empty_state(self, mock_state_cls, runner, yaml_config):
        mock_state = MagicMock()
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

    @patch("neuroflow.state.SessionState")
    def test_summary_with_sessions(self, mock_state_cls, runner, yaml_config):
        sessions_df = pd.DataFrame([
            {"participant_id": "sub-001", "session_id": "ses-01", "status": "validated"},
            {"participant_id": "sub-002", "session_id": "ses-01", "status": "discovered"},
            {"participant_id": "sub-003", "session_id": "ses-01", "status": "invalid"},
        ])
        mock_state = MagicMock()
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

    @patch("neuroflow.state.SessionState")
    def test_summary_with_pipeline_runs(self, mock_state_cls, runner, yaml_config):
        sessions_df = pd.DataFrame([
            {"participant_id": "sub-001", "session_id": "ses-01", "status": "validated"},
        ])
        pipeline_df = pd.DataFrame([
            {"pipeline_name": "qsiprep", "status": "completed", "count": 5},
            {"pipeline_name": "qsiprep", "status": "failed", "count": 2},
        ])
        mock_state = MagicMock()
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
    @patch("neuroflow.state.SessionState")
    def test_pipelines_table_format(self, mock_state_cls, runner, yaml_config):
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
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines"]
        )
        assert result.exit_code == 0
        assert "qsiprep" in result.output
        assert "120.5s" in result.output

    @patch("neuroflow.state.SessionState")
    def test_pipelines_csv_format(self, mock_state_cls, runner, yaml_config):
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
        mock_state.load_pipeline_runs.return_value = runs_df
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines", "--format", "csv"]
        )
        assert result.exit_code == 0
        assert "pipeline_name" in result.output

    @patch("neuroflow.state.SessionState")
    def test_pipelines_json_format(self, mock_state_cls, runner, yaml_config):
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
        mock_state.load_pipeline_runs.return_value = runs_df
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines", "--format", "json"]
        )
        assert result.exit_code == 0
        assert "qsiprep" in result.output

    @patch("neuroflow.state.SessionState")
    def test_pipelines_empty(self, mock_state_cls, runner, yaml_config):
        mock_state = MagicMock()
        mock_state.load_pipeline_runs.return_value = pd.DataFrame(
            columns=["participant_id", "session_id", "pipeline_name", "status"]
        )
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines"]
        )
        assert result.exit_code == 0
        assert "No pipeline runs found" in result.output

    @patch("neuroflow.state.SessionState")
    def test_pipelines_nan_duration(self, mock_state_cls, runner, yaml_config):
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
        mock_state.load_pipeline_runs.return_value = runs_df
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines"]
        )
        assert result.exit_code == 0
        assert "qsiprep" in result.output

    @patch("neuroflow.state.SessionState")
    def test_pipelines_missing_duration(self, mock_state_cls, runner, yaml_config):
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
        mock_state.load_pipeline_runs.return_value = runs_df
        mock_state_cls.return_value = mock_state

        result = runner.invoke(
            cli, ["--config", yaml_config, "status", "--pipelines"]
        )
        assert result.exit_code == 0
        assert "running" in result.output
