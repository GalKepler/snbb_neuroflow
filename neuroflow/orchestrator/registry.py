"""Pipeline Registry - Central registry of all pipelines with dependencies.

This module provides the pipeline registry system that defines:
- Available pipelines and their metadata
- Dependencies between pipelines
- Execution levels (session vs subject)
- Resource requirements
- Retry policies
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from neuroflow.config import NeuroflowConfig

log = structlog.get_logger("registry")


class PipelineLevel(str, Enum):
    """Level at which a pipeline operates."""
    SESSION = "session"
    SUBJECT = "subject"


class PipelineStage(IntEnum):
    """Processing stage for dependency ordering."""
    DISCOVERY = 0
    BIDS_CONVERSION = 1
    PREPROCESSING = 2
    RECONSTRUCTION = 3
    PARCELLATION = 4


@dataclass
class RetryPolicy:
    """Retry policy for a pipeline."""
    max_attempts: int = 3
    initial_delay_seconds: int = 300  # 5 minutes
    max_delay_seconds: int = 3600  # 1 hour
    exponential_backoff: bool = True

    def get_delay(self, attempt: int) -> int:
        """Calculate delay for a given attempt number."""
        if not self.exponential_backoff:
            return self.initial_delay_seconds

        delay = self.initial_delay_seconds * (2 ** (attempt - 1))
        return min(delay, self.max_delay_seconds)


@dataclass
class ResourceRequirements:
    """Resource requirements for a pipeline."""
    min_cpus: int = 1
    max_cpus: int = 8
    min_memory_gb: int = 4
    max_memory_gb: int = 16
    requires_gpu: bool = False
    estimated_duration_minutes: int = 60

    def to_dict(self) -> dict:
        """Convert to dictionary for configuration."""
        return {
            "min_cpus": self.min_cpus,
            "max_cpus": self.max_cpus,
            "min_memory_gb": self.min_memory_gb,
            "max_memory_gb": self.max_memory_gb,
            "requires_gpu": self.requires_gpu,
            "estimated_duration_minutes": self.estimated_duration_minutes,
        }


@dataclass
class PipelineDefinition:
    """Complete definition of a pipeline.

    Attributes:
        name: Unique identifier for the pipeline
        display_name: Human-readable name
        stage: Processing stage (determines rough execution order)
        level: Whether this operates on sessions or subjects
        runner: Python module path to the VoxelOps runner
        depends_on: List of pipeline names that must complete first
        triggers: List of pipelines to trigger when this completes
        required_inputs: Required BIDS suffixes (e.g., ["dwi", "T1w"])
        output_suffixes: Output BIDS suffixes produced
        retry_policy: How to handle failures
        resources: Resource requirements
        enabled: Whether this pipeline is enabled
        queue: Celery queue to use
        timeout_minutes: Maximum execution time
    """
    name: str
    display_name: str
    stage: PipelineStage
    level: PipelineLevel
    runner: str
    depends_on: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    required_inputs: list[str] = field(default_factory=list)
    output_suffixes: list[str] = field(default_factory=list)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    resources: ResourceRequirements = field(default_factory=ResourceRequirements)
    enabled: bool = True
    queue: str = "default"
    timeout_minutes: int = 60

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PipelineDefinition):
            return False
        return self.name == other.name


class DependencyError(Exception):
    """Raised when there's a problem with pipeline dependencies."""
    pass


class PipelineRegistry:
    """Registry of all available pipelines."""

    def __init__(self):
        self._pipelines: dict[str, PipelineDefinition] = {}
        self._register_default_pipelines()

    def _register_default_pipelines(self) -> None:
        """Register the default neuroflow pipelines."""

        # BIDS Conversion
        self.register(PipelineDefinition(
            name="bids_conversion",
            display_name="BIDS Conversion (HeudiConv)",
            stage=PipelineStage.BIDS_CONVERSION,
            level=PipelineLevel.SESSION,
            runner="voxelops.runners.heudiconv.run_heudiconv",
            depends_on=[],
            triggers=["qsiprep"],
            required_inputs=[],
            output_suffixes=["T1w", "dwi", "flair"],
            retry_policy=RetryPolicy(max_attempts=2, initial_delay_seconds=300),
            resources=ResourceRequirements(
                min_cpus=1, max_cpus=2,
                min_memory_gb=4, max_memory_gb=8,
                estimated_duration_minutes=30,
            ),
            queue="bids",
            timeout_minutes=60,
        ))

        # QSIPrep (subject-level)
        self.register(PipelineDefinition(
            name="qsiprep",
            display_name="QSIPrep Preprocessing",
            stage=PipelineStage.PREPROCESSING,
            level=PipelineLevel.SUBJECT,
            runner="voxelops.runners.qsiprep.run_qsiprep",
            depends_on=["bids_conversion"],
            triggers=["qsirecon"],
            required_inputs=["dwi"],
            output_suffixes=["dwi"],
            retry_policy=RetryPolicy(
                max_attempts=3,
                initial_delay_seconds=1800,
                max_delay_seconds=7200,
            ),
            resources=ResourceRequirements(
                min_cpus=8, max_cpus=16,
                min_memory_gb=16, max_memory_gb=32,
                estimated_duration_minutes=720,
            ),
            queue="heavy_processing",
            timeout_minutes=1440,
        ))

        # QSIRecon (session-level)
        self.register(PipelineDefinition(
            name="qsirecon",
            display_name="QSIRecon Reconstruction",
            stage=PipelineStage.RECONSTRUCTION,
            level=PipelineLevel.SESSION,
            runner="voxelops.runners.qsirecon.run_qsirecon",
            depends_on=["qsiprep"],
            triggers=["qsiparc"],
            required_inputs=["dwi"],
            output_suffixes=["dwi"],
            retry_policy=RetryPolicy(max_attempts=3, initial_delay_seconds=1800),
            resources=ResourceRequirements(
                min_cpus=4, max_cpus=8,
                min_memory_gb=8, max_memory_gb=16,
                estimated_duration_minutes=480,
            ),
            queue="processing",
            timeout_minutes=720,
        ))

        # QSIParc (session-level)
        self.register(PipelineDefinition(
            name="qsiparc",
            display_name="QSIParc Parcellation",
            stage=PipelineStage.PARCELLATION,
            level=PipelineLevel.SESSION,
            runner="voxelops.runners.qsiparc.run_qsiparc",
            depends_on=["qsirecon"],
            triggers=[],
            required_inputs=[],
            output_suffixes=["connmatrix"],
            retry_policy=RetryPolicy(max_attempts=3, initial_delay_seconds=300),
            resources=ResourceRequirements(
                min_cpus=2, max_cpus=4,
                min_memory_gb=4, max_memory_gb=8,
                estimated_duration_minutes=120,
            ),
            queue="processing",
            timeout_minutes=240,
        ))

    def register(self, pipeline: PipelineDefinition) -> None:
        """Register a pipeline definition."""
        if pipeline.name in self._pipelines:
            log.warning("registry.overwrite", pipeline=pipeline.name)
        self._pipelines[pipeline.name] = pipeline
        log.debug("registry.registered", pipeline=pipeline.name)

    def get(self, name: str) -> PipelineDefinition | None:
        """Get a pipeline definition by name."""
        return self._pipelines.get(name)

    def get_all(self, enabled_only: bool = True) -> list[PipelineDefinition]:
        """Get all registered pipelines."""
        pipelines = list(self._pipelines.values())
        if enabled_only:
            pipelines = [p for p in pipelines if p.enabled]
        return pipelines

    def get_by_stage(self, stage: PipelineStage, enabled_only: bool = True) -> list[PipelineDefinition]:
        """Get all pipelines for a specific stage."""
        pipelines = [p for p in self._pipelines.values() if p.stage == stage]
        if enabled_only:
            pipelines = [p for p in pipelines if p.enabled]
        return pipelines

    def get_by_level(self, level: PipelineLevel, enabled_only: bool = True) -> list[PipelineDefinition]:
        """Get all pipelines for a specific level."""
        pipelines = [p for p in self._pipelines.values() if p.level == level]
        if enabled_only:
            pipelines = [p for p in pipelines if p.enabled]
        return pipelines

    def get_dependencies(self, name: str, recursive: bool = True) -> list[PipelineDefinition]:
        """Get all dependencies for a pipeline."""
        pipeline = self.get(name)
        if not pipeline:
            return []

        if not recursive:
            return [self._pipelines[dep] for dep in pipeline.depends_on if dep in self._pipelines]

        visited: set[str] = set()
        result: list[PipelineDefinition] = []

        def resolve(current: str, path: list[str]) -> None:
            if current in path:
                raise DependencyError(f"Circular dependency: {' -> '.join(path + [current])}")
            if current in visited:
                return
            visited.add(current)
            current_pipeline = self.get(current)
            if current_pipeline:
                for dep in current_pipeline.depends_on:
                    resolve(dep, path + [current])
                if current != name:
                    result.append(current_pipeline)

        resolve(name, [])
        return result

    def get_execution_order(self, enabled_only: bool = True) -> list[PipelineDefinition]:
        """Get pipelines in dependency-resolved execution order (topological sort)."""
        pipelines = self.get_all(enabled_only=enabled_only)
        in_degree: dict[str, int] = {p.name: 0 for p in pipelines}

        for pipeline in pipelines:
            for dep in pipeline.depends_on:
                if dep in in_degree:
                    in_degree[pipeline.name] += 1

        queue = [name for name, degree in in_degree.items() if degree == 0]
        result: list[PipelineDefinition] = []

        while queue:
            queue.sort(key=lambda n: self._pipelines[n].stage)
            current = queue.pop(0)
            result.append(self._pipelines[current])

            for pipeline in pipelines:
                if current in pipeline.depends_on:
                    in_degree[pipeline.name] -= 1
                    if in_degree[pipeline.name] == 0:
                        queue.append(pipeline.name)

        if len(result) != len(pipelines):
            remaining = [p.name for p in pipelines if p not in result]
            raise DependencyError(f"Circular dependency involving: {remaining}")

        return result

    def validate_dependencies(self) -> list[str]:
        """Validate all pipeline dependencies. Returns list of error messages."""
        errors: list[str] = []

        for pipeline in self._pipelines.values():
            for dep in pipeline.depends_on:
                if dep not in self._pipelines:
                    errors.append(f"Pipeline '{pipeline.name}' depends on unknown pipeline '{dep}'")
                elif self._pipelines[dep].stage > pipeline.stage:
                    errors.append(f"Pipeline '{pipeline.name}' depends on '{dep}' which runs later")

        try:
            self.get_execution_order(enabled_only=False)
        except DependencyError as e:
            errors.append(str(e))

        return errors

    def update_from_config(self, config: NeuroflowConfig) -> None:
        """Update pipeline definitions from configuration."""
        for pipeline_cfg in config.pipelines.session_level:
            if pipeline_cfg.name in self._pipelines:
                pipeline = self._pipelines[pipeline_cfg.name]
                pipeline.enabled = pipeline_cfg.enabled
                pipeline.timeout_minutes = pipeline_cfg.timeout_minutes

        for pipeline_cfg in config.pipelines.subject_level:
            if pipeline_cfg.name in self._pipelines:
                pipeline = self._pipelines[pipeline_cfg.name]
                pipeline.enabled = pipeline_cfg.enabled
                pipeline.timeout_minutes = pipeline_cfg.timeout_minutes


# Global registry instance
_registry: PipelineRegistry | None = None

def get_registry() -> PipelineRegistry:
    """Get the global pipeline registry instance."""
    global _registry
    if _registry is None:
        _registry = PipelineRegistry()
    return _registry
