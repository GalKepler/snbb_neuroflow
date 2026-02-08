"""Tests for VoxelOps schema mapping."""

import pytest
from pathlib import Path
from unittest.mock import Mock

from neuroflow.adapters.voxelops import PipelineResult
from neuroflow.adapters.voxelops_schemas import (
    BuilderContext,
    HeudiconvSchemaBuilder,
    QSIPrepSchemaBuilder,
    QSIReconSchemaBuilder,
    QSIParcSchemaBuilder,
    SchemaValidationError,
    get_schema_builder,
    parse_voxelops_result,
)
from neuroflow.config import (
    NeuroflowConfig,
    PipelineConfig,
    BidsConversionConfig,
    PipelinesConfig,
)

# Check if VoxelOps is available
try:
    import voxelops
    VOXELOPS_AVAILABLE = True
except ImportError:
    VOXELOPS_AVAILABLE = False

# Skip marker for tests requiring VoxelOps
requires_voxelops = pytest.mark.skipif(
    not VOXELOPS_AVAILABLE,
    reason="VoxelOps not installed"
)


@pytest.fixture
def mock_subject():
    """Create a mock Subject."""
    subject = Mock()
    subject.id = 1
    subject.participant_id = "sub-001"
    return subject


@pytest.fixture
def mock_session(mock_subject):
    """Create a mock Session."""
    session = Mock()
    session.id = 1
    session.session_id = "ses-baseline"
    session.dicom_path = "/data/dicom/sub-001/ses-baseline"
    session.subject = mock_subject
    return session


@pytest.fixture
def mock_config(tmp_path):
    """Create a mock NeuroflowConfig."""
    config = Mock(spec=NeuroflowConfig)
    config.paths = Mock()
    config.paths.bids_root = tmp_path / "bids"
    config.paths.derivatives = tmp_path / "derivatives"
    config.paths.work_dir = tmp_path / "work"
    config.pipelines = Mock(spec=PipelinesConfig)
    config.pipelines.bids_conversion = BidsConversionConfig(
        enabled=True,
        tool="heudiconv",
        heuristic_file="/etc/test.py",
    )
    return config


@pytest.fixture
def heudiconv_pipeline_config(tmp_path):
    """Create HeudiConv pipeline config."""
    return PipelineConfig(
        name="bids_conversion",
        runner="voxelops.runners.heudiconv.run_heudiconv",
        voxelops_config={
            "heuristic": str(tmp_path / "test_heuristic.py"),
            "bids_validator": True,
            "overwrite": False,
        },
    )


@pytest.fixture
def qsiprep_pipeline_config():
    """Create QSIPrep pipeline config."""
    return PipelineConfig(
        name="qsiprep",
        runner="voxelops.runners.qsiprep.run_qsiprep",
        voxelops_config={
            "nprocs": 8,
            "mem_mb": 16000,
            "fs_license": "/opt/freesurfer/license.txt",
        },
    )


@pytest.fixture
def qsirecon_pipeline_config(tmp_path):
    """Create QSIRecon pipeline config."""
    return PipelineConfig(
        name="qsirecon",
        runner="voxelops.runners.qsirecon.run_qsirecon",
        voxelops_config={
            "nprocs": 8,
            "mem_mb": 16000,
            "recon_spec": str(tmp_path / "test_spec.yaml"),
            "fs_license": "/opt/freesurfer/license.txt",
        },
    )


class TestBuilderContext:
    """Test BuilderContext dataclass."""

    def test_participant_id_stored_directly(self, mock_config, heudiconv_pipeline_config):
        """Test that participant_id is stored as plain data."""
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=heudiconv_pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        assert ctx.participant_id == "001"

    def test_participant_id_can_be_none(self, mock_config, heudiconv_pipeline_config):
        """Test that participant_id can be None."""
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=heudiconv_pipeline_config,
            participant_id=None,
        )

        assert ctx.participant_id is None

    def test_session_id_stored_directly(self, mock_config, heudiconv_pipeline_config):
        """Test that session_id is stored as plain data."""
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=heudiconv_pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        assert ctx.session_id == "baseline"

    def test_session_id_can_be_none(self, mock_config, heudiconv_pipeline_config):
        """Test that session_id can be None."""
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=heudiconv_pipeline_config,
            participant_id="001",
            session_id=None,
        )

        assert ctx.session_id is None

    def test_dicom_path_stored_as_path(self, mock_config, heudiconv_pipeline_config):
        """Test that dicom_path is stored as Path object."""
        dicom_path = Path("/data/dicom/sub-001/ses-baseline")
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=heudiconv_pipeline_config,
            participant_id="001",
            dicom_path=dicom_path,
        )

        assert ctx.dicom_path == dicom_path
        assert isinstance(ctx.dicom_path, Path)


class TestHeudiconvSchemaBuilder:
    """Test HeudiConv schema builder."""

    def test_validate_config_requires_heuristic(self, mock_config):
        """Test that validation fails without heuristic."""
        pipeline_config = PipelineConfig(
            name="bids_conversion",
            runner="voxelops.runners.heudiconv.run_heudiconv",
            voxelops_config={},
        )
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        builder = HeudiconvSchemaBuilder()
        with pytest.raises(SchemaValidationError, match="requires 'heuristic'"):
            builder.validate_config(ctx)

    def test_validate_config_checks_heuristic_exists(
        self, mock_config, heudiconv_pipeline_config
    ):
        """Test that validation checks if heuristic file exists."""
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=heudiconv_pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        builder = HeudiconvSchemaBuilder()
        with pytest.raises(SchemaValidationError, match="not found"):
            builder.validate_config(ctx)

    def test_validate_config_succeeds_with_valid_heuristic(
        self, mock_config, tmp_path
    ):
        """Test that validation succeeds with valid heuristic."""
        heuristic_file = tmp_path / "test_heuristic.py"
        heuristic_file.write_text("# test heuristic")

        pipeline_config = PipelineConfig(
            name="bids_conversion",
            runner="voxelops.runners.heudiconv.run_heudiconv",
            voxelops_config={"heuristic": str(heuristic_file)},
        )
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        builder = HeudiconvSchemaBuilder()
        builder.validate_config(ctx)  # Should not raise

    @requires_voxelops
    def test_build_inputs_creates_valid_schema(
        self, mock_config, tmp_path
    ):
        """Test that build_inputs creates valid HeudiconvInputs."""
        from voxelops.schemas.heudiconv import HeudiconvInputs

        heuristic_file = tmp_path / "test_heuristic.py"
        heuristic_file.write_text("# test heuristic")

        pipeline_config = PipelineConfig(
            name="bids_conversion",
            runner="voxelops.runners.heudiconv.run_heudiconv",
            voxelops_config={"heuristic": str(heuristic_file)},
        )
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        builder = HeudiconvSchemaBuilder()
        inputs = builder.build_inputs(ctx)

        assert isinstance(inputs, HeudiconvInputs)
        assert inputs.participant == "001"
        assert inputs.session == "baseline"
        assert inputs.dicom_dir == Path("/data/dicom/sub-001/ses-baseline")
        assert inputs.output_dir == mock_config.paths.bids_root

    @requires_voxelops
    def test_build_inputs_raises_without_dicom_path(self, mock_config, heudiconv_pipeline_config):
        """Test that build_inputs raises without dicom_path."""
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=heudiconv_pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=None,
        )

        builder = HeudiconvSchemaBuilder()
        with pytest.raises(ValueError, match="DICOM path is required"):
            builder.build_inputs(ctx)


class TestQSIPrepSchemaBuilder:
    """Test QSIPrep schema builder."""

    @requires_voxelops
    def test_build_inputs_creates_valid_schema(
        self, mock_config, qsiprep_pipeline_config
    ):
        """Test that build_inputs creates valid QSIPrepInputs."""
        from voxelops.schemas.qsiprep import QSIPrepInputs

        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=qsiprep_pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        builder = QSIPrepSchemaBuilder()
        inputs = builder.build_inputs(ctx)

        assert isinstance(inputs, QSIPrepInputs)
        assert inputs.participant == "001"
        assert inputs.bids_dir == mock_config.paths.bids_root
        assert inputs.output_dir == mock_config.paths.derivatives / "qsiprep"

    @requires_voxelops
    def test_build_inputs_raises_without_participant_id(
        self, mock_config, qsiprep_pipeline_config
    ):
        """Test that build_inputs raises without participant_id."""
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=qsiprep_pipeline_config,
            participant_id=None,
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        builder = QSIPrepSchemaBuilder()
        with pytest.raises(ValueError, match="Participant ID is required"):
            builder.build_inputs(ctx)


class TestQSIReconSchemaBuilder:
    """Test QSIRecon schema builder."""

    def test_validate_config_checks_recon_spec_exists(
        self, mock_config, qsirecon_pipeline_config
    ):
        """Test that validation checks if recon_spec exists."""
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=qsirecon_pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        builder = QSIReconSchemaBuilder()
        with pytest.raises(SchemaValidationError, match="not found"):
            builder.validate_config(ctx)

    @requires_voxelops
    def test_build_inputs_creates_valid_schema(
        self, mock_config, tmp_path
    ):
        """Test that build_inputs creates valid QSIReconInputs."""
        from voxelops.schemas.qsirecon import QSIReconInputs

        recon_spec = tmp_path / "test_spec.yaml"
        recon_spec.write_text("# test spec")

        pipeline_config = PipelineConfig(
            name="qsirecon",
            runner="voxelops.runners.qsirecon.run_qsirecon",
            voxelops_config={"recon_spec": str(recon_spec)},
        )
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        builder = QSIReconSchemaBuilder()
        inputs = builder.build_inputs(ctx)

        assert isinstance(inputs, QSIReconInputs)
        assert inputs.participant == "001"
        assert inputs.recon_spec == recon_spec


class TestSchemaBuilderRegistry:
    """Test schema builder registry and factory."""

    def test_get_schema_builder_returns_correct_builder(self):
        """Test that factory returns correct builder for each runner."""
        heudiconv_builder = get_schema_builder("voxelops.runners.heudiconv.run_heudiconv")
        assert isinstance(heudiconv_builder, HeudiconvSchemaBuilder)

        qsiprep_builder = get_schema_builder("voxelops.runners.qsiprep.run_qsiprep")
        assert isinstance(qsiprep_builder, QSIPrepSchemaBuilder)

        qsirecon_builder = get_schema_builder("voxelops.runners.qsirecon.run_qsirecon")
        assert isinstance(qsirecon_builder, QSIReconSchemaBuilder)

        qsiparc_builder = get_schema_builder("voxelops.runners.qsiparc.run_qsiparc")
        assert isinstance(qsiparc_builder, QSIParcSchemaBuilder)

    def test_get_schema_builder_raises_for_unknown_runner(self):
        """Test that factory raises ValueError for unknown runner."""
        with pytest.raises(ValueError, match="No schema builder found"):
            get_schema_builder("unknown.runner")


class TestResultParsing:
    """Test VoxelOps result parsing."""

    def test_parse_skipped_result(self):
        """Test parsing a skipped result."""
        result = {
            "skipped": True,
            "reason": "outputs already exist",
            "output_dir": "/data/output",
        }

        parsed = parse_voxelops_result(result)

        assert isinstance(parsed, PipelineResult)
        assert parsed.success is True
        assert parsed.exit_code == 0
        assert parsed.output_path == Path("/data/output")
        assert parsed.metrics["skipped"] is True
        assert parsed.metrics["reason"] == "outputs already exist"

    def test_parse_successful_result(self):
        """Test parsing a successful result."""
        result = {
            "success": True,
            "exit_code": 0,
            "output_path": "/data/output",
            "duration_seconds": 120.5,
            "tool": "heudiconv",
            "participant": "001",
            "start_time": "2024-01-01T10:00:00",
            "end_time": "2024-01-01T10:02:00",
            "stdout": "Processing complete",
        }

        parsed = parse_voxelops_result(result)

        assert isinstance(parsed, PipelineResult)
        assert parsed.success is True
        assert parsed.exit_code == 0
        assert parsed.output_path == Path("/data/output")
        assert parsed.duration_seconds == 120.5
        assert parsed.metrics["tool"] == "heudiconv"
        assert parsed.metrics["participant"] == "001"
        assert parsed.logs == "Processing complete"

    def test_parse_failed_result(self):
        """Test parsing a failed result."""
        result = {
            "success": False,
            "exit_code": 1,
            "error": "Processing failed",
            "stderr": "Error details here",
            "output_dir": "/data/output",
        }

        parsed = parse_voxelops_result(result)

        assert isinstance(parsed, PipelineResult)
        assert parsed.success is False
        assert parsed.exit_code == 1
        assert parsed.output_path == Path("/data/output")
        assert "Processing failed" in parsed.error_message
        assert "stderr: Error details here" in parsed.error_message

    def test_parse_result_with_missing_fields(self):
        """Test parsing result with minimal fields."""
        result = {}

        parsed = parse_voxelops_result(result)

        assert isinstance(parsed, PipelineResult)
        assert parsed.success is False
        assert parsed.exit_code == -1
        assert parsed.output_path is None
        assert parsed.error_message is None


class TestHeudiconvDefaults:
    """Test HeudiConv defaults builder."""

    @requires_voxelops
    def test_build_defaults_with_all_options(
        self, mock_config, tmp_path
    ):
        """Test build_defaults with all voxelops_config options."""
        from voxelops.schemas.heudiconv import HeudiconvDefaults

        heuristic_file = tmp_path / "test_heuristic.py"
        heuristic_file.write_text("# test heuristic")

        pipeline_config = PipelineConfig(
            name="bids_conversion",
            runner="voxelops.runners.heudiconv.run_heudiconv",
            voxelops_config={
                "heuristic": str(heuristic_file),
                "bids_validator": False,
                "overwrite": True,
                "converter": "dcm2niix",
                "docker_image": "nipy/heudiconv:1.4.0",
                "post_process": False,
            },
        )
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        builder = HeudiconvSchemaBuilder()
        defaults = builder.build_defaults(ctx)

        assert isinstance(defaults, HeudiconvDefaults)
        assert defaults.heuristic == heuristic_file
        assert defaults.bids_validator is False
        assert defaults.overwrite is True
        assert defaults.converter == "dcm2niix"
        assert defaults.docker_image == "nipy/heudiconv:1.4.0"
        assert defaults.post_process is False

    @requires_voxelops
    def test_build_defaults_with_minimal_config(
        self, mock_config, tmp_path
    ):
        """Test build_defaults uses default values."""
        from voxelops.schemas.heudiconv import HeudiconvDefaults

        heuristic_file = tmp_path / "test_heuristic.py"
        heuristic_file.write_text("# test heuristic")

        pipeline_config = PipelineConfig(
            name="bids_conversion",
            runner="voxelops.runners.heudiconv.run_heudiconv",
            voxelops_config={"heuristic": str(heuristic_file)},
        )
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        builder = HeudiconvSchemaBuilder()
        defaults = builder.build_defaults(ctx)

        assert isinstance(defaults, HeudiconvDefaults)
        assert defaults.bids_validator is True
        assert defaults.overwrite is False
        assert defaults.converter == "dcm2niix"
        assert defaults.docker_image == "nipy/heudiconv:1.3.4"


class TestQSIPrepDefaults:
    """Test QSIPrep defaults builder."""

    @requires_voxelops
    def test_build_defaults_with_all_options(
        self, mock_config, tmp_path
    ):
        """Test build_defaults with all voxelops_config options."""
        from voxelops.schemas.qsiprep import QSIPrepDefaults

        fs_license = tmp_path / "license.txt"
        fs_license.write_text("license content")

        pipeline_config = PipelineConfig(
            name="qsiprep",
            runner="voxelops.runners.qsiprep.run_qsiprep",
            voxelops_config={
                "nprocs": 16,
                "mem_mb": 32000,
                "output_resolution": 2.0,
                "anatomical_template": ["MNI152NLin6Asym"],
                "fs_license": str(fs_license),
                "docker_image": "pennlinc/qsiprep:0.20.0",
                "force": True,
            },
        )
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        builder = QSIPrepSchemaBuilder()
        defaults = builder.build_defaults(ctx)

        assert isinstance(defaults, QSIPrepDefaults)
        assert defaults.nprocs == 16
        assert defaults.mem_mb == 32000
        assert defaults.output_resolution == 2.0
        assert defaults.anatomical_template == ["MNI152NLin6Asym"]
        assert defaults.fs_license == fs_license
        assert defaults.docker_image == "pennlinc/qsiprep:0.20.0"
        assert defaults.force is True

    @requires_voxelops
    def test_build_defaults_uses_default_values(
        self, mock_config
    ):
        """Test build_defaults uses default values when not specified."""
        from voxelops.schemas.qsiprep import QSIPrepDefaults

        pipeline_config = PipelineConfig(
            name="qsiprep",
            runner="voxelops.runners.qsiprep.run_qsiprep",
            voxelops_config={},
        )
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        builder = QSIPrepSchemaBuilder()
        defaults = builder.build_defaults(ctx)

        assert isinstance(defaults, QSIPrepDefaults)
        assert defaults.nprocs == 8
        assert defaults.mem_mb == 16000
        assert defaults.output_resolution == 1.6
        assert defaults.anatomical_template == ["MNI152NLin2009cAsym"]
        assert defaults.force is False


class TestQSIReconDefaults:
    """Test QSIRecon defaults builder."""

    @requires_voxelops
    def test_build_defaults_with_all_options(
        self, mock_config, tmp_path
    ):
        """Test build_defaults with all voxelops_config options."""
        from voxelops.schemas.qsirecon import QSIReconDefaults

        fs_license = tmp_path / "license.txt"
        fs_license.write_text("license content")

        pipeline_config = PipelineConfig(
            name="qsirecon",
            runner="voxelops.runners.qsirecon.run_qsirecon",
            voxelops_config={
                "nprocs": 16,
                "mem_mb": 32000,
                "fs_license": str(fs_license),
                "docker_image": "pennlinc/qsirecon:0.20.0",
                "force": True,
            },
        )
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        builder = QSIReconSchemaBuilder()
        defaults = builder.build_defaults(ctx)

        assert isinstance(defaults, QSIReconDefaults)
        assert defaults.nprocs == 16
        assert defaults.mem_mb == 32000
        assert defaults.fs_license == fs_license
        assert defaults.docker_image == "pennlinc/qsirecon:0.20.0"
        assert defaults.force is True


class TestQSIParcDefaults:
    """Test QSIParc defaults builder."""

    @requires_voxelops
    def test_build_defaults_with_all_options(
        self, mock_config
    ):
        """Test build_defaults with all voxelops_config options."""
        from voxelops.schemas.qsiparc import QSIParcDefaults

        pipeline_config = PipelineConfig(
            name="qsiparc",
            runner="voxelops.runners.qsiparc.run_qsiparc",
            voxelops_config={
                "mask": "wm",
                "force": True,
                "n_jobs": 4,
                "n_procs": 2,
            },
        )
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        builder = QSIParcSchemaBuilder()
        defaults = builder.build_defaults(ctx)

        assert isinstance(defaults, QSIParcDefaults)
        assert defaults.mask == "wm"
        assert defaults.force is True
        assert defaults.n_jobs == 4
        assert defaults.n_procs == 2

    @requires_voxelops
    def test_build_inputs_creates_valid_schema(
        self, mock_config
    ):
        """Test that build_inputs creates valid QSIParcInputs."""
        from voxelops.schemas.qsiparc import QSIParcInputs

        pipeline_config = PipelineConfig(
            name="qsiparc",
            runner="voxelops.runners.qsiparc.run_qsiparc",
            voxelops_config={},
        )
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        builder = QSIParcSchemaBuilder()
        inputs = builder.build_inputs(ctx)

        assert isinstance(inputs, QSIParcInputs)
        assert inputs.participant == "001"
        assert inputs.qsirecon_dir == mock_config.paths.derivatives / "qsirecon"
        assert inputs.output_dir == mock_config.paths.derivatives / "qsiparc"


class TestHelperFunctions:
    """Test helper functions for result parsing."""

    def test_extract_output_path_from_output_dir(self):
        """Test _extract_output_path with output_dir."""
        from neuroflow.adapters.voxelops_schemas import _extract_output_path

        result = {"output_dir": "/data/output"}
        path = _extract_output_path(result)

        assert path == Path("/data/output")

    def test_extract_output_path_from_output_path(self):
        """Test _extract_output_path with output_path."""
        from neuroflow.adapters.voxelops_schemas import _extract_output_path

        result = {"output_path": "/data/output"}
        path = _extract_output_path(result)

        assert path == Path("/data/output")

    def test_extract_output_path_returns_none(self):
        """Test _extract_output_path returns None when no path."""
        from neuroflow.adapters.voxelops_schemas import _extract_output_path

        result = {}
        path = _extract_output_path(result)

        assert path is None

    def test_build_error_message_with_success(self):
        """Test _build_error_message returns None for success."""
        from neuroflow.adapters.voxelops_schemas import _build_error_message

        result = {"success": True}
        message = _build_error_message(result)

        assert message is None

    def test_build_error_message_with_error(self):
        """Test _build_error_message with error field."""
        from neuroflow.adapters.voxelops_schemas import _build_error_message

        result = {"success": False, "error": "Processing failed"}
        message = _build_error_message(result)

        assert message == "Processing failed"

    def test_build_error_message_with_stderr(self):
        """Test _build_error_message with stderr field."""
        from neuroflow.adapters.voxelops_schemas import _build_error_message

        result = {"success": False, "stderr": "Error details"}
        message = _build_error_message(result)

        assert message == "stderr: Error details"

    def test_build_error_message_with_both(self):
        """Test _build_error_message with error and stderr."""
        from neuroflow.adapters.voxelops_schemas import _build_error_message

        result = {"success": False, "error": "Failed", "stderr": "Details"}
        message = _build_error_message(result)

        assert "Failed" in message
        assert "stderr: Details" in message

    def test_build_error_message_returns_none_when_empty(self):
        """Test _build_error_message returns None when no error info."""
        from neuroflow.adapters.voxelops_schemas import _build_error_message

        result = {"success": False}
        message = _build_error_message(result)

        assert message is None


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_session_id_without_prefix(self, mock_config, heudiconv_pipeline_config):
        """Test session_id when already without 'ses-' prefix."""
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=heudiconv_pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        assert ctx.session_id == "baseline"

    def test_voxelops_config_property(self, mock_config, heudiconv_pipeline_config):
        """Test voxelops_config property shortcut."""
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=heudiconv_pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        assert ctx.voxelops_config == heudiconv_pipeline_config.voxelops_config

    def test_qsirecon_validation_succeeds_without_recon_spec(
        self, mock_config
    ):
        """Test QSIRecon validation succeeds when recon_spec not provided."""
        pipeline_config = PipelineConfig(
            name="qsirecon",
            runner="voxelops.runners.qsirecon.run_qsirecon",
            voxelops_config={},
        )
        ctx = BuilderContext(
            config=mock_config,
            pipeline_config=pipeline_config,
            participant_id="001",
            session_id="baseline",
            dicom_path=Path("/data/dicom/sub-001/ses-baseline"),
        )

        builder = QSIReconSchemaBuilder()
        builder.validate_config(ctx)  # Should not raise

    def test_result_with_only_output_dir(self):
        """Test parsing result with only output_dir."""
        result = {
            "success": True,
            "exit_code": 0,
            "output_dir": "/data/output",
        }

        parsed = parse_voxelops_result(result)

        assert parsed.success is True
        assert parsed.output_path == Path("/data/output")

    def test_result_with_partial_metrics(self):
        """Test parsing result with partial metrics."""
        result = {
            "success": True,
            "exit_code": 0,
            "tool": "qsiprep",
            "start_time": "2024-01-01T10:00:00",
        }

        parsed = parse_voxelops_result(result)

        assert parsed.metrics["tool"] == "qsiprep"
        assert parsed.metrics["start_time"] == "2024-01-01T10:00:00"
        assert parsed.metrics["participant"] is None
        assert parsed.metrics["end_time"] is None
