"""Tests for configuration loading."""

import pytest
from pathlib import Path

from neuroflow.config import (
    DatabaseConfig,
    DatasetConfig,
    NeuroflowConfig,
    PathConfig,
    PipelineConfig,
    PipelinesConfig,
    ProtocolConfig,
    ScanRequirement,
)


def test_config_defaults():
    """Test that default values are applied."""
    config = NeuroflowConfig(
        paths=PathConfig(
            dicom_incoming=Path("/tmp/incoming"),
            bids_root=Path("/tmp/bids"),
            derivatives=Path("/tmp/derivatives"),
        ),
    )
    assert config.database.url == "sqlite:///neuroflow.db"
    assert config.redis.url == "redis://localhost:6379/0"
    assert config.dataset.name == "brainbank"
    assert config.container_runtime == "apptainer"
    assert config.compute_environment == "local"


def test_config_from_yaml(tmp_path: Path):
    """Test loading from YAML file."""
    yaml_content = """
paths:
  dicom_incoming: /tmp/incoming
  bids_root: /tmp/bids
  derivatives: /tmp/derivatives

database:
  url: "sqlite:///test.db"

dataset:
  name: testset
  session_ids: ["baseline"]
  dicom_participant_first: false

logging:
  level: DEBUG
  format: console
"""
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(yaml_content)

    config = NeuroflowConfig.from_yaml(config_file)
    assert config.paths.dicom_incoming == Path("/tmp/incoming")
    assert config.database.url == "sqlite:///test.db"
    assert config.dataset.name == "testset"
    assert config.dataset.dicom_participant_first is False
    assert config.logging.level == "DEBUG"


def test_scan_requirement():
    """Test ScanRequirement model."""
    req = ScanRequirement(
        name="T1w",
        series_description_pattern=".*T1.*MPRAGE.*",
        min_files=170,
        max_files=220,
    )
    assert req.name == "T1w"
    assert req.min_files == 170
    assert req.max_files == 220


def test_pipeline_config():
    """Test PipelineConfig model."""
    pipeline = PipelineConfig(
        name="freesurfer",
        runner="voxelops.runners.freesurfer",
        container="freesurfer/freesurfer:7.4.1",
        timeout_minutes=720,
        requirements={"bids_suffixes": ["T1w"]},
    )
    assert pipeline.name == "freesurfer"
    assert pipeline.enabled is True
    assert pipeline.retries == 2
    assert pipeline.timeout_minutes == 720


def test_config_with_pipelines(tmp_path: Path):
    """Test config with pipeline definitions."""
    yaml_content = """
paths:
  dicom_incoming: /tmp/incoming
  bids_root: /tmp/bids
  derivatives: /tmp/derivatives

pipelines:
  session_level:
    - name: mriqc
      runner: voxelops.runners.mriqc
      container: nipreps/mriqc:24.0.0
      timeout_minutes: 120
      requirements:
        bids_suffixes: ["T1w"]
"""
    config_file = tmp_path / "pipelines_config.yaml"
    config_file.write_text(yaml_content)

    config = NeuroflowConfig.from_yaml(config_file)
    assert len(config.pipelines.session_level) == 1
    assert config.pipelines.session_level[0].name == "mriqc"
    assert config.pipelines.session_level[0].container == "nipreps/mriqc:24.0.0"
