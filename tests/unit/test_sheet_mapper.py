"""Tests for ScanID -> SubjectCode mapper (Google Sheet and CSV)."""

from unittest.mock import MagicMock, patch

import pytest

from neuroflow.config import GoogleSheetConfig
from neuroflow.discovery.sheet_mapper import (
    SheetMapper,
    SubjectMapping,
    clean_subject_code,
    scan_id_to_session_id,
)


# --- pure function tests ---


class TestCleanSubjectCode:
    def test_underscores_removed(self):
        assert clean_subject_code("CLM_L_01") == "CLML01"

    def test_dashes_removed(self):
        assert clean_subject_code("AB-12-CD") == "AB12CD"

    def test_spaces_removed(self):
        assert clean_subject_code("AB 12") == "AB12"

    def test_already_clean(self):
        assert clean_subject_code("ABC123") == "ABC123"

    def test_empty_string(self):
        assert clean_subject_code("") == "unknown"

    def test_mixed_special_chars(self):
        assert clean_subject_code("a.b/c@d!e") == "abcde"


class TestScanIdToSessionId:
    def test_standard_format(self):
        assert scan_id_to_session_id("20240115_1430") == "202401151430"

    def test_no_underscore(self):
        assert scan_id_to_session_id("202401151430") == "202401151430"

    def test_multiple_underscores(self):
        assert scan_id_to_session_id("2024_01_15") == "20240115"


# --- SheetMapper tests ---


def _make_config(**overrides):
    defaults = dict(
        enabled=True,
        spreadsheet_key="test-key",
        worksheet_name="Sheet1",
        service_account_file="/path/to/sa.json",
        scan_id_column="ScanID",
        subject_code_column="SubjectCode",
        unknown_subject_id="unknown",
    )
    defaults.update(overrides)
    return GoogleSheetConfig(**defaults)


def _mock_gspread(records: list[dict]):
    """Return patches that make gspread return the given records."""
    mock_worksheet = MagicMock()
    mock_worksheet.get_all_records.return_value = records

    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheet.return_value = mock_worksheet

    mock_gc = MagicMock()
    mock_gc.open_by_key.return_value = mock_spreadsheet

    mock_authorize = MagicMock(return_value=mock_gc)
    mock_load_creds = MagicMock(return_value=(MagicMock(), "project-id"))

    return mock_authorize, mock_load_creds


class TestSheetMapperFetch:
    def test_fetch_returns_mapping(self):
        config = _make_config()
        mapper = SheetMapper(config)
        records = [
            {"ScanID": "20240115_1430", "SubjectCode": "CLM_L_01"},
            {"ScanID": "20240116_0900", "SubjectCode": "CLM_L_02"},
        ]
        mock_authorize, mock_load_creds = _mock_gspread(records)

        with (
            patch("gspread.authorize", mock_authorize),
            patch("google.auth.load_credentials_from_file", mock_load_creds),
        ):
            result = mapper.fetch()

        assert result == {
            "20240115_1430": "CLM_L_01",
            "20240116_0900": "CLM_L_02",
        }

    def test_fetch_skips_empty_rows(self):
        config = _make_config()
        mapper = SheetMapper(config)
        records = [
            {"ScanID": "20240115_1430", "SubjectCode": "CLM_L_01"},
            {"ScanID": "", "SubjectCode": "CLM_L_02"},
            {"ScanID": "20240117_1000", "SubjectCode": ""},
        ]
        mock_authorize, mock_load_creds = _mock_gspread(records)

        with (
            patch("gspread.authorize", mock_authorize),
            patch("google.auth.load_credentials_from_file", mock_load_creds),
        ):
            result = mapper.fetch()

        assert result == {"20240115_1430": "CLM_L_01"}

    def test_fetch_caches_result(self):
        config = _make_config()
        mapper = SheetMapper(config)
        records = [{"ScanID": "20240115_1430", "SubjectCode": "CLM_L_01"}]
        mock_authorize, mock_load_creds = _mock_gspread(records)

        with (
            patch("gspread.authorize", mock_authorize),
            patch("google.auth.load_credentials_from_file", mock_load_creds),
        ):
            result1 = mapper.fetch()
            result2 = mapper.fetch()

        assert result1 is result2
        # authorize should only be called once
        mock_authorize.assert_called_once()

    def test_invalidate_cache_forces_refetch(self):
        config = _make_config()
        mapper = SheetMapper(config)
        records = [{"ScanID": "20240115_1430", "SubjectCode": "CLM_L_01"}]
        mock_authorize, mock_load_creds = _mock_gspread(records)

        with (
            patch("gspread.authorize", mock_authorize),
            patch("google.auth.load_credentials_from_file", mock_load_creds),
        ):
            mapper.fetch()
            mapper.invalidate_cache()
            mapper.fetch()

        assert mock_authorize.call_count == 2


class TestSheetMapperResolve:
    def test_resolve_known_scan_id(self):
        config = _make_config()
        mapper = SheetMapper(config)
        mapper._mapping = {"20240115_1430": "CLM_L_01"}

        result = mapper.resolve("20240115_1430")

        assert result == SubjectMapping(
            participant_id="CLML01",
            recruitment_id="CLM_L_01",
            session_id="202401151430",
        )

    def test_resolve_unknown_scan_id(self):
        config = _make_config()
        mapper = SheetMapper(config)
        mapper._mapping = {}

        result = mapper.resolve("20240115_1430")

        assert result == SubjectMapping(
            participant_id="unknown",
            recruitment_id="",
            session_id="202401151430",
        )

    def test_resolve_custom_unknown_id(self):
        config = _make_config(unknown_subject_id="UNMATCHED")
        mapper = SheetMapper(config)
        mapper._mapping = {}

        result = mapper.resolve("20240115_1430")
        assert result.participant_id == "UNMATCHED"


# --- CSV-based fetch tests ---


class TestSheetMapperFetchCSV:
    def test_reads_wellformed_csv(self, tmp_path):
        csv_file = tmp_path / "mapping.csv"
        csv_file.write_text(
            "ScanID,SubjectCode\n" "20240115_1430,CLM_L_01\n" "20240116_0900,CLM_L_02\n"
        )
        config = _make_config(csv_file=str(csv_file))
        mapper = SheetMapper(config)

        result = mapper.fetch()

        assert result == {
            "20240115_1430": "CLM_L_01",
            "20240116_0900": "CLM_L_02",
        }

    def test_skips_rows_with_empty_fields(self, tmp_path):
        csv_file = tmp_path / "mapping.csv"
        csv_file.write_text(
            "ScanID,SubjectCode\n"
            "20240115_1430,CLM_L_01\n"
            ",CLM_L_02\n"
            "20240117_1000,\n"
        )
        config = _make_config(csv_file=str(csv_file))
        mapper = SheetMapper(config)

        result = mapper.fetch()

        assert result == {"20240115_1430": "CLM_L_01"}

    def test_caches_result(self, tmp_path):
        csv_file = tmp_path / "mapping.csv"
        csv_file.write_text("ScanID,SubjectCode\n20240115_1430,CLM_L_01\n")
        config = _make_config(csv_file=str(csv_file))
        mapper = SheetMapper(config)

        result1 = mapper.fetch()
        result2 = mapper.fetch()

        assert result1 is result2

    def test_invalidate_cache_forces_reread(self, tmp_path):
        csv_file = tmp_path / "mapping.csv"
        csv_file.write_text("ScanID,SubjectCode\n20240115_1430,CLM_L_01\n")
        config = _make_config(csv_file=str(csv_file))
        mapper = SheetMapper(config)

        result1 = mapper.fetch()
        mapper.invalidate_cache()
        # Update the CSV content between reads
        csv_file.write_text("ScanID,SubjectCode\n20240115_1430,NEW_CODE\n")
        result2 = mapper.fetch()

        assert result1 is not result2
        assert result2 == {"20240115_1430": "NEW_CODE"}

    def test_csv_takes_priority_over_google_sheets(self, tmp_path):
        csv_file = tmp_path / "mapping.csv"
        csv_file.write_text("ScanID,SubjectCode\n20240115_1430,CLM_L_01\n")
        config = _make_config(csv_file=str(csv_file))
        mapper = SheetMapper(config)

        with patch(
            "neuroflow.discovery.sheet_mapper.SheetMapper._fetch_from_google_sheet"
        ) as mock_gs:
            result = mapper.fetch()

        mock_gs.assert_not_called()
        assert result == {"20240115_1430": "CLM_L_01"}
