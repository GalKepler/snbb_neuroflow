"""Session validation against protocol requirements."""

import re
from dataclasses import dataclass, field

import structlog

from neuroflow.config import NeuroflowConfig, ScanRequirement
from neuroflow.discovery.scanner import ScanInfo

log = structlog.get_logger("validator")


@dataclass
class ValidationResult:
    """Result of session validation."""

    is_valid: bool
    scans_found: dict[str, int]
    missing_required: list[str] = field(default_factory=list)
    message: str = ""


class SessionValidator:
    """Validate sessions against protocol requirements."""

    def __init__(self, config: NeuroflowConfig):
        self.config = config

    def validate(self, scans: list[ScanInfo]) -> ValidationResult:
        """Validate a session's scans against protocol."""
        scans_found: dict[str, int] = {}
        matched_required: set[str] = set()

        # Check each scan against required patterns
        for scan in scans:
            for req in self.config.protocol.required_scans:
                if re.match(
                    req.series_description_pattern,
                    scan.series_description,
                    re.IGNORECASE,
                ):
                    scans_found[req.name] = scan.file_count

                    if scan.file_count >= req.min_files:
                        if req.max_files is None or scan.file_count <= req.max_files:
                            matched_required.add(req.name)

            # Also check optional scans
            for req in self.config.protocol.optional_scans:
                if re.match(
                    req.series_description_pattern,
                    scan.series_description,
                    re.IGNORECASE,
                ):
                    scans_found[req.name] = scan.file_count

        # If no required scans are configured, check minimum file count
        if not self.config.protocol.required_scans:
            total_files = sum(s.file_count for s in scans)
            is_valid = total_files >= self.config.protocol.bids_conversion_min_files
            message = (
                f"Session has {total_files} DICOM files "
                f"(minimum: {self.config.protocol.bids_conversion_min_files})"
            )
            return ValidationResult(
                is_valid=is_valid,
                scans_found=scans_found,
                message=message,
            )

        # Find missing required scans
        required_names = {r.name for r in self.config.protocol.required_scans}
        missing = sorted(required_names - matched_required)

        is_valid = len(missing) == 0

        if is_valid:
            message = f"Session valid: {len(scans_found)} scan types found"
        else:
            message = f"Missing required scans: {', '.join(missing)}"

        return ValidationResult(
            is_valid=is_valid,
            scans_found=scans_found,
            missing_required=missing,
            message=message,
        )
