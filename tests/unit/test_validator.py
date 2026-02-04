"""Tests for session validator."""

import pytest

from neuroflow.config import NeuroflowConfig, ProtocolConfig, ScanRequirement
from neuroflow.discovery.scanner import ScanInfo
from neuroflow.discovery.validator import SessionValidator


@pytest.fixture
def validator(config: NeuroflowConfig) -> SessionValidator:
    return SessionValidator(config)


def test_validate_valid_session(validator: SessionValidator):
    """Test validation of a session with all required scans."""
    scans = [
        ScanInfo(series_description="T1 MPRAGE GRAPPA", file_count=176, series_uid="1.2.3"),
        ScanInfo(series_description="FLAIR 3D", file_count=48, series_uid="1.2.4"),
    ]
    result = validator.validate(scans)
    assert result.is_valid is True
    assert "T1w" in result.scans_found


def test_validate_missing_required_scan(validator: SessionValidator):
    """Test validation fails when required scan is missing."""
    scans = [
        ScanInfo(series_description="FLAIR 3D", file_count=48, series_uid="1.2.4"),
    ]
    result = validator.validate(scans)
    assert result.is_valid is False
    assert "T1w" in result.missing_required


def test_validate_insufficient_files(validator: SessionValidator):
    """Test validation fails when file count is below minimum."""
    scans = [
        ScanInfo(series_description="T1 MPRAGE GRAPPA", file_count=50, series_uid="1.2.3"),
    ]
    result = validator.validate(scans)
    assert result.is_valid is False
    assert "T1w" in result.missing_required


def test_validate_no_required_scans(tmp_paths):
    """Test validation with no required scans (just min file count)."""
    from neuroflow.config import (
        DatabaseConfig,
        DatasetConfig,
        LoggingConfig,
        PathConfig,
    )

    config = NeuroflowConfig(
        paths=PathConfig(
            dicom_incoming=tmp_paths["dicom_incoming"],
            bids_root=tmp_paths["bids_root"],
            derivatives=tmp_paths["derivatives"],
        ),
        protocol=ProtocolConfig(bids_conversion_min_files=5),
        logging=LoggingConfig(level="DEBUG", format="console"),
    )
    validator = SessionValidator(config)

    scans = [
        ScanInfo(series_description="Some scan", file_count=10, series_uid="1.2.3"),
    ]
    result = validator.validate(scans)
    assert result.is_valid is True


def test_validate_no_required_scans_below_minimum(tmp_paths):
    """Test validation fails when total files below minimum."""
    from neuroflow.config import LoggingConfig, PathConfig

    config = NeuroflowConfig(
        paths=PathConfig(
            dicom_incoming=tmp_paths["dicom_incoming"],
            bids_root=tmp_paths["bids_root"],
            derivatives=tmp_paths["derivatives"],
        ),
        protocol=ProtocolConfig(bids_conversion_min_files=50),
        logging=LoggingConfig(level="DEBUG", format="console"),
    )
    validator = SessionValidator(config)

    scans = [
        ScanInfo(series_description="Some scan", file_count=10, series_uid="1.2.3"),
    ]
    result = validator.validate(scans)
    assert result.is_valid is False
