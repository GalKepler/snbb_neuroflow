"""Tests for DICOM session scanner."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from neuroflow.config import DatasetConfig, GoogleSheetConfig, NeuroflowConfig, PathConfig
from neuroflow.discovery.scanner import (
    ScanInfo,
    SessionScanResult,
    SessionScanner,
    parse_dicom_path,
)
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


class TestScanInfo:
    def test_creation(self):
        s = ScanInfo(series_description="T1w MPRAGE", file_count=176, series_uid="1.2.3")
        assert s.series_description == "T1w MPRAGE"
        assert s.file_count == 176
        assert s.series_uid == "1.2.3"

    def test_default_scans_list(self):
        r = SessionScanResult(
            session_path=Path("/tmp"),
            subject_id="sub-001",
            session_id="ses-01",
        )
        assert r.scans == []


class TestFindSessionDirsParticipantFirst:
    """Test _find_session_dirs with participant_first=True layout."""

    @patch.object(SessionScanner, "_has_dicoms", return_value=True)
    def test_participant_session_layout(self, mock_has_dicoms, tmp_path):
        (tmp_path / "sub-001" / "ses-baseline").mkdir(parents=True)
        (tmp_path / "sub-001" / "ses-followup").mkdir(parents=True)
        (tmp_path / "sub-002" / "ses-baseline").mkdir(parents=True)

        config = _make_config(tmp_path, sheet_enabled=False)
        config.dataset.dicom_participant_first = True
        scanner = SessionScanner(config)

        dirs = scanner._find_session_dirs(tmp_path)
        names = [f"{d.parent.name}/{d.name}" for d in dirs]
        assert "sub-001/ses-baseline" in names
        assert "sub-001/ses-followup" in names
        assert "sub-002/ses-baseline" in names
        assert len(dirs) == 3

    @patch.object(SessionScanner, "_has_dicoms", return_value=True)
    def test_skips_hidden_directories(self, mock_has_dicoms, tmp_path):
        (tmp_path / "sub-001" / "ses-01").mkdir(parents=True)
        (tmp_path / ".hidden" / "ses-01").mkdir(parents=True)

        config = _make_config(tmp_path, sheet_enabled=False)
        config.dataset.dicom_participant_first = True
        scanner = SessionScanner(config)

        dirs = scanner._find_session_dirs(tmp_path)
        assert len(dirs) == 1

    @patch.object(SessionScanner, "_has_dicoms", return_value=False)
    def test_skips_dirs_without_dicoms(self, mock_has_dicoms, tmp_path):
        (tmp_path / "sub-001" / "ses-01").mkdir(parents=True)

        config = _make_config(tmp_path, sheet_enabled=False)
        config.dataset.dicom_participant_first = True
        scanner = SessionScanner(config)

        dirs = scanner._find_session_dirs(tmp_path)
        assert dirs == []


class TestFindSessionDirsSessionFirst:
    """Test _find_session_dirs with participant_first=False layout."""

    @patch.object(SessionScanner, "_has_dicoms", return_value=True)
    def test_session_participant_layout(self, mock_has_dicoms, tmp_path):
        (tmp_path / "ses-baseline" / "sub-001").mkdir(parents=True)
        (tmp_path / "ses-baseline" / "sub-002").mkdir(parents=True)

        config = _make_config(tmp_path, sheet_enabled=False)
        config.dataset.dicom_participant_first = False
        scanner = SessionScanner(config)

        dirs = scanner._find_session_dirs(tmp_path)
        assert len(dirs) == 2

    @patch.object(SessionScanner, "_has_dicoms", return_value=True)
    def test_skips_hidden_sessions(self, mock_has_dicoms, tmp_path):
        (tmp_path / "ses-01" / "sub-001").mkdir(parents=True)
        (tmp_path / ".hidden" / "sub-001").mkdir(parents=True)

        config = _make_config(tmp_path, sheet_enabled=False)
        config.dataset.dicom_participant_first = False
        scanner = SessionScanner(config)

        dirs = scanner._find_session_dirs(tmp_path)
        assert len(dirs) == 1


class TestFindSessionDirsNonexistentRoot:
    def test_nonexistent_root(self, tmp_path):
        config = _make_config(tmp_path, sheet_enabled=False)
        scanner = SessionScanner(config)

        dirs = scanner._find_session_dirs(tmp_path / "nonexistent")
        assert dirs == []


class TestScanAll:
    def test_nonexistent_incoming_dir(self, tmp_path):
        config = _make_config(tmp_path / "nonexistent", sheet_enabled=False)
        scanner = SessionScanner(config)

        df, scans = scanner.scan_all()
        assert df.empty
        assert scans == {}

    @patch.object(SessionScanner, "_scan_session")
    @patch.object(SessionScanner, "_find_session_dirs")
    def test_scan_all_collects_results(self, mock_find, mock_scan, tmp_path):
        session_dir = tmp_path / "sub-001" / "ses-01"
        session_dir.mkdir(parents=True)
        mock_find.return_value = [session_dir]

        scan_info = ScanInfo("T1w", 176, "1.2.3")
        mock_scan.return_value = SessionScanResult(
            session_path=session_dir,
            subject_id="sub-001",
            session_id="ses-01",
            scans=[scan_info],
            recruitment_id="REC001",
        )

        config = _make_config(tmp_path, sheet_enabled=False)
        scanner = SessionScanner(config)

        df, scans = scanner.scan_all()
        assert len(df) == 1
        assert df.iloc[0]["participant_id"] == "sub-001"
        assert df.iloc[0]["recruitment_id"] == "REC001"
        assert ("sub-001", "ses-01") in scans
        assert len(scans[("sub-001", "ses-01")]) == 1

    @patch.object(SessionScanner, "_scan_session")
    @patch.object(SessionScanner, "_find_session_dirs")
    def test_scan_all_skips_none_results(self, mock_find, mock_scan, tmp_path):
        mock_find.return_value = [tmp_path / "bad_dir"]
        mock_scan.return_value = None

        config = _make_config(tmp_path, sheet_enabled=False)
        scanner = SessionScanner(config)

        df, scans = scanner.scan_all()
        assert df.empty
        assert scans == {}

    @patch.object(SessionScanner, "_scan_session")
    @patch.object(SessionScanner, "_find_session_dirs")
    def test_scan_all_null_recruitment_id(self, mock_find, mock_scan, tmp_path):
        session_dir = tmp_path / "sub-001" / "ses-01"
        session_dir.mkdir(parents=True)
        mock_find.return_value = [session_dir]
        mock_scan.return_value = SessionScanResult(
            session_path=session_dir,
            subject_id="sub-001",
            session_id="ses-01",
            scans=[],
            recruitment_id=None,
        )

        config = _make_config(tmp_path, sheet_enabled=False)
        scanner = SessionScanner(config)

        df, scans = scanner.scan_all()
        assert df.iloc[0]["recruitment_id"] == ""


class TestUseSheetMapping:
    def test_enabled_google_sheet(self, tmp_path):
        config = _make_config(tmp_path, sheet_enabled=True)
        scanner = SessionScanner(config)
        assert scanner._use_sheet_mapping() is True

    def test_csv_file_set(self, tmp_path):
        config = _make_config(tmp_path, sheet_enabled=False)
        config.dataset.google_sheet.csv_file = "/data/mapping.csv"
        scanner = SessionScanner(config)
        assert scanner._use_sheet_mapping() is True

    def test_no_mapping(self, tmp_path):
        config = _make_config(tmp_path, sheet_enabled=False)
        scanner = SessionScanner(config)
        assert scanner._use_sheet_mapping() is False


class TestScanSessionWithoutMapperEdgeCases:
    def test_returns_none_for_short_path(self, tmp_path):
        """Path with <2 components returns None."""
        config = _make_config(tmp_path, sheet_enabled=False)
        scanner = SessionScanner(config)
        # A relative single-component path
        result = scanner._scan_session(Path("onlyname"), mapper=None)
        assert result is None
