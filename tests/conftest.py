"""Shared test fixtures."""

import pytest
from pathlib import Path

from neuroflow.config import (
    DatabaseConfig,
    DatasetConfig,
    LoggingConfig,
    NeuroflowConfig,
    PathConfig,
    PipelinesConfig,
    ProtocolConfig,
    ScanRequirement,
)
from neuroflow.core.logging import setup_logging
from neuroflow.core.state import StateManager


@pytest.fixture(autouse=True)
def _setup_logging():
    """Configure logging for tests."""
    setup_logging(level="DEBUG", format="console")


@pytest.fixture
def tmp_paths(tmp_path: Path) -> dict[str, Path]:
    """Create temporary directory structure for tests."""
    dirs = {
        "dicom_incoming": tmp_path / "incoming",
        "bids_root": tmp_path / "bids",
        "derivatives": tmp_path / "derivatives",
        "work_dir": tmp_path / "work",
        "log_dir": tmp_path / "logs",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


@pytest.fixture
def config(tmp_paths: dict[str, Path]) -> NeuroflowConfig:
    """Create a test configuration with SQLite in-memory."""
    return NeuroflowConfig(
        paths=PathConfig(
            dicom_incoming=tmp_paths["dicom_incoming"],
            bids_root=tmp_paths["bids_root"],
            derivatives=tmp_paths["derivatives"],
            work_dir=tmp_paths["work_dir"],
            log_dir=tmp_paths["log_dir"],
        ),
        database=DatabaseConfig(url="sqlite:///:memory:"),
        dataset=DatasetConfig(
            name="test",
            session_ids=["baseline", "followup"],
            dicom_participant_first=True,
        ),
        protocol=ProtocolConfig(
            stability_wait_minutes=0,
            bids_conversion_min_files=5,
            required_scans=[
                ScanRequirement(
                    name="T1w",
                    series_description_pattern=".*T1.*MPRAGE.*",
                    min_files=170,
                ),
            ],
        ),
        logging=LoggingConfig(level="DEBUG", format="console"),
    )


@pytest.fixture
def state(config: NeuroflowConfig) -> StateManager:
    """Create a StateManager with initialized database."""
    sm = StateManager(config)
    sm.init_db()
    return sm
