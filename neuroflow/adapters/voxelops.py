"""Adapter for calling voxelops pipeline runners."""

import importlib
import subprocess
import time
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
    """Adapter for calling voxelops procedures."""

    def __init__(self, config: NeuroflowConfig):
        self.config = config

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

        try:
            return self._run_via_import(
                pipeline_config, session_id, subject_id, **kwargs
            )
        except (ImportError, ModuleNotFoundError):
            log.info(
                "adapter.fallback_to_container",
                pipeline=pipeline_name,
                runner=pipeline_config.runner,
            )
            return self._run_via_container(
                pipeline_config, session_id, subject_id, **kwargs
            )

    def _run_via_import(
        self,
        pipeline_config: PipelineConfig,
        session_id: int | None,
        subject_id: int | None,
        **kwargs: Any,
    ) -> PipelineResult:
        """Run pipeline via direct Python import."""
        start_time = time.time()

        module_path, _, func_name = pipeline_config.runner.rpartition(".")
        if not func_name:
            # Runner is a module, use .run() convention
            module_path = pipeline_config.runner
            func_name = "run"

        module = importlib.import_module(module_path)
        runner_func = getattr(module, func_name)

        # Build arguments based on what the runner expects
        run_kwargs: dict[str, Any] = {}
        if session_id is not None:
            run_kwargs["session_id"] = session_id
        if subject_id is not None:
            run_kwargs["subject_id"] = subject_id
        run_kwargs.update(kwargs)

        result = runner_func(**run_kwargs)

        duration = time.time() - start_time

        # Normalize result
        if isinstance(result, dict):
            return PipelineResult(
                success=result.get("success", True),
                exit_code=result.get("exit_code", 0),
                output_path=Path(result["output_path"])
                if result.get("output_path")
                else None,
                error_message=result.get("error_message"),
                duration_seconds=duration,
                metrics=result.get("metrics"),
            )
        else:
            return PipelineResult(
                success=True,
                exit_code=0,
                duration_seconds=duration,
            )

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
        """Build the container execution command."""
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
        for p in self.config.pipelines.session_level:
            if p.name == pipeline_name:
                return p
        for p in self.config.pipelines.subject_level:
            if p.name == pipeline_name:
                return p
        return None
