"""Tests for CLI validate command."""

from dataclasses import dataclass
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
    for d in ("incoming", "bids", "derivatives"):
        (tmp_path / d).mkdir()
    return str(cfg)


@dataclass
class FakeValidationResult:
    is_valid: bool
    message: str
    scans_found: dict
    missing_required: list


class TestValidateCommand:
    @patch("neuroflow.state.SessionState")
    def test_no_sessions_to_validate(self, mock_state_cls, runner, yaml_config):
        mock_state = MagicMock()
        mock_state.load_sessions.return_value = pd.DataFrame(
            columns=["participant_id", "session_id", "dicom_path", "status"]
        )
        mock_state_cls.return_value = mock_state

        result = runner.invoke(cli, ["--config", yaml_config, "validate"])
        assert result.exit_code == 0
        assert "No sessions to validate" in result.output

    @patch("neuroflow.discovery.validator.SessionValidator")
    @patch("neuroflow.discovery.scanner.SessionScanner")
    @patch("neuroflow.state.SessionState")
    def test_validate_valid_session(
        self, mock_state_cls, mock_scanner_cls, mock_validator_cls, runner, yaml_config
    ):
        sessions_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "dicom_path": "/data/001",
                "recruitment_id": "",
                "status": "discovered",
                "validation_message": "",
                "scans_found": "",
                "last_updated": "",
            }
        ])
        mock_state = MagicMock()
        mock_state.load_sessions.return_value = sessions_df
        mock_state_cls.return_value = mock_state

        mock_scanner = MagicMock()
        mock_scanner._identify_scans.return_value = [
            ScanInfo("T1w MPRAGE", 176, "1.2.3")
        ]
        mock_scanner_cls.return_value = mock_scanner

        mock_validator = MagicMock()
        mock_validator.validate.return_value = FakeValidationResult(
            is_valid=True,
            message="Valid: 1 scan type",
            scans_found={"T1w": 176},
            missing_required=[],
        )
        mock_validator_cls.return_value = mock_validator

        result = runner.invoke(cli, ["--config", yaml_config, "validate"])
        assert result.exit_code == 0
        assert "Valid:" in result.output or "valid" in result.output.lower()
        mock_state.update_session_status.assert_called_once()

    @patch("neuroflow.discovery.validator.SessionValidator")
    @patch("neuroflow.discovery.scanner.SessionScanner")
    @patch("neuroflow.state.SessionState")
    def test_validate_invalid_session(
        self, mock_state_cls, mock_scanner_cls, mock_validator_cls, runner, yaml_config
    ):
        sessions_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "dicom_path": "/data/001",
                "recruitment_id": "",
                "status": "discovered",
                "validation_message": "",
                "scans_found": "",
                "last_updated": "",
            }
        ])
        mock_state = MagicMock()
        mock_state.load_sessions.return_value = sessions_df
        mock_state_cls.return_value = mock_state

        mock_scanner = MagicMock()
        mock_scanner._identify_scans.return_value = []
        mock_scanner_cls.return_value = mock_scanner

        mock_validator = MagicMock()
        mock_validator.validate.return_value = FakeValidationResult(
            is_valid=False,
            message="Missing: T1w",
            scans_found={},
            missing_required=["T1w"],
        )
        mock_validator_cls.return_value = mock_validator

        result = runner.invoke(cli, ["--config", yaml_config, "validate"])
        assert result.exit_code == 0
        assert "Invalid" in result.output or "invalid" in result.output.lower()

    @patch("neuroflow.discovery.validator.SessionValidator")
    @patch("neuroflow.discovery.scanner.SessionScanner")
    @patch("neuroflow.state.SessionState")
    def test_validate_exception_handled(
        self, mock_state_cls, mock_scanner_cls, mock_validator_cls, runner, yaml_config
    ):
        sessions_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "dicom_path": "/data/001",
                "recruitment_id": "",
                "status": "discovered",
                "validation_message": "",
                "scans_found": "",
                "last_updated": "",
            }
        ])
        mock_state = MagicMock()
        mock_state.load_sessions.return_value = sessions_df
        mock_state_cls.return_value = mock_state

        mock_scanner = MagicMock()
        mock_scanner._identify_scans.side_effect = OSError("Permission denied")
        mock_scanner_cls.return_value = mock_scanner

        result = runner.invoke(cli, ["--config", yaml_config, "validate"])
        assert result.exit_code == 0
        assert "Error" in result.output

    @patch("neuroflow.discovery.validator.SessionValidator")
    @patch("neuroflow.discovery.scanner.SessionScanner")
    @patch("neuroflow.state.SessionState")
    def test_validate_only_discovered_and_invalid(
        self, mock_state_cls, mock_scanner_cls, mock_validator_cls, runner, yaml_config
    ):
        """Sessions with status 'validated' or 'completed' are skipped."""
        sessions_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "dicom_path": "/data/001",
                "recruitment_id": "",
                "status": "validated",
                "validation_message": "Valid",
                "scans_found": "",
                "last_updated": "",
            },
            {
                "participant_id": "sub-002",
                "session_id": "ses-01",
                "dicom_path": "/data/002",
                "recruitment_id": "",
                "status": "discovered",
                "validation_message": "",
                "scans_found": "",
                "last_updated": "",
            },
        ])
        mock_state = MagicMock()
        mock_state.load_sessions.return_value = sessions_df
        mock_state_cls.return_value = mock_state

        mock_scanner = MagicMock()
        mock_scanner._identify_scans.return_value = [ScanInfo("T1w", 176, "1.2.3")]
        mock_scanner_cls.return_value = mock_scanner

        mock_validator = MagicMock()
        mock_validator.validate.return_value = FakeValidationResult(
            is_valid=True, message="OK", scans_found={"T1w": 176}, missing_required=[]
        )
        mock_validator_cls.return_value = mock_validator

        result = runner.invoke(cli, ["--config", yaml_config, "validate"])
        assert result.exit_code == 0
        # Only sub-002 should be validated (1 session)
        assert "1 sessions" in result.output
        assert mock_scanner._identify_scans.call_count == 1

    @patch("neuroflow.discovery.validator.SessionValidator")
    @patch("neuroflow.discovery.scanner.SessionScanner")
    @patch("neuroflow.state.SessionState")
    def test_validate_shows_failed_table(
        self, mock_state_cls, mock_scanner_cls, mock_validator_cls, runner, yaml_config
    ):
        sessions_df = pd.DataFrame([
            {
                "participant_id": "sub-001",
                "session_id": "ses-01",
                "dicom_path": "/data/001",
                "recruitment_id": "",
                "status": "discovered",
                "validation_message": "",
                "scans_found": "",
                "last_updated": "",
            },
            {
                "participant_id": "sub-002",
                "session_id": "ses-01",
                "dicom_path": "/data/002",
                "recruitment_id": "",
                "status": "discovered",
                "validation_message": "",
                "scans_found": "",
                "last_updated": "",
            },
        ])
        mock_state = MagicMock()
        mock_state.load_sessions.return_value = sessions_df
        mock_state_cls.return_value = mock_state

        mock_scanner = MagicMock()
        mock_scanner._identify_scans.return_value = []
        mock_scanner_cls.return_value = mock_scanner

        mock_validator = MagicMock()
        mock_validator.validate.return_value = FakeValidationResult(
            is_valid=False,
            message="Missing required scans",
            scans_found={},
            missing_required=["T1w"],
        )
        mock_validator_cls.return_value = mock_validator

        result = runner.invoke(cli, ["--config", yaml_config, "validate"])
        assert result.exit_code == 0
        assert "Invalid Sessions" in result.output
        assert "sub-001" in result.output
        assert "sub-002" in result.output
