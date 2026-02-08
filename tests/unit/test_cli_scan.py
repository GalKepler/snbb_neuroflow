"""Tests for CLI scan command."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from click.testing import CliRunner

from neuroflow.cli.main import cli
from neuroflow.discovery.scanner import ScanInfo


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
    (tmp_path / "incoming").mkdir()
    (tmp_path / "bids").mkdir()
    (tmp_path / "derivatives").mkdir()
    return str(cfg)


class TestScanCommand:
    @patch("neuroflow.state.SessionState")
    @patch("neuroflow.discovery.scanner.SessionScanner")
    def test_scan_no_sessions(self, mock_scanner_cls, mock_state_cls, runner, yaml_config):
        mock_scanner = MagicMock()
        mock_scanner.scan_all.return_value = (
            pd.DataFrame(columns=["participant_id", "session_id", "dicom_path", "recruitment_id"]),
            {},
        )
        mock_scanner_cls.return_value = mock_scanner

        result = runner.invoke(cli, ["--config", yaml_config, "scan"])
        assert result.exit_code == 0
        assert "No sessions found" in result.output

    @patch("neuroflow.state.SessionState")
    @patch("neuroflow.discovery.scanner.SessionScanner")
    def test_scan_with_sessions(self, mock_scanner_cls, mock_state_cls, runner, yaml_config):
        sessions_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-baseline",
                "dicom_path": "/data/sub-001/ses-baseline",
                "recruitment_id": "REC001",
            }
        ])
        scans = {
            ("sub-001", "ses-baseline"): [
                ScanInfo("T1w MPRAGE", 176, "1.2.3"),
                ScanInfo("DWI", 60, "1.2.4"),
            ]
        }
        mock_scanner = MagicMock()
        mock_scanner.scan_all.return_value = (sessions_df, scans)
        mock_scanner_cls.return_value = mock_scanner

        mock_state = MagicMock()
        mock_state.register_sessions.return_value = 1
        mock_state_cls.return_value = mock_state

        result = runner.invoke(cli, ["--config", yaml_config, "scan"])
        assert result.exit_code == 0
        assert "sub-001" in result.output
        assert "1 new sessions registered" in result.output

    @patch("neuroflow.state.SessionState")
    @patch("neuroflow.discovery.scanner.SessionScanner")
    def test_scan_shows_scan_count(self, mock_scanner_cls, mock_state_cls, runner, yaml_config):
        sessions_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "dicom_path": "/data/001",
                "recruitment_id": "",
            }
        ])
        scans = {
            ("sub-001", "ses-01"): [ScanInfo("T1w", 176, "1.2.3")]
        }
        mock_scanner = MagicMock()
        mock_scanner.scan_all.return_value = (sessions_df, scans)
        mock_scanner_cls.return_value = mock_scanner

        mock_state = MagicMock()
        mock_state.register_sessions.return_value = 1
        mock_state_cls.return_value = mock_state

        result = runner.invoke(cli, ["--config", yaml_config, "scan"])
        assert result.exit_code == 0
        assert "1" in result.output

    @patch("neuroflow.state.SessionState")
    @patch("neuroflow.discovery.scanner.SessionScanner")
    def test_scan_duplicate_sessions(self, mock_scanner_cls, mock_state_cls, runner, yaml_config):
        sessions_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "dicom_path": "/data/001",
                "recruitment_id": "",
            }
        ])
        mock_scanner = MagicMock()
        mock_scanner.scan_all.return_value = (sessions_df, {("sub-001", "ses-01"): []})
        mock_scanner_cls.return_value = mock_scanner

        mock_state = MagicMock()
        mock_state.register_sessions.return_value = 0
        mock_state_cls.return_value = mock_state

        result = runner.invoke(cli, ["--config", yaml_config, "scan"])
        assert result.exit_code == 0
        assert "0 new" in result.output
