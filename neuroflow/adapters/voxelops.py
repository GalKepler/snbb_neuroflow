"""Adapter for calling voxelops pipeline runners."""

import importlib
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

import structlog

from neuroflow.config import NeuroflowConfig, PipelineConfig

if TYPE_CHECKING:
    from neuroflow.models.session import Session
    from neuroflow.models.subject import Subject

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
    """Adapter for calling voxelops procedures."""

    def __init__(self, config: NeuroflowConfig):
        self.config = config
        self._voxelops_available = self._check_voxelops_available()

    def _check_voxelops_available(self) -> bool:
        """Check if VoxelOps is installed and importable."""
        try:
            importlib.import_module("voxelops")
            return True
        except (ImportError, ModuleNotFoundError):
            log.warning("voxelops.not_available", message="VoxelOps not installed, will use container mode")
            return False

    def run(
        self,
        pipeline_name: str,
        session_id: int | None = None,
        subject_id: int | None = None,
        **kwargs: Any,
    ) -> PipelineResult:
        """Run a pipeline via voxelops.

        Tries direct import first, falls back to container execution.
        """
        pipeline_config = self._get_pipeline_config(pipeline_name)
        if not pipeline_config:
            return PipelineResult(
                success=False,
                exit_code=-1,
                error_message=f"Unknown pipeline: {pipeline_name}",
            )

        log.info(
            "adapter.run",
            pipeline=pipeline_name,
            session_id=session_id,
            subject_id=subject_id,
        )

        # Use VoxelOps schema mapping if available
        if self._voxelops_available and pipeline_config.runner in self._get_voxelops_runners():
            try:
                return self._run_via_voxelops(
                    pipeline_config, session_id, subject_id, **kwargs
                )
            except Exception as e:
                log.error(
                    "adapter.voxelops_failed",
                    pipeline=pipeline_name,
                    error=str(e),
                )
                # Fall back to container mode if VoxelOps fails
                if pipeline_config.container:
                    log.info("adapter.fallback_to_container", pipeline=pipeline_name)
                    return self._run_via_container(
                        pipeline_config, session_id, subject_id, **kwargs
                    )
                raise

        # Fall back to container mode
        if pipeline_config.container:
            return self._run_via_container(
                pipeline_config, session_id, subject_id, **kwargs
            )

        return PipelineResult(
            success=False,
            exit_code=-1,
            error_message=f"No execution method available for pipeline {pipeline_name}",
        )

    def _get_voxelops_runners(self) -> list[str]:
        """Get list of supported VoxelOps runner names."""
        from neuroflow.adapters.voxelops_schemas import SCHEMA_BUILDERS
        return list(SCHEMA_BUILDERS.keys())

    def _run_via_voxelops(
        self,
        pipeline_config: PipelineConfig,
        session_id: int | None,
        subject_id: int | None,
        **kwargs: Any,
    ) -> PipelineResult:
        """Run pipeline via VoxelOps with schema mapping."""
        from neuroflow.adapters.voxelops_schemas import (
            BuilderContext,
            get_schema_builder,
            parse_voxelops_result,
        )
        from neuroflow.core.state import StateManager
        from neuroflow.models.session import Session
        from neuroflow.models.subject import Subject

        # Fetch session/subject from database
        state = StateManager(self.config)
        with state.get_session() as db:
            session = db.get(Session, session_id) if session_id else None
            subject = db.get(Subject, subject_id) if subject_id else None
            if session and not subject:
                subject = session.subject

        # Build context
        ctx = BuilderContext(
            config=self.config,
            pipeline_config=pipeline_config,
            session=session,
            subject=subject,
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

        # Call VoxelOps runner
        result = runner_func(inputs=inputs, config=defaults)

        # Parse and return
        pipeline_result = parse_voxelops_result(result)

        log.info(
            "adapter.voxelops_complete",
            runner=pipeline_config.runner,
            success=pipeline_result.success,
            duration=pipeline_result.duration_seconds,
        )

        return pipeline_result

    def _run_via_container(
        self,
        pipeline_config: PipelineConfig,
        session_id: int | None,
        subject_id: int | None,
        **kwargs: Any,
    ) -> PipelineResult:
        """Run pipeline via container (apptainer/docker)."""
        if not pipeline_config.container:
            return PipelineResult(
                success=False,
                exit_code=-1,
                error_message=(
                    f"No container configured for pipeline {pipeline_config.name} "
                    f"and runner {pipeline_config.runner} not importable"
                ),
            )

        start_time = time.time()
        cmd = self._build_container_command(
            pipeline_config, session_id, subject_id, **kwargs
        )

        log.info("container.execute", cmd=" ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=pipeline_config.timeout_minutes * 60,
            )

            return PipelineResult(
                success=result.returncode == 0,
                exit_code=result.returncode,
                duration_seconds=time.time() - start_time,
                error_message=result.stderr if result.returncode != 0 else None,
                logs=result.stdout,
            )

        except subprocess.TimeoutExpired:
            return PipelineResult(
                success=False,
                exit_code=-1,
                duration_seconds=time.time() - start_time,
                error_message=f"Timeout after {pipeline_config.timeout_minutes} minutes",
            )

    def _build_container_command(
        self,
        pipeline_config: PipelineConfig,
        session_id: int | None,
        subject_id: int | None,
        **kwargs: Any,
    ) -> list[str]:
        """Build the container execution command.

        NOTE: This is a basic implementation for backward compatibility.
        VoxelOps handles container execution internally when using schema mapping.
        """
        runtime = self.config.container_runtime

        if runtime == "apptainer":
            cmd = ["apptainer", "run"]
        elif runtime == "docker":
            cmd = ["docker", "run", "--rm"]
        else:
            cmd = ["singularity", "run"]

        # Add container image
        cmd.append(pipeline_config.container or "")

        return cmd

    def _get_pipeline_config(self, pipeline_name: str) -> PipelineConfig | None:
        """Get pipeline configuration by name."""
        # Check if this is bids_conversion
        if pipeline_name == "bids_conversion":
            bids_cfg = self.config.pipelines.bids_conversion
            if isinstance(bids_cfg, dict):
                # Handle dict config (backward compatibility)
                return PipelineConfig(
                    name="bids_conversion",
                    enabled=bids_cfg.get("enabled", True),
                    runner="voxelops.runners.heudiconv.run_heudiconv",
                    timeout_minutes=bids_cfg.get("timeout_minutes", 60),
                    voxelops_config=bids_cfg.get("voxelops_config", {}),
                )
            else:
                # BidsConversionConfig object
                return PipelineConfig(
                    name="bids_conversion",
                    enabled=bids_cfg.enabled,
                    runner="voxelops.runners.heudiconv.run_heudiconv",
                    timeout_minutes=bids_cfg.timeout_minutes,
                    container=bids_cfg.container,
                    voxelops_config=getattr(bids_cfg, "voxelops_config", {}),
                )

        # Check session_level and subject_level pipelines
        for p in self.config.pipelines.session_level:
            if p.name == pipeline_name:
                return p
        for p in self.config.pipelines.subject_level:
            if p.name == pipeline_name:
                return p
        return None
