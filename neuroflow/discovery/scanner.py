"""DICOM session scanner."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import structlog

from neuroflow.config import NeuroflowConfig

log = structlog.get_logger("scanner")


@dataclass
class ScanInfo:
    """Information about a single DICOM series."""

    series_description: str
    file_count: int
    series_uid: str


@dataclass
class SessionScanResult:
    """Result of scanning a session directory."""

    session_path: Path
    subject_id: str
    session_id: str
    scans: list[ScanInfo] = field(default_factory=list)
    recruitment_id: str | None = None


def parse_dicom_path(
    path: Path, participant_first: bool
) -> tuple[str, str] | None:
    """Extract subject and session IDs from DICOM path.

    Args:
        path: Path to a session directory.
        participant_first: If True, path is .../SUBJECT/SESSION/.
                          If False, path is .../SESSION/SUBJECT/.

    Returns:
        Tuple of (subject_id, session_id) or None if path is too short.
    """
    parts = path.parts
    if len(parts) < 2:
        return None

    if participant_first:
        subject_id = parts[-2]
        session_id = parts[-1]
    else:
        session_id = parts[-2]
        subject_id = parts[-1]

    return subject_id, session_id


class SessionScanner:
    """Scan directories for DICOM sessions."""

    def __init__(self, config: NeuroflowConfig):
        self.config = config

    def _use_sheet_mapping(self) -> bool:
        """Check whether sheet/CSV mapping is enabled."""
        gs = self.config.dataset.google_sheet
        return gs.enabled or bool(gs.csv_file)

    def scan_all(self) -> tuple[pd.DataFrame, dict[tuple[str, str], list[ScanInfo]]]:
        """Scan all configured directories for new sessions.

        Returns:
            Tuple of (sessions_df, scans_by_session) where:
            - sessions_df has columns: participant_id, session_id, dicom_path, recruitment_id
            - scans_by_session maps (participant_id, session_id) -> list[ScanInfo]
        """
        from neuroflow.discovery.sheet_mapper import SheetMapper

        incoming = self.config.paths.dicom_incoming
        log.info("scan.started", path=str(incoming))

        rows: list[dict] = []
        scans_by_session: dict[tuple[str, str], list[ScanInfo]] = {}

        if not incoming.exists():
            log.warning("scan.path_not_found", path=str(incoming))
            return pd.DataFrame(columns=["participant_id", "session_id", "dicom_path", "recruitment_id"]), scans_by_session

        mapper = None
        if self._use_sheet_mapping():
            mapper = SheetMapper(self.config.dataset.google_sheet)

        for session_path in self._find_session_dirs(incoming):
            result = self._scan_session(session_path, mapper=mapper)
            if result:
                rows.append({
                    "participant_id": result.subject_id,
                    "session_id": result.session_id,
                    "dicom_path": str(result.session_path),
                    "recruitment_id": result.recruitment_id or "",
                })
                scans_by_session[(result.subject_id, result.session_id)] = result.scans

        log.info("scan.completed", sessions_found=len(rows))

        df = pd.DataFrame(rows, columns=["participant_id", "session_id", "dicom_path", "recruitment_id"])
        return df, scans_by_session

    def _find_session_dirs(self, root: Path) -> list[Path]:
        """Find directories that look like DICOM sessions."""
        sessions = []

        if not root.exists():
            return sessions

        if self._use_sheet_mapping():
            # Flat layout: each directory under root is a ScanID
            for entry in sorted(root.iterdir()):
                if entry.is_dir() and not entry.name.startswith("."):
                    sessions.append(entry)
            return sessions

        if self.config.dataset.dicom_participant_first:
            # /root/subject/session/
            for subject_dir in sorted(root.iterdir()):
                if subject_dir.is_dir() and not subject_dir.name.startswith("."):
                    for session_dir in sorted(subject_dir.iterdir()):
                        if session_dir.is_dir() and self._has_dicoms(session_dir):
                            sessions.append(session_dir)
        else:
            # /root/session/subject/
            for session_dir in sorted(root.iterdir()):
                if session_dir.is_dir() and not session_dir.name.startswith("."):
                    for subject_dir in sorted(session_dir.iterdir()):
                        if subject_dir.is_dir() and self._has_dicoms(subject_dir):
                            sessions.append(subject_dir)

        return sessions

    def _has_dicoms(self, path: Path) -> bool:
        """Check if directory contains DICOM files."""
        import pydicom

        for f in path.rglob("*"):
            if f.is_file() and f.suffix.lower() in (".dcm", ".ima", ""):
                try:
                    pydicom.dcmread(f, stop_before_pixels=True, force=True)
                    return True
                except Exception:
                    continue
        return False

    def _scan_session(
        self,
        session_path: Path,
        mapper: "SheetMapper | None" = None,
    ) -> SessionScanResult | None:
        """Scan a session directory for DICOM series."""
        if mapper is not None:
            scan_id = session_path.name
            resolved = mapper.resolve(scan_id)
            scans = self._identify_scans(session_path)
            return SessionScanResult(
                session_path=session_path,
                subject_id=resolved.participant_id,
                session_id=resolved.session_id,
                scans=scans,
                recruitment_id=resolved.recruitment_id,
            )

        parsed = parse_dicom_path(
            session_path, self.config.dataset.dicom_participant_first
        )
        if not parsed:
            return None

        subject_id, session_id = parsed
        scans = self._identify_scans(session_path)

        return SessionScanResult(
            session_path=session_path,
            subject_id=subject_id,
            session_id=session_id,
            scans=scans,
        )

    def _identify_scans(self, session_path: Path) -> list[ScanInfo]:
        """Identify all DICOM series in a session directory."""
        import pydicom

        series: dict[str, ScanInfo] = {}

        for dcm_file in session_path.rglob("*"):
            if not dcm_file.is_file():
                continue
            try:
                ds = pydicom.dcmread(dcm_file, stop_before_pixels=True, force=True)
                uid = str(ds.SeriesInstanceUID)
                desc = str(getattr(ds, "SeriesDescription", "Unknown"))

                if uid not in series:
                    series[uid] = ScanInfo(
                        series_description=desc,
                        file_count=1,
                        series_uid=uid,
                    )
                else:
                    series[uid].file_count += 1
            except Exception:
                continue

        return list(series.values())
