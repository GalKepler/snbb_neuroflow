"""Schema mapping layer for VoxelOps integration.

This module provides a mapping between neuroflow's configuration/models
and VoxelOps' schema-based runners (HeudiConv, QSIPrep, QSIRecon, QSIParc).

Schema builders set "structural" fields (paths, participant) from neuroflow
config, then pass through ALL other voxelops_config keys that the schema
class accepts. This means neuroflow doesn't need updating when voxelops
adds new schema fields.
"""

import dataclasses
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
    """

    config: NeuroflowConfig
    pipeline_config: PipelineConfig
    participant_id: str | None = None  # Without 'sub-' prefix
    session_id: str | None = None  # Without 'ses-' prefix
    dicom_path: Path | None = None

    @property
    def voxelops_config(self) -> dict:
        """Shortcut to pipeline's voxelops_config."""
        return self.pipeline_config.voxelops_config


def _build_dataclass(cls: type, explicit: dict[str, Any], vox_cfg: dict[str, Any]) -> Any:
    """Build a dataclass instance, merging explicit fields with voxelops_config.

    Explicit fields take precedence. Only keys that match actual dataclass
    fields are passed — unknown keys are logged and skipped.
    """
    accepted = {f.name for f in dataclasses.fields(cls)}

    # Start with voxelops_config values that match schema fields
    kwargs = {k: v for k, v in vox_cfg.items() if k in accepted}

    # Explicit fields override voxelops_config
    kwargs.update({k: v for k, v in explicit.items() if v is not None})

    # Warn about unrecognized keys
    unknown = set(vox_cfg.keys()) - accepted
    if unknown:
        log.debug("schema.unused_config_keys", cls=cls.__name__, keys=sorted(unknown))

    return cls(**kwargs)


class SchemaBuilder(ABC):
    """Abstract base class for VoxelOps schema builders."""

    @abstractmethod
    def build_inputs(self, ctx: BuilderContext) -> Any:
        """Build VoxelOps Inputs schema from context."""
        pass

    @abstractmethod
    def build_defaults(self, ctx: BuilderContext) -> Any:
        """Build VoxelOps Defaults schema from context."""
        pass

    def validate_config(self, ctx: BuilderContext) -> None:
        """Validate that required configuration is present.

        Override in subclasses to add runner-specific validation.
        """
        pass


class HeudiconvSchemaBuilder(SchemaBuilder):
    """Schema builder for HeudiConv (BIDS conversion)."""

    def validate_config(self, ctx: BuilderContext) -> None:
        """Validate HeudiConv configuration."""
        vox_cfg = ctx.voxelops_config

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

        heuristic = None
        if ctx.voxelops_config.get("heuristic"):
            heuristic = Path(ctx.voxelops_config["heuristic"])
        elif hasattr(ctx.config.pipelines.bids_conversion, "heuristic_file"):
            bids_cfg = ctx.config.pipelines.bids_conversion
            if bids_cfg.heuristic_file:
                heuristic = Path(bids_cfg.heuristic_file)

        return _build_dataclass(
            HeudiconvInputs,
            explicit={
                "dicom_dir": ctx.dicom_path,
                "participant": ctx.participant_id,
                "session": ctx.session_id,
                "output_dir": ctx.config.paths.bids_root,
                "heuristic": heuristic,
            },
            vox_cfg=ctx.voxelops_config,
        )

    def build_defaults(self, ctx: BuilderContext) -> Any:
        """Build HeudiconvDefaults schema."""
        from voxelops.schemas.heudiconv import HeudiconvDefaults

        return _build_dataclass(HeudiconvDefaults, explicit={}, vox_cfg=ctx.voxelops_config)


class QSIPrepSchemaBuilder(SchemaBuilder):
    """Schema builder for QSIPrep (diffusion preprocessing)."""

    def build_inputs(self, ctx: BuilderContext) -> Any:
        """Build QSIPrepInputs schema."""
        from voxelops.schemas.qsiprep import QSIPrepInputs

        if not ctx.participant_id:
            raise ValueError("Participant ID is required for QSIPrep")

        return _build_dataclass(
            QSIPrepInputs,
            explicit={
                "bids_dir": ctx.config.paths.bids_root,
                "output_dir": ctx.config.paths.derivatives / "qsiprep",
                "participant": ctx.participant_id,
                "work_dir": ctx.config.paths.work_dir / "qsiprep",
            },
            vox_cfg=ctx.voxelops_config,
        )

    def build_defaults(self, ctx: BuilderContext) -> Any:
        """Build QSIPrepDefaults schema."""
        from voxelops.schemas.qsiprep import QSIPrepDefaults

        return _build_dataclass(QSIPrepDefaults, explicit={}, vox_cfg=ctx.voxelops_config)


class QSIReconSchemaBuilder(SchemaBuilder):
    """Schema builder for QSIRecon (diffusion reconstruction)."""

    def validate_config(self, ctx: BuilderContext) -> None:
        """Validate QSIRecon configuration."""
        vox_cfg = ctx.voxelops_config

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

        return _build_dataclass(
            QSIReconInputs,
            explicit={
                "qsiprep_dir": ctx.config.paths.derivatives / "qsiprep",
                "output_dir": ctx.config.paths.derivatives / "qsirecon",
                "participant": ctx.participant_id,
                "work_dir": ctx.config.paths.work_dir / "qsirecon",
            },
            vox_cfg=ctx.voxelops_config,
        )

    def build_defaults(self, ctx: BuilderContext) -> Any:
        """Build QSIReconDefaults schema."""
        from voxelops.schemas.qsirecon import QSIReconDefaults

        return _build_dataclass(QSIReconDefaults, explicit={}, vox_cfg=ctx.voxelops_config)


class QSIParcSchemaBuilder(SchemaBuilder):
    """Schema builder for QSIParc (parcellation)."""

    def build_inputs(self, ctx: BuilderContext) -> Any:
        """Build QSIParcInputs schema."""
        from voxelops.schemas.qsiparc import QSIParcInputs

        if not ctx.participant_id:
            raise ValueError("Participant ID is required for QSIParc")

        return _build_dataclass(
            QSIParcInputs,
            explicit={
                "qsirecon_dir": ctx.config.paths.derivatives / "qsirecon",
                "output_dir": ctx.config.paths.derivatives / "qsiparc",
                "participant": ctx.participant_id,
                "session": ctx.session_id,
            },
            vox_cfg=ctx.voxelops_config,
        )

    def build_defaults(self, ctx: BuilderContext) -> Any:
        """Build QSIParcDefaults schema."""
        from voxelops.schemas.qsiparc import QSIParcDefaults

        return _build_dataclass(QSIParcDefaults, explicit={}, vox_cfg=ctx.voxelops_config)


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
        runner_name: Full module path to runner function

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
