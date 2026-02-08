"""Adapter for calling voxelops pipeline runners."""

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from neuroflow.config import NeuroflowConfig, PipelineConfig

log = structlog.get_logger("voxelops")


@dataclass
class PipelineResult:
    """Result of a pipeline execution."""

    success: bool
    exit_code: int
    output_path: Path | None = None
    error_message: str | None = None
    duration_seconds: float | None = None
    metrics: dict | None = None
    logs: str | None = None


class VoxelopsAdapter:
    """Adapter that passes pipeline inputs to voxelops and collects results.

    Neuroflow does NOT execute containers — voxelops handles all of that.
    This adapter builds the input/config schemas and calls the voxelops runner.
    """

    def __init__(self, config: NeuroflowConfig):
        self.config = config
        self._voxelops_available = self._check_voxelops_available()

    def _check_voxelops_available(self) -> bool:
        """Check if VoxelOps is installed and importable."""
        try:
            importlib.import_module("voxelops")
            return True
        except (ImportError, ModuleNotFoundError):
            log.warning("voxelops.not_available")
            return False

    def run(
        self,
        pipeline_name: str,
        participant_id: str | None = None,
        session_id: str | None = None,
        dicom_path: Path | None = None,
        **kwargs: Any,
    ) -> PipelineResult:
        """Run a pipeline via voxelops.

        Args:
            pipeline_name: Name of the pipeline to run.
            participant_id: Participant identifier (with or without 'sub-' prefix).
            session_id: Session identifier (with or without 'ses-' prefix).
            dicom_path: Path to the DICOM directory.
            **kwargs: Additional arguments passed to the runner.
        """
        pipeline_config = self._get_pipeline_config(pipeline_name)
        if not pipeline_config:
            return PipelineResult(
                success=False,
                exit_code=-1,
                error_message=f"Unknown pipeline: {pipeline_name}",
            )

        if not self._voxelops_available:
            return PipelineResult(
                success=False,
                exit_code=-1,
                error_message=(
                    "voxelops is not installed. "
                    "Install it with: pip install voxelops"
                ),
            )

        resolved_runner = self._resolve_runner(pipeline_config.runner)
        if not resolved_runner:
            return PipelineResult(
                success=False,
                exit_code=-1,
                error_message=(
                    f"Runner '{pipeline_config.runner}' not recognized. "
                    f"Check the 'runner' field in your pipeline config."
                ),
            )

        log.info(
            "adapter.run",
            pipeline=pipeline_name,
            runner=resolved_runner,
            participant_id=participant_id,
            session_id=session_id,
        )

        # Use the resolved full runner name
        resolved_config = PipelineConfig(**{
            **pipeline_config.model_dump(),
            "runner": resolved_runner,
        })
        return self._run_via_voxelops(
            resolved_config, participant_id, session_id, dicom_path, **kwargs
        )

    def _resolve_runner(self, runner: str) -> str | None:
        """Resolve a runner name to a full schema builder key.

        Handles both full names ('voxelops.runners.qsiprep.run_qsiprep')
        and short names ('voxelops.runners.qsiprep').
        """
        from neuroflow.adapters.voxelops_schemas import SCHEMA_BUILDERS

        if runner in SCHEMA_BUILDERS:
            return runner

        # Try appending run_{last_component} for short-form names
        # e.g. 'voxelops.runners.qsiprep' -> 'voxelops.runners.qsiprep.run_qsiprep'
        last = runner.rsplit(".", 1)[-1]
        full = f"{runner}.run_{last}"
        if full in SCHEMA_BUILDERS:
            return full

        return None

    def _run_via_voxelops(
        self,
        pipeline_config: PipelineConfig,
        participant_id: str | None,
        session_id: str | None,
        dicom_path: Path | None,
        **kwargs: Any,
    ) -> PipelineResult:
        """Build schemas, call voxelops runner, return result."""
        from neuroflow.adapters.voxelops_schemas import (
            BuilderContext,
            get_schema_builder,
            parse_voxelops_result,
        )

        # Strip prefixes if present
        clean_participant = participant_id
        if clean_participant and clean_participant.startswith("sub-"):
            clean_participant = clean_participant[4:]

        clean_session = session_id
        if clean_session and clean_session.startswith("ses-"):
            clean_session = clean_session[4:]

        # Build context directly from arguments
        ctx = BuilderContext(
            config=self.config,
            pipeline_config=pipeline_config,
            participant_id=clean_participant,
            session_id=clean_session,
            dicom_path=dicom_path,
        )

        # Get builder and validate config
        builder = get_schema_builder(pipeline_config.runner)
        builder.validate_config(ctx)

        # Build schemas
        inputs = builder.build_inputs(ctx)
        defaults = builder.build_defaults(ctx)

        # Apply kwargs overrides to defaults
        for key, value in kwargs.items():
            if hasattr(defaults, key):
                setattr(defaults, key, value)
                log.debug("adapter.override_default", key=key, value=value)

        # Import and call runner
        module_path, _, func_name = pipeline_config.runner.rpartition(".")
        module = importlib.import_module(module_path)
        runner_func = getattr(module, func_name)

        log.info(
            "adapter.calling_voxelops",
            runner=pipeline_config.runner,
            inputs=str(inputs),
        )

        # Call VoxelOps runner — it handles containers, execution, everything
        result = runner_func(inputs=inputs, config=defaults)

        # Parse and return
        pipeline_result = parse_voxelops_result(result)

        log.info(
            "adapter.complete",
            runner=pipeline_config.runner,
            success=pipeline_result.success,
            duration=pipeline_result.duration_seconds,
        )

        return pipeline_result

    def _get_pipeline_config(self, pipeline_name: str) -> PipelineConfig | None:
        """Get pipeline configuration by name."""
        if pipeline_name == "bids_conversion":
            bids_cfg = self.config.pipelines.bids_conversion
            if isinstance(bids_cfg, dict):
                return PipelineConfig(
                    name="bids_conversion",
                    enabled=bids_cfg.get("enabled", True),
                    runner="voxelops.runners.heudiconv.run_heudiconv",
                    timeout_minutes=bids_cfg.get("timeout_minutes", 60),
                    voxelops_config=bids_cfg.get("voxelops_config", {}),
                )
            else:
                return PipelineConfig(
                    name="bids_conversion",
                    enabled=bids_cfg.enabled,
                    runner="voxelops.runners.heudiconv.run_heudiconv",
                    timeout_minutes=bids_cfg.timeout_minutes,
                    voxelops_config=getattr(bids_cfg, "voxelops_config", {}),
                )

        for p in self.config.pipelines.session_level:
            if p.name == pipeline_name:
                return p
        for p in self.config.pipelines.subject_level:
            if p.name == pipeline_name:
                return p
        return None
