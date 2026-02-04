"""ScanID -> SubjectCode mapper (Google Sheet or local CSV)."""

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import structlog

from neuroflow.config import GoogleSheetConfig

log = structlog.get_logger("sheet_mapper")


def clean_subject_code(raw: str, unknown: str = "unknown") -> str:
    """Strip non-alphanumeric characters from a subject code.

    Example: 'CLM_L_01' -> 'CLML01', and then zero-pad to 4 characters: '75' -> '0075'.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]", "", raw)
    if cleaned == "":
        return unknown
    return cleaned.zfill(4)


def scan_id_to_session_id(scan_id: str) -> str:
    """Convert a ScanID (YYYYMMDD_hhmm) to a session ID by removing the underscore.

    Example: '20240115_1430' -> '202401151430'
    """
    return scan_id.replace("_", "")


@dataclass
class SubjectMapping:
    """Resolved mapping for a single scan directory."""

    participant_id: str
    recruitment_id: str
    session_id: str


class SheetMapper:
    """Fetches and caches a ScanID -> SubjectCode mapping.

    The mapping can be loaded from either a local CSV file (when
    ``config.csv_file`` is set) or a Google Sheet.
    """

    def __init__(self, config: GoogleSheetConfig):
        self.config = config
        self._mapping: dict[str, str] | None = None

    def fetch(self) -> dict[str, str]:
        """Fetch the ScanID -> SubjectCode mapping.

        If ``config.csv_file`` is non-empty the mapping is read from that
        local CSV file; otherwise it is fetched from Google Sheets.

        Returns a dict keyed by ScanID with SubjectCode values.
        The result is cached; call invalidate_cache() to force a re-read.
        """
        if self._mapping is not None:
            return self._mapping

        if self.config.csv_file:
            self._mapping = self._fetch_from_csv()
        else:
            self._mapping = self._fetch_from_google_sheet()

        log.info("sheet_mapper.fetched", entries=len(self._mapping))
        return self._mapping

    def _fetch_from_csv(self) -> dict[str, str]:
        """Read the mapping from a local CSV file."""
        mapping: dict[str, str] = {}
        with Path(self.config.csv_file).open(newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                scan_id = str(row.get(self.config.scan_id_column, "")).strip()
                subject_code = str(row.get(self.config.subject_code_column, "")).strip()
                if scan_id and subject_code:
                    mapping[scan_id] = subject_code
        return mapping

    def _fetch_from_google_sheet(self) -> dict[str, str]:
        """Fetch the mapping from Google Sheets."""
        import google.auth
        import gspread

        creds = google.auth.load_credentials_from_file(
            self.config.service_account_file,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
        )[0]
        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_key(self.config.spreadsheet_key)
        worksheet = spreadsheet.worksheet(self.config.worksheet_name)
        records = worksheet.get_all_records()

        mapping: dict[str, str] = {}
        for row in records:
            scan_id = str(row.get(self.config.scan_id_column, "")).strip()
            subject_code = str(row.get(self.config.subject_code_column, "")).strip()
            if scan_id and subject_code:
                mapping[scan_id] = subject_code
        return mapping

    def resolve(self, scan_id: str) -> SubjectMapping:
        """Resolve a ScanID to a SubjectMapping.

        If the ScanID is not found in the sheet, participant_id is set to
        the configured unknown_subject_id.
        """
        mapping = self.fetch()
        session_id = scan_id_to_session_id(scan_id)

        raw_code = mapping.get(scan_id)
        if raw_code:
            participant_id = clean_subject_code(
                raw_code, self.config.unknown_subject_id
            )
            recruitment_id = raw_code
        else:
            log.warning("sheet_mapper.unknown_scan_id", scan_id=scan_id)
            participant_id = self.config.unknown_subject_id
            recruitment_id = ""

        return SubjectMapping(
            participant_id=participant_id,
            recruitment_id=recruitment_id,
            session_id=session_id,
        )

    def invalidate_cache(self) -> None:
        """Force a re-fetch on the next call to fetch() or resolve()."""
        self._mapping = None
