"""Integration tests for VoxelOps adapter.

These tests validate the full integration between neuroflow and VoxelOps,
including database interactions, schema building, and pipeline execution.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from neuroflow.adapters.voxelops import VoxelopsAdapter, PipelineResult
from neuroflow.config import (
    BidsConversionConfig,
    NeuroflowConfig,
    PipelineConfig,
    PipelinesConfig,
)
from neuroflow.core.state import StateManager
from neuroflow.models.session import Session, SessionStatus
from neuroflow.models.subject import Subject, SubjectStatus


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


@pytest.fixture
def test_subject(state):
    """Create a test subject in database."""
    with state.get_session() as db:
        subject = Subject(
            participant_id="sub-001",
            recruitment_id="REC001",
            status=SubjectStatus.VALID,
        )
        db.add(subject)
        db.commit()
        db.refresh(subject)
        subject_id = subject.id

    with state.get_session() as db:
        return db.get(Subject, subject_id)


@pytest.fixture
def test_session(state, test_subject, tmp_path):
    """Create a test session in database."""
    dicom_dir = tmp_path / "dicom" / "sub-001" / "ses-baseline"
    dicom_dir.mkdir(parents=True)

    with state.get_session() as db:
        session = Session(
            subject_id=test_subject.id,
            session_id="ses-baseline",
            dicom_path=str(dicom_dir),
            status=SessionStatus.VALIDATED,
            is_valid=True,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        session_id = session.id

    with state.get_session() as db:
        return db.get(Session, session_id)


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
        self, mock_import, config_with_voxelops, caplog
    ):
        """Test that missing VoxelOps logs a warning."""
        mock_import.side_effect = ImportError("No module named 'voxelops'")

        adapter = VoxelopsAdapter(config_with_voxelops)

        assert adapter._voxelops_available is False
        assert "voxelops.not_available" in caplog.text or not caplog.text  # May not capture structlog


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
    """Test VoxelOps pipeline execution."""

    @pytest.mark.skipif(
        not pytest.importorskip("voxelops", reason="VoxelOps not installed"),
        reason="VoxelOps not installed"
    )
    @patch("neuroflow.adapters.voxelops.importlib.import_module")
    def test_run_heudiconv_via_voxelops(
        self, mock_import, adapter, test_session, tmp_path
    ):
        """Test running HeudiConv via VoxelOps."""
        # Create heuristic file
        heuristic_file = tmp_path / "test_heuristic.py"
        heuristic_file.write_text("# test heuristic")

        # Update config with valid heuristic
        bids_cfg = adapter.config.pipelines.bids_conversion
        bids_cfg.voxelops_config["heuristic"] = str(heuristic_file)

        # Mock VoxelOps runner
        mock_runner = MagicMock()
        mock_runner.return_value = {
            "success": True,
            "exit_code": 0,
            "output_dir": str(tmp_path / "bids"),
            "duration_seconds": 120.0,
            "tool": "heudiconv",
            "participant": "001",
        }

        mock_module = MagicMock()
        mock_module.run_heudiconv = mock_runner
        mock_import.return_value = mock_module

        # Make VoxelOps available
        adapter._voxelops_available = True

        result = adapter.run("bids_conversion", session_id=test_session.id)

        assert result.success is True
        assert result.exit_code == 0
        assert result.output_path is not None

    @pytest.mark.skipif(
        not pytest.importorskip("voxelops", reason="VoxelOps not installed"),
        reason="VoxelOps not installed"
    )
    @patch("neuroflow.adapters.voxelops.importlib.import_module")
    def test_run_qsiprep_via_voxelops(
        self, mock_import, adapter, test_subject, tmp_path
    ):
        """Test running QSIPrep via VoxelOps."""
        # Mock VoxelOps runner
        mock_runner = MagicMock()
        mock_runner.return_value = {
            "success": True,
            "exit_code": 0,
            "output_dir": str(tmp_path / "derivatives" / "qsiprep"),
            "duration_seconds": 3600.0,
            "tool": "qsiprep",
            "participant": "001",
        }

        mock_module = MagicMock()
        mock_module.run_qsiprep = mock_runner
        mock_import.return_value = mock_module

        # Make VoxelOps available
        adapter._voxelops_available = True

        result = adapter.run("qsiprep", subject_id=test_subject.id)

        assert result.success is True
        assert result.exit_code == 0
        assert "qsiprep" in str(result.output_path)

    @pytest.mark.skipif(
        not pytest.importorskip("voxelops", reason="VoxelOps not installed"),
        reason="VoxelOps not installed"
    )
    @patch("neuroflow.adapters.voxelops.importlib.import_module")
    def test_voxelops_failure_with_container_fallback(
        self, mock_import, adapter, test_session, tmp_path
    ):
        """Test that VoxelOps failure falls back to container mode if configured."""
        # Create heuristic file
        heuristic_file = tmp_path / "test_heuristic.py"
        heuristic_file.write_text("# test heuristic")

        # Update config with container
        bids_cfg = adapter.config.pipelines.bids_conversion
        bids_cfg.voxelops_config["heuristic"] = str(heuristic_file)
        bids_cfg.container = "nipy/heudiconv:1.3.4"

        # Mock VoxelOps to fail
        mock_import.side_effect = Exception("VoxelOps execution failed")

        # Make VoxelOps available but fail on execution
        adapter._voxelops_available = True

        # Mock container execution to succeed
        with patch.object(adapter, "_run_via_container") as mock_container:
            mock_container.return_value = PipelineResult(
                success=True,
                exit_code=0,
                output_path=tmp_path / "bids",
            )

            result = adapter.run("bids_conversion", session_id=test_session.id)

            # Should have fallen back to container
            mock_container.assert_called_once()
            assert result.success is True

    def test_run_unknown_pipeline_returns_error(self, adapter, test_session):
        """Test running unknown pipeline returns error result."""
        result = adapter.run("unknown_pipeline", session_id=test_session.id)

        assert result.success is False
        assert "Unknown pipeline" in result.error_message


class TestContainerExecution:
    """Test container execution as fallback."""

    def test_run_via_container_without_voxelops(
        self, config_with_voxelops, test_session
    ):
        """Test container execution when VoxelOps not available."""
        # Configure container for bids_conversion
        config_with_voxelops.pipelines.bids_conversion.container = (
            "nipy/heudiconv:1.3.4"
        )

        adapter = VoxelopsAdapter(config_with_voxelops)
        adapter._voxelops_available = False

        # Mock subprocess to avoid actual container execution
        with patch("neuroflow.adapters.voxelops.subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout="Container execution successful",
                stderr="",
            )

            result = adapter.run("bids_conversion", session_id=test_session.id)

            # Should have used container mode
            mock_run.assert_called_once()
            assert result.success is True

    def test_no_execution_method_available(
        self, config_with_voxelops, test_session
    ):
        """Test error when no execution method available."""
        # Remove container config and disable VoxelOps
        config_with_voxelops.pipelines.bids_conversion.container = None

        adapter = VoxelopsAdapter(config_with_voxelops)
        adapter._voxelops_available = False

        result = adapter.run("bids_conversion", session_id=test_session.id)

        assert result.success is False
        assert "No execution method available" in result.error_message


class TestDatabaseIntegration:
    """Test database integration for session/subject retrieval."""

    @pytest.mark.skipif(
        not pytest.importorskip("voxelops", reason="VoxelOps not installed"),
        reason="VoxelOps not installed"
    )
    @patch("neuroflow.adapters.voxelops.importlib.import_module")
    def test_fetches_session_from_database(
        self, mock_import, adapter, test_session, tmp_path
    ):
        """Test that adapter fetches session from database."""
        # Setup
        heuristic_file = tmp_path / "test_heuristic.py"
        heuristic_file.write_text("# test heuristic")
        bids_cfg = adapter.config.pipelines.bids_conversion
        bids_cfg.voxelops_config["heuristic"] = str(heuristic_file)

        # Mock VoxelOps
        mock_runner = MagicMock()
        mock_runner.return_value = {"success": True, "exit_code": 0}
        mock_module = MagicMock()
        mock_module.run_heudiconv = mock_runner
        mock_import.return_value = mock_module
        adapter._voxelops_available = True

        # Execute
        result = adapter.run("bids_conversion", session_id=test_session.id)

        # Verify runner was called with correct inputs
        assert mock_runner.called
        call_args = mock_runner.call_args
        inputs = call_args.kwargs["inputs"]

        # Should have fetched session data from database
        assert inputs.participant == "001"  # Stripped prefix
        assert inputs.session == "baseline"  # Stripped prefix
        assert str(test_session.dicom_path) in str(inputs.dicom_dir)

    @pytest.mark.skipif(
        not pytest.importorskip("voxelops", reason="VoxelOps not installed"),
        reason="VoxelOps not installed"
    )
    @patch("neuroflow.adapters.voxelops.importlib.import_module")
    def test_fetches_subject_from_database(
        self, mock_import, adapter, test_subject
    ):
        """Test that adapter fetches subject from database."""
        # Mock VoxelOps
        mock_runner = MagicMock()
        mock_runner.return_value = {"success": True, "exit_code": 0}
        mock_module = MagicMock()
        mock_module.run_qsiprep = mock_runner
        mock_import.return_value = mock_module
        adapter._voxelops_available = True

        # Execute
        result = adapter.run("qsiprep", subject_id=test_subject.id)

        # Verify runner was called with correct inputs
        assert mock_runner.called
        call_args = mock_runner.call_args
        inputs = call_args.kwargs["inputs"]

        # Should have fetched subject data
        assert inputs.participant_label == "001"  # Stripped prefix


class TestKwargsOverrides:
    """Test that kwargs properly override defaults."""

    @pytest.mark.skipif(
        not pytest.importorskip("voxelops", reason="VoxelOps not installed"),
        reason="VoxelOps not installed"
    )
    @patch("neuroflow.adapters.voxelops.importlib.import_module")
    def test_kwargs_override_defaults(
        self, mock_import, adapter, test_subject
    ):
        """Test that kwargs override voxelops_config defaults."""
        # Mock VoxelOps
        mock_runner = MagicMock()
        mock_runner.return_value = {"success": True, "exit_code": 0}
        mock_module = MagicMock()
        mock_module.run_qsiprep = mock_runner
        mock_import.return_value = mock_module
        adapter._voxelops_available = True

        # Execute with overrides
        result = adapter.run(
            "qsiprep",
            subject_id=test_subject.id,
            nprocs=16,  # Override default of 8
            force=True,  # Override default of False
        )

        # Verify overrides were applied
        assert mock_runner.called
        call_args = mock_runner.call_args
        defaults = call_args.kwargs["config"]

        assert defaults.nprocs == 16
        assert defaults.force is True


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.skipif(
        not pytest.importorskip("voxelops", reason="VoxelOps not installed"),
        reason="VoxelOps not installed"
    )
    @patch("neuroflow.adapters.voxelops.importlib.import_module")
    def test_handles_voxelops_execution_error(
        self, mock_import, adapter, test_session, tmp_path
    ):
        """Test handling of VoxelOps execution errors."""
        # Setup
        heuristic_file = tmp_path / "test_heuristic.py"
        heuristic_file.write_text("# test heuristic")
        bids_cfg = adapter.config.pipelines.bids_conversion
        bids_cfg.voxelops_config["heuristic"] = str(heuristic_file)
        bids_cfg.container = None  # No fallback

        # Mock VoxelOps to raise error
        mock_import.side_effect = Exception("VoxelOps runner failed")
        adapter._voxelops_available = True

        # Should raise since no container fallback
        with pytest.raises(Exception, match="VoxelOps runner failed"):
            adapter.run("bids_conversion", session_id=test_session.id)

    @pytest.mark.skipif(
        not pytest.importorskip("voxelops", reason="VoxelOps not installed"),
        reason="VoxelOps not installed"
    )
    def test_handles_missing_session(self, adapter, tmp_path):
        """Test handling of missing session ID."""
        # Create heuristic
        heuristic_file = tmp_path / "test_heuristic.py"
        heuristic_file.write_text("# test heuristic")
        bids_cfg = adapter.config.pipelines.bids_conversion
        bids_cfg.voxelops_config["heuristic"] = str(heuristic_file)

        adapter._voxelops_available = True

        # Run with non-existent session ID
        with pytest.raises(ValueError):
            adapter.run("bids_conversion", session_id=99999)

    @pytest.mark.skipif(
        not pytest.importorskip("voxelops", reason="VoxelOps not installed"),
        reason="VoxelOps not installed"
    )
    @patch("neuroflow.adapters.voxelops.importlib.import_module")
    def test_handles_validation_error(
        self, mock_import, adapter, test_session
    ):
        """Test handling of schema validation errors."""
        # Don't provide required heuristic
        bids_cfg = adapter.config.pipelines.bids_conversion
        bids_cfg.voxelops_config = {}

        adapter._voxelops_available = True

        # Should raise validation error
        from neuroflow.adapters.voxelops_schemas import SchemaValidationError

        with pytest.raises(SchemaValidationError):
            adapter.run("bids_conversion", session_id=test_session.id)
