"""Integration tests for VoxelOps adapter.

These tests validate the integration between neuroflow and VoxelOps,
including schema building and pipeline execution with the new plain-data API.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from neuroflow.adapters.voxelops import VoxelopsAdapter, PipelineResult
from neuroflow.config import (
    BidsConversionConfig,
    NeuroflowConfig,
    PipelineConfig,
    PipelinesConfig,
)


@pytest.fixture
def config_with_voxelops(config):
    """Create config with VoxelOps pipeline configurations."""
    config.pipelines = PipelinesConfig(
        bids_conversion=BidsConversionConfig(
            enabled=True,
            tool="heudiconv",
            timeout_minutes=60,
            voxelops_config={
                "heuristic": "/etc/test_heuristic.py",
                "bids_validator": True,
                "overwrite": False,
            },
        ),
        session_level=[
            PipelineConfig(
                name="qsiprep",
                enabled=True,
                runner="voxelops.runners.qsiprep.run_qsiprep",
                timeout_minutes=720,
                voxelops_config={
                    "nprocs": 8,
                    "mem_mb": 16000,
                    "fs_license": "/opt/freesurfer/license.txt",
                },
                requirements={"bids_suffixes": ["dwi"]},
            ),
        ],
        subject_level=[
            PipelineConfig(
                name="qsirecon",
                enabled=True,
                runner="voxelops.runners.qsirecon.run_qsirecon",
                timeout_minutes=480,
                voxelops_config={
                    "nprocs": 8,
                    "mem_mb": 16000,
                    "fs_license": "/opt/freesurfer/license.txt",
                },
            ),
        ],
    )
    return config


@pytest.fixture
def adapter(config_with_voxelops):
    """Create VoxelOps adapter."""
    return VoxelopsAdapter(config_with_voxelops)


class TestAdapterInitialization:
    """Test adapter initialization and availability checks."""

    def test_adapter_initializes_successfully(self, adapter):
        """Test that adapter initializes without errors."""
        assert adapter is not None
        assert hasattr(adapter, "_voxelops_available")

    def test_check_voxelops_available_returns_bool(self, adapter):
        """Test that VoxelOps availability check returns boolean."""
        assert isinstance(adapter._voxelops_available, bool)

    @patch("neuroflow.adapters.voxelops.importlib.import_module")
    def test_voxelops_not_available_logs_warning(
        self, mock_import, config_with_voxelops
    ):
        """Test that missing VoxelOps logs a warning."""
        mock_import.side_effect = ImportError("No module named 'voxelops'")

        adapter = VoxelopsAdapter(config_with_voxelops)

        assert adapter._voxelops_available is False


class TestPipelineConfigRetrieval:
    """Test pipeline configuration retrieval."""

    def test_get_bids_conversion_config(self, adapter):
        """Test retrieving BIDS conversion pipeline config."""
        config = adapter._get_pipeline_config("bids_conversion")

        assert config is not None
        assert config.name == "bids_conversion"
        assert config.runner == "voxelops.runners.heudiconv.run_heudiconv"
        assert "heuristic" in config.voxelops_config

    def test_get_session_level_config(self, adapter):
        """Test retrieving session-level pipeline config."""
        config = adapter._get_pipeline_config("qsiprep")

        assert config is not None
        assert config.name == "qsiprep"
        assert config.runner == "voxelops.runners.qsiprep.run_qsiprep"

    def test_get_subject_level_config(self, adapter):
        """Test retrieving subject-level pipeline config."""
        config = adapter._get_pipeline_config("qsirecon")

        assert config is not None
        assert config.name == "qsirecon"
        assert config.runner == "voxelops.runners.qsirecon.run_qsirecon"

    def test_get_unknown_pipeline_returns_none(self, adapter):
        """Test that unknown pipeline returns None."""
        config = adapter._get_pipeline_config("unknown_pipeline")

        assert config is None


class TestVoxelOpsExecution:
    """Test VoxelOps pipeline execution with new plain-data API."""

    def test_run_unknown_pipeline_returns_error(self, adapter):
        """Test running unknown pipeline returns error result."""
        result = adapter.run("unknown_pipeline", participant_id="sub-001")

        assert result.success is False
        assert "Unknown pipeline" in result.error_message


class TestVoxelopsRequired:
    """Test that voxelops must be installed."""

    def test_run_without_voxelops_returns_error(self, config_with_voxelops):
        """Test that running without voxelops gives a clear error."""
        adapter = VoxelopsAdapter(config_with_voxelops)
        adapter._voxelops_available = False

        result = adapter.run(
            "bids_conversion",
            participant_id="sub-001",
            session_id="ses-baseline",
        )

        assert result.success is False
        assert "voxelops is not installed" in result.error_message

    def test_unrecognized_runner_returns_error(self, config_with_voxelops):
        """Test that an unrecognized runner gives a clear error."""
        config_with_voxelops.pipelines.session_level[0].runner = "some.unknown.runner"

        adapter = VoxelopsAdapter(config_with_voxelops)
        adapter._voxelops_available = True

        result = adapter.run("qsiprep", participant_id="sub-001")

        assert result.success is False
        assert "not recognized" in result.error_message


class TestRunnerResolution:
    """Test short-form and full-form runner name resolution."""

    def test_full_runner_name_resolves(self, adapter):
        """Test that full runner names resolve correctly."""
        assert adapter._resolve_runner("voxelops.runners.qsiprep.run_qsiprep") == \
            "voxelops.runners.qsiprep.run_qsiprep"

    def test_short_runner_name_resolves(self, adapter):
        """Test that short runner names are expanded."""
        assert adapter._resolve_runner("voxelops.runners.qsiprep") == \
            "voxelops.runners.qsiprep.run_qsiprep"

    def test_unknown_runner_returns_none(self, adapter):
        """Test that unknown runners return None."""
        assert adapter._resolve_runner("some.unknown.runner") is None

    def test_run_accepts_string_args(self, adapter):
        """Test that run() accepts participant_id and session_id strings."""
        adapter._voxelops_available = False

        result = adapter.run(
            "bids_conversion",
            participant_id="sub-001",
            session_id="ses-baseline",
            dicom_path=Path("/data/sub-001/ses-baseline"),
        )

        assert result.success is False
        assert "voxelops is not installed" in result.error_message
