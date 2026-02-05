"""Schema mapping layer for VoxelOps integration.

This module provides a mapping between neuroflow's configuration/models
and VoxelOps' schema-based runners (HeudiConv, QSIPrep, QSIRecon, QSIParc).
"""

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from neuroflow.adapters.voxelops import PipelineResult
from neuroflow.config import NeuroflowConfig, PipelineConfig

log = structlog.get_logger("voxelops.schemas")


class SchemaValidationError(Exception):
    """Raised when VoxelOps configuration is invalid."""

    pass


@dataclass
class BuilderContext:
    """Context for building VoxelOps schemas.

    Encapsulates all the information needed to construct VoxelOps Input
    and Defaults schemas from neuroflow configuration.

    Note: This holds plain data (strings, Paths), not SQLAlchemy ORM objects,
    to avoid DetachedInstanceError when used outside database session context.
    """

    config: NeuroflowConfig
    pipeline_config: PipelineConfig
    # Plain data fields instead of ORM objects
    participant_id: str | None = None  # Without 'sub-' prefix
    session_id: str | None = None  # Without 'ses-' prefix
    dicom_path: Path | None = None

    @property
    def voxelops_config(self) -> dict:
        """Shortcut to pipeline's voxelops_config."""
        return self.pipeline_config.voxelops_config


class SchemaBuilder(ABC):
    """Abstract base class for VoxelOps schema builders.

    Each VoxelOps runner (HeudiConv, QSIPrep, etc.) has its own concrete
    builder that knows how to construct the appropriate Input and Defaults
    schemas from neuroflow context.
    """

    @abstractmethod
    def build_inputs(self, ctx: BuilderContext) -> Any:
        """Build VoxelOps Inputs schema from context.

        Args:
            ctx: BuilderContext containing config and database models

        Returns:
            VoxelOps Inputs schema instance (e.g., HeudiconvInputs)
        """
        pass

    @abstractmethod
    def build_defaults(self, ctx: BuilderContext) -> Any:
        """Build VoxelOps Defaults schema from context.

        Args:
            ctx: BuilderContext containing config and database models

        Returns:
            VoxelOps Defaults schema instance (e.g., HeudiconvDefaults)
        """
        pass

    def validate_config(self, ctx: BuilderContext) -> None:
        """Validate that required configuration is present.

        Override in subclasses to add runner-specific validation.

        Args:
            ctx: BuilderContext containing config

        Raises:
            SchemaValidationError: If required configuration is missing
        """
        pass


class HeudiconvSchemaBuilder(SchemaBuilder):
    """Schema builder for HeudiConv (BIDS conversion)."""

    def validate_config(self, ctx: BuilderContext) -> None:
        """Validate HeudiConv configuration."""
        vox_cfg = ctx.voxelops_config

        # Check for heuristic file
        if not vox_cfg.get("heuristic"):
            raise SchemaValidationError(
                "HeudiConv requires 'heuristic' in voxelops_config"
            )

        heuristic_path = Path(vox_cfg["heuristic"])
        if not heuristic_path.exists():
            raise SchemaValidationError(
                f"Heuristic file not found: {heuristic_path}"
            )

    def build_inputs(self, ctx: BuilderContext) -> Any:
        """Build HeudiconvInputs schema."""
        from voxelops.schemas.heudiconv import HeudiconvInputs

        if not ctx.dicom_path:
            raise ValueError("DICOM path is required for HeudiConv")

        # Get heuristic from config or BidsConversionConfig
        heuristic = None
        if ctx.voxelops_config.get("heuristic"):
            heuristic = Path(ctx.voxelops_config["heuristic"])
        elif hasattr(ctx.config.pipelines.bids_conversion, "heuristic_file"):
            bids_cfg = ctx.config.pipelines.bids_conversion
            if bids_cfg.heuristic_file:
                heuristic = Path(bids_cfg.heuristic_file)

        return HeudiconvInputs(
            dicom_dir=ctx.dicom_path,
            participant=ctx.participant_id,
            session=ctx.session_id,
            output_dir=ctx.config.paths.bids_root,
            heuristic=heuristic,
        )

    def build_defaults(self, ctx: BuilderContext) -> Any:
        """Build HeudiconvDefaults schema."""
        from voxelops.schemas.heudiconv import HeudiconvDefaults

        vox_cfg = ctx.voxelops_config

        return HeudiconvDefaults(
            heuristic=Path(vox_cfg["heuristic"]) if vox_cfg.get("heuristic") else None,
            bids_validator=vox_cfg.get("bids_validator", True),
            overwrite=vox_cfg.get("overwrite", False),
            converter=vox_cfg.get("converter", "dcm2niix"),
            docker_image=vox_cfg.get("docker_image", "nipy/heudiconv:1.3.4"),
            post_process=vox_cfg.get("post_process", True),
        )


class QSIPrepSchemaBuilder(SchemaBuilder):
    """Schema builder for QSIPrep (diffusion preprocessing)."""

    def build_inputs(self, ctx: BuilderContext) -> Any:
        """Build QSIPrepInputs schema."""
        from voxelops.schemas.qsiprep import QSIPrepInputs

        if not ctx.participant_id:
            raise ValueError("Participant ID is required for QSIPrep")

        return QSIPrepInputs(
            bids_dir=ctx.config.paths.bids_root,
            output_dir=ctx.config.paths.derivatives / "qsiprep",
            participant=ctx.participant_id,
        )

    def build_defaults(self, ctx: BuilderContext) -> Any:
        """Build QSIPrepDefaults schema."""
        from voxelops.schemas.qsiprep import QSIPrepDefaults

        vox_cfg = ctx.voxelops_config

        return QSIPrepDefaults(
            nprocs=vox_cfg.get("nprocs", 8),
            mem_mb=vox_cfg.get("mem_mb", 16000),
            output_resolution=vox_cfg.get("output_resolution", 1.6),
            anatomical_template=vox_cfg.get("anatomical_template", ["MNI152NLin2009cAsym"]),
            fs_license=Path(vox_cfg["fs_license"]) if vox_cfg.get("fs_license") else None,
            docker_image=vox_cfg.get("docker_image", "pennlinc/qsiprep:latest"),
            force=vox_cfg.get("force", False),
        )


class QSIReconSchemaBuilder(SchemaBuilder):
    """Schema builder for QSIRecon (diffusion reconstruction)."""

    def validate_config(self, ctx: BuilderContext) -> None:
        """Validate QSIRecon configuration."""
        vox_cfg = ctx.voxelops_config

        # Check recon_spec if provided
        if vox_cfg.get("recon_spec"):
            recon_spec_path = Path(vox_cfg["recon_spec"])
            if not recon_spec_path.exists():
                raise SchemaValidationError(
                    f"Recon spec file not found: {recon_spec_path}"
                )

    def build_inputs(self, ctx: BuilderContext) -> Any:
        """Build QSIReconInputs schema."""
        from voxelops.schemas.qsirecon import QSIReconInputs

        if not ctx.participant_id:
            raise ValueError("Participant ID is required for QSIRecon")

        recon_spec = None
        if ctx.voxelops_config.get("recon_spec"):
            recon_spec = Path(ctx.voxelops_config["recon_spec"])

        atlases = ctx.voxelops_config.get("atlases", ["Brainnetome246Ext", "AAL116"])

        return QSIReconInputs(
            qsiprep_dir=ctx.config.paths.derivatives / "qsiprep",
            output_dir=ctx.config.paths.derivatives / "qsirecon",
            participant=ctx.participant_id,
            recon_spec=recon_spec,
            atlases=atlases,
        )

    def build_defaults(self, ctx: BuilderContext) -> Any:
        """Build QSIReconDefaults schema."""
        from voxelops.schemas.qsirecon import QSIReconDefaults

        vox_cfg = ctx.voxelops_config

        return QSIReconDefaults(
            nprocs=vox_cfg.get("nprocs", 8),
            mem_mb=vox_cfg.get("mem_mb", 16000),
            fs_license=Path(vox_cfg["fs_license"]) if vox_cfg.get("fs_license") else None,
            docker_image=vox_cfg.get("docker_image", "pennlinc/qsirecon:latest"),
            force=vox_cfg.get("force", False),
        )


class QSIParcSchemaBuilder(SchemaBuilder):
    """Schema builder for QSIParc (parcellation)."""

    def build_inputs(self, ctx: BuilderContext) -> Any:
        """Build QSIParcInputs schema."""
        from voxelops.schemas.qsiparc import QSIParcInputs

        if not ctx.participant_id:
            raise ValueError("Participant ID is required for QSIParc")

        return QSIParcInputs(
            qsirecon_dir=ctx.config.paths.derivatives / "qsirecon",
            output_dir=ctx.config.paths.derivatives / "qsiparc",
            participant=ctx.participant_id,
        )

    def build_defaults(self, ctx: BuilderContext) -> Any:
        """Build QSIParcDefaults schema."""
        from voxelops.schemas.qsiparc import QSIParcDefaults

        vox_cfg = ctx.voxelops_config

        return QSIParcDefaults(
            mask=vox_cfg.get("mask", "gm"),
            force=vox_cfg.get("force", False),
            n_jobs=vox_cfg.get("n_jobs", 1),
            n_procs=vox_cfg.get("n_procs", 1),
        )


# Registry mapping runner names to builder classes
SCHEMA_BUILDERS: dict[str, type[SchemaBuilder]] = {
    "voxelops.runners.heudiconv.run_heudiconv": HeudiconvSchemaBuilder,
    "voxelops.runners.qsiprep.run_qsiprep": QSIPrepSchemaBuilder,
    "voxelops.runners.qsirecon.run_qsirecon": QSIReconSchemaBuilder,
    "voxelops.runners.qsiparc.run_qsiparc": QSIParcSchemaBuilder,
}


def get_schema_builder(runner_name: str) -> SchemaBuilder:
    """Factory function to get appropriate schema builder for a runner.

    Args:
        runner_name: Full module path to runner function (e.g., 'voxelops.runners.heudiconv.run_heudiconv')

    Returns:
        SchemaBuilder instance for the runner

    Raises:
        ValueError: If runner is not supported
    """
    builder_class = SCHEMA_BUILDERS.get(runner_name)
    if not builder_class:
        raise ValueError(
            f"No schema builder found for runner: {runner_name}. "
            f"Supported runners: {list(SCHEMA_BUILDERS.keys())}"
        )

    return builder_class()


def parse_voxelops_result(result: dict[str, Any]) -> PipelineResult:
    """Convert VoxelOps result dict to neuroflow PipelineResult.

    VoxelOps runners return structured result dicts with metadata about
    execution. This function normalizes them to neuroflow's PipelineResult.

    Args:
        result: Dict returned by VoxelOps runner

    Returns:
        PipelineResult with normalized fields
    """
    # Handle skipped runs (outputs exist, force=False)
    if result.get("skipped"):
        return PipelineResult(
            success=True,
            exit_code=0,
            output_path=_extract_output_path(result),
            metrics={"skipped": True, "reason": result.get("reason")},
        )

    # Parse execution result
    return PipelineResult(
        success=result.get("success", False),
        exit_code=result.get("exit_code", -1),
        output_path=_extract_output_path(result),
        error_message=_build_error_message(result),
        duration_seconds=result.get("duration_seconds"),
        metrics={
            "tool": result.get("tool"),
            "participant": result.get("participant"),
            "start_time": result.get("start_time"),
            "end_time": result.get("end_time"),
        },
        logs=result.get("stdout"),
    )


def _extract_output_path(result: dict[str, Any]) -> Path | None:
    """Extract output path from VoxelOps result."""
    if "output_dir" in result:
        return Path(result["output_dir"])
    if "output_path" in result:
        return Path(result["output_path"])
    return None


def _build_error_message(result: dict[str, Any]) -> str | None:
    """Build error message from VoxelOps result."""
    if result.get("success", False):
        return None

    parts = []
    if result.get("error"):
        parts.append(str(result["error"]))
    if result.get("stderr"):
        parts.append(f"stderr: {result['stderr']}")

    return "\n".join(parts) if parts else None
