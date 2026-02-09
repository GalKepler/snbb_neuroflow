"""Huey task definitions for background pipeline execution.

This module provides a Huey-based task queue for executing neuroimaging pipelines
in the background. Tasks are stored in a SQLite database and executed by a
separate consumer process.

Usage:
    # In your application code:
    from neuroflow.tasks import enqueue_pipeline

    task_id = enqueue_pipeline(
        config_path="/path/to/config.yaml",
        participant_id="sub-01",
        session_id="ses-baseline",
        dicom_path="/data/dicom",
        pipeline_name="qsiprep",
        log_dir="/var/log/neuroflow",
        force=False,
        retries=2,
    )

    # Start the consumer:
    # huey_consumer neuroflow.tasks.huey -w 4 -k process

Environment Variables:
    NEUROFLOW_STATE_DIR: Override the default state directory for Huey database.
                         Defaults to ".neuroflow" if not set.
"""

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import structlog
from huey import SqliteHuey, crontab

from neuroflow.runner import run_single_pipeline

log = structlog.get_logger("tasks")

# Determine Huey database path from environment or default
# This allows the consumer to use the same state_dir as configured
_state_dir = os.getenv("NEUROFLOW_STATE_DIR", ".neuroflow")
_huey_db_path = str(Path(_state_dir) / "huey.db")

# Global Huey instance - initialized at module import time
# Path can be overridden via NEUROFLOW_STATE_DIR environment variable
huey = SqliteHuey(
    name="neuroflow",
    filename=_huey_db_path,
    results=True,  # Store task results
    store_none=False,  # Don't store None results
    utc=True,  # Use UTC timestamps
    immediate=False,  # Don't execute tasks immediately (use consumer)
)

log.debug("tasks.initialized", huey_db=_huey_db_path)


def configure_huey(state_dir: str | Path) -> None:
    """Configure the Huey instance with a custom state directory.

    This should be called before enqueuing any tasks to ensure the SQLite
    database is created in the correct location and that the CLI uses the
    same database as the consumer.

    Note: The consumer process reads NEUROFLOW_STATE_DIR environment variable
    at import time, so make sure to set it before starting the consumer:
        NEUROFLOW_STATE_DIR=/path/to/state huey_consumer neuroflow.tasks.huey

    Args:
        state_dir: Directory where huey.db will be stored.
    """
    global huey, _huey_db_path
    db_path = Path(state_dir) / "huey.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    _huey_db_path = str(db_path)

    huey = SqliteHuey(
        name="neuroflow",
        filename=_huey_db_path,
        results=True,
        store_none=False,
        utc=True,
        immediate=False,
    )

    log.info("tasks.configured", huey_db=_huey_db_path)


@huey.task(retries=0, context=True)
def run_pipeline_task(
    config_path: str,
    participant_id: str,
    session_id: str,
    dicom_path: str,
    pipeline_name: str,
    log_dir: str,
    force: bool = False,
    task=None,  # Huey injects this when context=True
) -> dict:
    """Background task wrapper for run_single_pipeline.

    This task executes a single pipeline run for a participant/session.
    It wraps the existing run_single_pipeline function and adds state
    tracking via SessionState.

    Args:
        config_path: Path to the neuroflow configuration YAML file.
        participant_id: Participant identifier (with or without 'sub-' prefix).
        session_id: Session identifier (with or without 'ses-' prefix).
        dicom_path: Path to the DICOM directory for this session.
        pipeline_name: Name of the pipeline to run.
        log_dir: Directory for session-specific log files.
        force: If True, re-run even if already completed.
        task: Huey task context (injected automatically).

    Returns:
        Dictionary with run result fields: success, exit_code, output_path,
        error_message, duration_seconds, log_path.
    """
    from neuroflow.config import NeuroflowConfig
    from neuroflow.state import SessionState

    # Get task ID for logging
    task_id = task.id if task else "unknown"

    log.info(
        "task.start",
        task_id=task_id,
        pipeline=pipeline_name,
        participant=participant_id,
        session=session_id,
    )

    # Initialize state tracking
    config = NeuroflowConfig.from_yaml(config_path)
    state = SessionState(config.execution.state_dir)

    # Record task as running
    start_time = datetime.now(timezone.utc).isoformat()
    state.record_pipeline_run(
        participant_id=participant_id,
        session_id=session_id,
        pipeline_name=pipeline_name,
        status="running",
        start_time=start_time,
    )

    try:
        # Execute the pipeline
        result_dict = run_single_pipeline(
            config_path=config_path,
            participant_id=participant_id,
            session_id=session_id,
            dicom_path=dicom_path,
            pipeline_name=pipeline_name,
            log_dir=log_dir,
            force=force,
        )

        # Update state with completion
        end_time = datetime.now(timezone.utc).isoformat()
        status = "completed" if result_dict.get("success") else "failed"

        state.record_pipeline_run(
            participant_id=participant_id,
            session_id=session_id,
            pipeline_name=pipeline_name,
            status=status,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=str(result_dict.get("duration_seconds", "")),
            exit_code=str(result_dict.get("exit_code", "")),
            error_message=result_dict.get("error_message", ""),
            output_path=result_dict.get("output_path", ""),
            log_path=result_dict.get("log_path", ""),
        )

        log.info(
            "task.complete",
            task_id=task_id,
            pipeline=pipeline_name,
            participant=participant_id,
            session=session_id,
            success=result_dict.get("success"),
            duration=result_dict.get("duration_seconds"),
        )

        return result_dict

    except Exception as e:
        # Record failure
        end_time = datetime.now(timezone.utc).isoformat()
        error_msg = str(e)

        state.record_pipeline_run(
            participant_id=participant_id,
            session_id=session_id,
            pipeline_name=pipeline_name,
            status="failed",
            start_time=start_time,
            end_time=end_time,
            error_message=error_msg,
        )

        log.error(
            "task.failed",
            task_id=task_id,
            pipeline=pipeline_name,
            participant=participant_id,
            session=session_id,
            error=error_msg,
        )

        # Re-raise so Huey can handle retries
        raise


def enqueue_pipeline(
    config_path: str,
    participant_id: str,
    session_id: str,
    dicom_path: str,
    pipeline_name: str,
    log_dir: str,
    force: bool = False,
    retries: int = 0,
) -> str:
    """Enqueue a pipeline run for background execution.

    This function adds a pipeline run to the Huey task queue and returns
    immediately. The actual execution happens in the Huey consumer process.

    Args:
        config_path: Path to the neuroflow configuration YAML file.
        participant_id: Participant identifier (with or without 'sub-' prefix).
        session_id: Session identifier (with or without 'ses-' prefix).
        dicom_path: Path to the DICOM directory for this session.
        pipeline_name: Name of the pipeline to run.
        log_dir: Directory for session-specific log files.
        force: If True, re-run even if already completed.
        retries: Number of times to retry on failure (default: 0).

    Returns:
        Task ID (string UUID) that can be used to query task status.

    Example:
        >>> task_id = enqueue_pipeline(
        ...     config_path="/etc/neuroflow/config.yaml",
        ...     participant_id="sub-01",
        ...     session_id="ses-baseline",
        ...     dicom_path="/data/dicom/sub-01/ses-baseline",
        ...     pipeline_name="qsiprep",
        ...     log_dir="/var/log/neuroflow",
        ...     force=False,
        ...     retries=2,
        ... )
        >>> print(f"Enqueued task: {task_id}")
    """
    from neuroflow.config import NeuroflowConfig
    from neuroflow.state import SessionState

    # Enqueue the task using the already-decorated task
    # Note: retries parameter is currently not dynamically configurable
    # The task uses retries=0 by default; for custom retries, we'd need
    # to create task variants or use Huey's revoke/retry mechanism
    result = run_pipeline_task(
        config_path=config_path,
        participant_id=participant_id,
        session_id=session_id,
        dicom_path=dicom_path,
        pipeline_name=pipeline_name,
        log_dir=log_dir,
        force=force,
    )

    # Record as queued in state
    config = NeuroflowConfig.from_yaml(config_path)
    state = SessionState(config.execution.state_dir)
    state.record_pipeline_run(
        participant_id=participant_id,
        session_id=session_id,
        pipeline_name=pipeline_name,
        status="queued",
    )

    task_id = result.id
    log.info(
        "task.enqueued",
        task_id=task_id,
        pipeline=pipeline_name,
        participant=participant_id,
        session=session_id,
        retries=retries,
    )

    return task_id


def get_task_result(task_id: str, blocking: bool = False, timeout: int | None = None) -> dict | None:
    """Get the result of a task by ID.

    Args:
        task_id: Task ID returned by enqueue_pipeline.
        blocking: If True, wait for the task to complete.
        timeout: Maximum time to wait in seconds (only used if blocking=True).

    Returns:
        Result dictionary if available, None otherwise.

    Raises:
        TaskException: If the task failed with an exception.
    """
    # Huey's result API requires accessing the storage directly
    # or using the TaskResultWrapper returned by the task
    # For now, we'll rely on SessionState for status queries
    # This is a placeholder for potential future enhancement
    log.warning("task.result_query", task_id=task_id, message="Use SessionState for status")
    return None


def get_queue_stats() -> dict:
    """Get statistics about the task queue.

    Returns:
        Dictionary with queue statistics:
        - pending: Number of tasks waiting to run
        - scheduled: Number of tasks scheduled for future execution

    Example:
        >>> stats = get_queue_stats()
        >>> print(f"Pending: {stats['pending']}, Scheduled: {stats['scheduled']}")
    """
    pending = len(huey.pending())
    scheduled = len(huey.scheduled())

    return {
        "pending": pending,
        "scheduled": scheduled,
    }


def get_queue_details() -> list[dict]:
    """Get detailed information about tasks in the queue.

    Returns a list of queued tasks with their metadata, including task IDs,
    pipeline names, participant/session IDs, and queue status.

    Returns:
        List of dictionaries, each containing:
        - task_id: Task ID (string UUID)
        - pipeline_name: Name of the pipeline
        - participant_id: Participant identifier
        - session_id: Session identifier
        - status: "queued" for pending tasks, "scheduled" for scheduled tasks

    Example:
        >>> details = get_queue_details()
        >>> for task in details:
        ...     print(f"{task['task_id']}: {task['pipeline_name']} "
        ...           f"{task['participant_id']}/{task['session_id']}")
    """
    tasks = []

    # Get pending tasks (ready to run)
    for task in huey.pending():
        try:
            # Prefer extracting metadata from keyword arguments when available.
            pipeline_name = None
            participant_id = None
            session_id = None

            # Attempt to read from task.kwargs first (by name).
            task_kwargs = getattr(task, "kwargs", None)
            if isinstance(task_kwargs, dict):
                pipeline_name = task_kwargs.get("pipeline_name")
                participant_id = task_kwargs.get("participant_id")
                session_id = task_kwargs.get("session_id")

            # Fallback to positional args only if needed and available.
            if (pipeline_name is None or participant_id is None or session_id is None):
                task_args = getattr(task, "args", None)
                if isinstance(task_args, (list, tuple)) and len(task_args) >= 5:
                    # Args are: (config_path, participant_id, session_id, dicom_path,
                    #            pipeline_name, log_dir, force)
                    if participant_id is None:
                        participant_id = task_args[1]
                    if session_id is None:
                        session_id = task_args[2]
                    if pipeline_name is None:
                        pipeline_name = task_args[4]

            # Skip tasks that don't have the required metadata.
            if pipeline_name is None or participant_id is None or session_id is None:
                continue

            tasks.append({
                "task_id": task.id,
                "pipeline_name": pipeline_name,
                "participant_id": participant_id,
                "session_id": session_id,
                "status": "queued",
            })
        except AttributeError:
            # Skip tasks that don't have expected structure
            continue

    # Get scheduled tasks (scheduled for future execution)
    for task in huey.scheduled():
        try:
            pipeline_name = None
            participant_id = None
            session_id = None
    def extract_task_metadata(task, status: str) -> dict | None:
        """Extract common metadata from a Huey task.

        Prefer keyword arguments (task.kwargs) but fall back to positional
        arguments (task.args) for backwards compatibility.
        """
        try:
            # First, try to read from keyword arguments (newer tasks)
            kwargs = getattr(task, "kwargs", {}) or {}
            pipeline_name = kwargs.get("pipeline_name")
            participant_id = kwargs.get("participant_id")
            session_id = kwargs.get("session_id")

            # If any of the required fields are missing in kwargs, fall back
            # to positional args as used by older callers.
            if pipeline_name is None or participant_id is None or session_id is None:
                args = getattr(task, "args", ()) or ()
                # Args are: (config_path, participant_id, session_id, dicom_path,
                #            pipeline_name, log_dir, force, ...)
                if len(args) >= 5:
                    participant_id = participant_id or args[1]
                    session_id = session_id or args[2]
                    pipeline_name = pipeline_name or args[4]
                else:
                    return None

            return {
                "task_id": task.id,
                "pipeline_name": pipeline_name,
                "participant_id": participant_id,
                "session_id": session_id,
                "status": status,
            }
        except (IndexError, AttributeError, TypeError):
            # Skip tasks that don't have the expected structure
            return None

    # Get pending tasks (ready to run)
    for task in huey.pending():
        meta = extract_task_metadata(task, status="queued")
        if meta is not None:
            tasks.append(meta)

    # Get scheduled tasks (scheduled for future execution)
    for task in huey.scheduled():
        meta = extract_task_metadata(task, status="scheduled")
        if meta is not None:
            tasks.append(meta)

    return tasks
