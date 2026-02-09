"""Shared test fixtures."""

import pytest
from pathlib import Path

from neuroflow.config import (
    DatasetConfig,
    ExecutionConfig,
    LoggingConfig,
    NeuroflowConfig,
    PathConfig,
    PipelinesConfig,
    ProtocolConfig,
    ScanRequirement,
)
from neuroflow.core.logging import setup_logging


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
        "state_dir": tmp_path / "state",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


@pytest.fixture
def config(tmp_paths: dict[str, Path]) -> NeuroflowConfig:
    """Create a test configuration."""
    return NeuroflowConfig(
        paths=PathConfig(
            dicom_incoming=tmp_paths["dicom_incoming"],
            bids_root=tmp_paths["bids_root"],
            derivatives=tmp_paths["derivatives"],
            work_dir=tmp_paths["work_dir"],
            log_dir=tmp_paths["log_dir"],
        ),
        execution=ExecutionConfig(
            max_workers=1,
            state_dir=tmp_paths["state_dir"],
        ),
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
def sample_config_path(config: NeuroflowConfig, tmp_path: Path) -> Path:
    """Create a YAML config file for testing."""
    import yaml

    config_path = tmp_path / "test_config.yaml"

    # Convert config to dict for YAML serialization
    config_dict = {
        "paths": {
            "dicom_incoming": str(config.paths.dicom_incoming),
            "bids_root": str(config.paths.bids_root),
            "derivatives": str(config.paths.derivatives),
            "work_dir": str(config.paths.work_dir),
            "log_dir": str(config.paths.log_dir),
        },
        "execution": {
            "max_workers": config.execution.max_workers,
            "state_dir": str(config.execution.state_dir),
            "log_per_session": config.execution.log_per_session,
        },
        "dataset": {
            "name": config.dataset.name,
            "session_ids": config.dataset.session_ids,
            "dicom_participant_first": config.dataset.dicom_participant_first,
        },
        "protocol": {
            "stability_wait_minutes": config.protocol.stability_wait_minutes,
            "bids_conversion_min_files": config.protocol.bids_conversion_min_files,
        },
        "logging": {
            "level": config.logging.level,
            "format": config.logging.format,
        },
    }

    with open(config_path, "w") as f:
        yaml.dump(config_dict, f)

    return config_path
