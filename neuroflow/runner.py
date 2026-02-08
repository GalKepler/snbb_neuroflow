"""Parallel pipeline execution via ProcessPoolExecutor."""

import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import structlog

from neuroflow.adapters.voxelops import PipelineResult
from neuroflow.config import NeuroflowConfig

log = structlog.get_logger("runner")


@dataclass
class RunRequest:
    """Request to run a pipeline for a session."""

    participant_id: str
    session_id: str
    dicom_path: str
    pipeline_name: str
    force: bool = False


@dataclass
class RunResult:
    """Result of a pipeline run."""

    request: RunRequest
    pipeline_result: PipelineResult | None
    log_path: str = ""
    error: str = ""


def run_single_pipeline(
    config_path: str,
    participant_id: str,
    session_id: str,
    dicom_path: str,
    pipeline_name: str,
    log_dir: str,
    force: bool = False,
) -> dict:
    """Run a single pipeline in a worker process.

    All arguments are plain strings/bools for picklability.
    Returns a dict with result fields.
    """
    from neuroflow.adapters.voxelops import VoxelopsAdapter
    from neuroflow.core.logging import setup_session_logger, write_to_log

    config = NeuroflowConfig.from_yaml(config_path)

    # Setup per-session log file — redirects structlog to the file
    log_path_obj = None
    log_path = ""
    if log_dir:
        log_path_obj = setup_session_logger(
            Path(log_dir), pipeline_name, participant_id, session_id
        )
        log_path = str(log_path_obj)

    # Get a fresh logger (now pointing at the file)
    slog = structlog.get_logger("runner").bind(
        pipeline=pipeline_name,
        participant=participant_id,
        session=session_id,
    )

    slog.info("pipeline.start", config_path=config_path, dicom_path=dicom_path)
    start_time = time.time()

    try:
        adapter = VoxelopsAdapter(config)
        result = adapter.run(
            pipeline_name=pipeline_name,
            participant_id=participant_id,
            session_id=session_id,
            dicom_path=Path(dicom_path) if dicom_path else None,
            force=force,
        )

        duration = result.duration_seconds or (time.time() - start_time)

        if result.success:
            slog.info(
                "pipeline.completed",
                exit_code=result.exit_code,
                duration=f"{duration:.1f}s",
                output_path=str(result.output_path or ""),
            )
        else:
            slog.error(
                "pipeline.failed",
                exit_code=result.exit_code,
                duration=f"{duration:.1f}s",
                error=result.error_message or "unknown error",
            )

        # Write stdout/stderr/error details to the log file
        if log_path_obj:
            if result.logs:
                write_to_log(log_path_obj, "STDOUT", result.logs)
            if result.error_message:
                write_to_log(log_path_obj, "ERROR", result.error_message)
            if result.metrics:
                import json
                write_to_log(
                    log_path_obj, "METRICS", json.dumps(result.metrics, indent=2, default=str)
                )

        return {
            "success": result.success,
            "exit_code": result.exit_code,
            "output_path": str(result.output_path) if result.output_path else "",
            "error_message": result.error_message or "",
            "duration_seconds": duration,
            "log_path": log_path,
        }

    except Exception as e:
        duration = time.time() - start_time
        tb = traceback.format_exc()
        slog.error("pipeline.exception", error=str(e), duration=f"{duration:.1f}s")

        if log_path_obj:
            write_to_log(log_path_obj, "TRACEBACK", tb)

        return {
            "success": False,
            "exit_code": -1,
            "output_path": "",
            "error_message": str(e),
            "duration_seconds": duration,
            "log_path": log_path,
        }


class PipelineRunner:
    """Runs pipelines in parallel via ProcessPoolExecutor."""

    def __init__(self, config: NeuroflowConfig, config_path: str):
        self.config = config
        self.config_path = config_path

    def run_batch(
        self, requests: list[RunRequest], dry_run: bool = False
    ) -> list[RunResult]:
        """Submit all requests to ProcessPoolExecutor, collect via as_completed."""
        if not requests:
            return []

        if dry_run:
            results = []
            for req in requests:
                log.info(
                    "runner.dry_run",
                    pipeline=req.pipeline_name,
                    participant=req.participant_id,
                    session=req.session_id,
                )
                results.append(
                    RunResult(
                        request=req,
                        pipeline_result=None,
                    )
                )
            return results

        max_workers = self.config.execution.max_workers
        log_dir = str(self.config.paths.log_dir) if self.config.execution.log_per_session else ""

        log.info(
            "runner.batch_start",
            total=len(requests),
            max_workers=max_workers,
        )

        results: list[RunResult] = []
        future_to_request = {}

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            for req in requests:
                future = executor.submit(
                    run_single_pipeline,
                    config_path=self.config_path,
                    participant_id=req.participant_id,
                    session_id=req.session_id,
                    dicom_path=req.dicom_path,
                    pipeline_name=req.pipeline_name,
                    log_dir=log_dir,
                    force=req.force,
                )
                future_to_request[future] = req

            for future in as_completed(future_to_request):
                req = future_to_request[future]
                try:
                    result_dict = future.result()
                    pipeline_result = PipelineResult(
                        success=result_dict["success"],
                        exit_code=result_dict["exit_code"],
                        output_path=Path(result_dict["output_path"]) if result_dict["output_path"] else None,
                        error_message=result_dict["error_message"] or None,
                        duration_seconds=result_dict["duration_seconds"],
                    )
                    results.append(
                        RunResult(
                            request=req,
                            pipeline_result=pipeline_result,
                            log_path=result_dict.get("log_path", ""),
                        )
                    )
                    status = "completed" if pipeline_result.success else "failed"
                    log.info(
                        f"runner.{status}",
                        pipeline=req.pipeline_name,
                        participant=req.participant_id,
                        session=req.session_id,
                        duration=pipeline_result.duration_seconds,
                    )

                except Exception as e:
                    results.append(
                        RunResult(
                            request=req,
                            pipeline_result=None,
                            error=str(e),
                        )
                    )
                    log.error(
                        "runner.exception",
                        pipeline=req.pipeline_name,
                        participant=req.participant_id,
                        session=req.session_id,
                        error=str(e),
                    )

        succeeded = sum(1 for r in results if r.pipeline_result and r.pipeline_result.success)
        failed = len(results) - succeeded

        log.info(
            "runner.batch_complete",
            total=len(results),
            succeeded=succeeded,
            failed=failed,
        )

        return results
