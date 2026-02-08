"""Tests for DICOM session scanner."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from neuroflow.config import DatasetConfig, GoogleSheetConfig, NeuroflowConfig, PathConfig
from neuroflow.discovery.scanner import SessionScanResult, SessionScanner, parse_dicom_path
from neuroflow.discovery.sheet_mapper import SheetMapper, SubjectMapping


# --- Legacy parse_dicom_path tests ---


def test_parse_dicom_path_participant_first():
    """Test parsing path with participant/session structure."""
    path = Path("/data/Raw_Data/sub-001/ses-baseline")
    result = parse_dicom_path(path, participant_first=True)
    assert result == ("sub-001", "ses-baseline")


def test_parse_dicom_path_session_first():
    """Test parsing path with session/participant structure."""
    path = Path("/data/Raw_Data/ses-baseline/sub-001")
    result = parse_dicom_path(path, participant_first=False)
    assert result == ("sub-001", "ses-baseline")


def test_parse_dicom_path_two_components():
    """Test parsing a two-component absolute path returns parts."""
    path = Path("/data")
    result = parse_dicom_path(path, participant_first=True)
    # Path("/data").parts is ('/', 'data') which has length 2
    assert result is not None


def test_parse_dicom_path_single_component():
    """Test parsing a single-component path."""
    path = Path("subject")
    result = parse_dicom_path(path, participant_first=True)
    assert result is None


# --- Flat layout / sheet-mapper scanner tests ---


def _make_config(tmp_path: Path, sheet_enabled: bool = False) -> NeuroflowConfig:
    """Build a minimal NeuroflowConfig for testing."""
    return NeuroflowConfig(
        paths=PathConfig(
            dicom_incoming=tmp_path,
            bids_root=tmp_path / "bids",
            derivatives=tmp_path / "derivatives",
            work_dir=tmp_path / "work",
        ),
        dataset=DatasetConfig(
            google_sheet=GoogleSheetConfig(enabled=sheet_enabled),
        ),
    )


class TestFindSessionDirsFlat:
    """Test _find_session_dirs with sheet mapping (flat layout)."""

    def test_flat_layout_returns_immediate_subdirs(self, tmp_path):
        (tmp_path / "20240115_1430").mkdir()
        (tmp_path / "20240116_0900").mkdir()
        (tmp_path / ".hidden").mkdir()

        config = _make_config(tmp_path, sheet_enabled=True)
        scanner = SessionScanner(config)

        dirs = scanner._find_session_dirs(tmp_path)

        names = [d.name for d in dirs]
        assert names == ["20240115_1430", "20240116_0900"]

    def test_flat_layout_ignores_files(self, tmp_path):
        (tmp_path / "20240115_1430").mkdir()
        (tmp_path / "readme.txt").touch()

        config = _make_config(tmp_path, sheet_enabled=True)
        scanner = SessionScanner(config)

        dirs = scanner._find_session_dirs(tmp_path)
        assert len(dirs) == 1

    def test_flat_layout_empty_dir(self, tmp_path):
        config = _make_config(tmp_path, sheet_enabled=True)
        scanner = SessionScanner(config)

        dirs = scanner._find_session_dirs(tmp_path)
        assert dirs == []


class TestScanSessionWithMapper:
    """Test _scan_session when a SheetMapper is provided."""

    def test_scan_session_uses_mapper(self, tmp_path):
        scan_dir = tmp_path / "20240115_1430"
        scan_dir.mkdir()

        config = _make_config(tmp_path, sheet_enabled=True)
        scanner = SessionScanner(config)

        mapper = MagicMock(spec=SheetMapper)
        mapper.resolve.return_value = SubjectMapping(
            participant_id="CLML01",
            recruitment_id="CLM_L_01",
            session_id="202401151430",
        )

        result = scanner._scan_session(scan_dir, mapper=mapper)

        assert result is not None
        assert result.subject_id == "CLML01"
        assert result.session_id == "202401151430"
        assert result.recruitment_id == "CLM_L_01"
        mapper.resolve.assert_called_once_with("20240115_1430")

    def test_scan_session_without_mapper_uses_path(self, tmp_path):
        session_dir = tmp_path / "sub-001" / "ses-baseline"
        session_dir.mkdir(parents=True)

        config = _make_config(tmp_path, sheet_enabled=False)
        scanner = SessionScanner(config)

        result = scanner._scan_session(session_dir, mapper=None)

        assert result is not None
        assert result.subject_id == "sub-001"
        assert result.session_id == "ses-baseline"
        assert result.recruitment_id is None


class TestSessionScanResultRecruitmentId:
    def test_recruitment_id_default_none(self):
        r = SessionScanResult(
            session_path=Path("/tmp/test"),
            subject_id="sub-001",
            session_id="ses-01",
        )
        assert r.recruitment_id is None

    def test_recruitment_id_set(self):
        r = SessionScanResult(
            session_path=Path("/tmp/test"),
            subject_id="CLML01",
            session_id="202401151430",
            recruitment_id="CLM_L_01",
        )
        assert r.recruitment_id == "CLM_L_01"
