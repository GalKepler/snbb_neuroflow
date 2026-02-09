# Plan: Migrate Runner to Background Queue

> **Status:** Draft
> **Date:** 2026-02-09
> **Problem:** `PipelineRunner.run_batch()` uses `ProcessPoolExecutor` which blocks the terminal for the entire duration of all pipeline runs (often hours).

---

## Current Architecture

```
CLI (neuroflow run pipeline qsiprep)
  -> PipelineRunner.run_batch()
    -> ProcessPoolExecutor(max_workers=N)
      -> run_single_pipeline()  [picklable, top-level function]
      -> run_single_pipeline()
      -> ...
    -> as_completed()  # BLOCKS until all done
  -> record results to CSV
  -> print summary table
```

**Pain points:**
1. Terminal is occupied for the entire batch (neuroimaging pipelines run for hours)
2. Closing the terminal kills all running pipelines
3. No way to enqueue new work while a batch is running
4. No crash recovery -- if the process dies, queue state is lost

---

## Recommended Approach: Huey with SQLite Backend

### Why Huey

| Criteria | Huey | Simple daemon | RQ | Dramatiq | Prefect | Dask |
|---|---|---|---|---|---|---|
| External infrastructure | **None** | None | Redis | Redis/RabbitMQ | None (runs server) | None (runs scheduler) |
| New dependencies | **1 (zero-dep)** | 1-2 | 2+ server | 2+ server | 30+ pkgs | 10+ pkgs |
| Persistent queue | **SQLite** | SQLite | Redis | Redis | SQLite | No |
| Crash recovery | **Yes** | Yes (manual) | Yes | Yes | Yes | No |
| Built-in retries | **Yes** | No | Yes | Yes | Yes | No |
| Process workers | **Yes (-k process)** | Yes | Yes | Yes | Yes | Yes |
| Code to write | **~50 lines** | ~200 lines | ~50 lines | ~50 lines | ~80 lines | ~40 lines |
| Maintenance | Active (v2.6.0, Jan 2026, 5.7k stars) | N/A | Active | Active | Active | Active |

**Huey wins** because it:
- Adds **zero infrastructure** (SQLite is stdlib)
- Is a **single zero-dependency package** (`pip install huey`)
- Maps directly to the existing `run_single_pipeline()` function
- Has a consumer process with `-k process` workers (same model as current `ProcessPoolExecutor`)
- Provides built-in retries, which `PipelineConfig.retries` already configures but `runner.py` doesn't use
- Queue persists in SQLite, surviving crashes and restarts

**Rejected alternatives:**
- **RQ / Dramatiq** -- require Redis or RabbitMQ (same reason Celery was removed)
- **Prefect** -- pulls in 30+ deps including SQLAlchemy (which was removed), overkill
- **Dask** -- no persistent queue, heavy deps, designed for data parallelism not pipeline orchestration
- **Simple daemon** -- viable but requires writing ~200 lines of plumbing that Huey provides for free

---

## Implementation Plan

### Phase 1: Add Huey Task Definitions

**New file: `neuroflow/tasks.py`**

```python
"""Huey task definitions for background pipeline execution."""

from huey import SqliteHuey

from neuroflow.runner import run_single_pipeline

# Initialized lazily by get_huey() based on config
_huey: SqliteHuey | None = None


def get_huey(state_dir: str = ".neuroflow") -> SqliteHuey:
    """Get or create the Huey instance with SQLite backend."""
    global _huey
    if _huey is None:
        from pathlib import Path
        db_path = str(Path(state_dir) / "huey.db")
        _huey = SqliteHuey("neuroflow", filename=db_path)
    return _huey


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
    """Enqueue a pipeline run. Returns the task ID."""
    huey = get_huey()

    @huey.task(retries=retries)
    def _run(config_path, participant_id, session_id, dicom_path,
             pipeline_name, log_dir, force):
        return run_single_pipeline(
            config_path, participant_id, session_id,
            dicom_path, pipeline_name, log_dir, force,
        )

    result = _run(
        config_path, participant_id, session_id,
        dicom_path, pipeline_name, log_dir, force,
    )
    return result.id
```

> **Note:** The exact Huey API for task registration may need adjustment.
> Huey tasks are typically decorated at module level; the lazy init pattern
> above is a sketch. Implementation should test whether dynamic task
> registration works or if a module-level `huey = SqliteHuey(...)` with
> config loaded from env/yaml at import time is needed.

### Phase 2: Update CLI to Enqueue Instead of Block

**Modify `neuroflow/cli/run.py`:**

```python
# Before (blocks):
runner = PipelineRunner(config, config_path)
results = runner.run_batch(requests, dry_run=False)

# After (enqueue + return immediately):
from neuroflow.tasks import enqueue_pipeline

task_ids = []
for req in requests:
    task_id = enqueue_pipeline(
        config_path=config_path,
        participant_id=req.participant_id,
        session_id=req.session_id,
        dicom_path=req.dicom_path,
        pipeline_name=req.pipeline_name,
        log_dir=log_dir,
        force=req.force,
        retries=pipeline_config.retries if pipeline_config else 0,
    )
    task_ids.append(task_id)
    state.record_pipeline_run(
        participant_id=req.participant_id,
        session_id=req.session_id,
        pipeline_name=req.pipeline_name,
        status="queued",
    )

console.print(f"Enqueued {len(task_ids)} pipeline run(s).")
console.print("Monitor with: neuroflow status runs")
```

### Phase 3: Add Consumer Management CLI

**New CLI group: `neuroflow worker`**

```
neuroflow worker start   # start consumer (foreground or daemonized)
neuroflow worker stop    # stop consumer gracefully
neuroflow worker status  # show consumer status (running/stopped, PID, queued tasks)
```

Implementation in `neuroflow/cli/worker.py`:

```python
@click.group()
def worker():
    """Manage the background pipeline worker."""

@worker.command("start")
@click.option("--workers", "-w", default=None, type=int, help="Number of parallel workers")
@click.option("--daemon/--no-daemon", default=False, help="Run in background")
@click.pass_context
def start(ctx, workers, daemon):
    """Start the Huey consumer to process queued pipelines."""
    config = ctx.obj["config"]
    w = workers or config.execution.max_workers
    # Launch huey_consumer (either via subprocess or programmatically)
    ...

@worker.command("stop")
def stop():
    """Stop the running consumer."""
    # Send SIGTERM to consumer PID
    ...

@worker.command("status")
@click.pass_context
def status(ctx):
    """Show worker status and queue depth."""
    ...
```

### Phase 4: Update State Tracking for Queue Awareness

**Modify `neuroflow/state.py`:**

Add a `queued` status to the pipeline run lifecycle:

```
queued -> running -> completed
                  -> failed -> (retry) -> running
```

The Huey task wrapper should call `record_pipeline_run(status="running")` at task start and update to `completed`/`failed` at task end. This replaces the current pattern where `cli/run.py` records results after `run_batch()` returns.

**Modify `run_single_pipeline()` in `runner.py`:**

Add state updates inside the worker function itself (since it now runs asynchronously, not in the CLI process):

```python
def run_single_pipeline(...) -> dict:
    config = NeuroflowConfig.from_yaml(config_path)
    state = SessionState(config.execution.state_dir)

    # Mark as running
    state.record_pipeline_run(
        participant_id=participant_id,
        session_id=session_id,
        pipeline_name=pipeline_name,
        status="running",
        start_time=datetime.now(timezone.utc).isoformat(),
    )

    try:
        result = adapter.run(...)
        state.record_pipeline_run(status="completed", ...)
        return result_dict
    except Exception:
        state.record_pipeline_run(status="failed", ...)
        return error_dict
```

### Phase 5: Enhance Status CLI

**Modify `neuroflow/cli/status.py`:**

Add queue-aware status display:

```
$ neuroflow status runs

Pipeline Runs:
  Pipeline     Queued  Running  Completed  Failed
  qsiprep        3       2         45        1
  fmriprep       0       0         47        0

Worker: running (PID 12345, 4 workers)
Queue depth: 3 tasks pending
```

### Phase 6: Systemd Integration (Optional)

Provide a systemd unit file template for production deployments:

**`contrib/neuroflow-worker.service`:**

```ini
[Unit]
Description=Neuroflow Pipeline Worker
After=network.target

[Service]
Type=simple
User=%i
WorkingDirectory=/path/to/project
ExecStart=/path/to/venv/bin/python -m huey.bin.huey_consumer neuroflow.tasks.huey -w 4 -k process
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

---

## Files Changed

| File | Action | Description |
|---|---|---|
| `pyproject.toml` | Edit | Add `huey>=2.5` to dependencies |
| `neuroflow/tasks.py` | **New** | Huey instance + task definitions |
| `neuroflow/runner.py` | Edit | Add state updates inside `run_single_pipeline()` |
| `neuroflow/cli/run.py` | Edit | Replace blocking `run_batch()` with `enqueue_pipeline()` |
| `neuroflow/cli/worker.py` | **New** | `neuroflow worker start/stop/status` commands |
| `neuroflow/cli/main.py` | Edit | Register `worker` CLI group |
| `neuroflow/cli/status.py` | Edit | Add queue-aware status display |
| `neuroflow/state.py` | Edit | Support `queued`/`running` status transitions |
| `neuroflow/config.py` | Edit | (optional) Add `huey_db` path to `ExecutionConfig` |
| `tests/test_tasks.py` | **New** | Tests for task enqueue/dequeue |
| `tests/test_runner.py` | Edit | Update for new state-tracking behavior |
| `contrib/neuroflow-worker.service` | **New** | Systemd unit template |

---

## Migration Strategy

1. **Keep `PipelineRunner` and `run_batch()`** as a fallback for synchronous/blocking execution (`neuroflow run pipeline --sync`)
2. Make background queue the **default** mode
3. The `--sync` flag would invoke the current blocking behavior for quick one-off runs or debugging

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| SQLite write contention under high concurrency | WAL mode + Huey's built-in busy timeout; neuroimaging workloads are low-throughput (tens of tasks, not thousands) |
| Consumer dies mid-task | Systemd `Restart=always`; Huey re-queues unacknowledged tasks on restart |
| Task registered before consumer starts | Tasks persist in SQLite; consumer picks them up whenever it starts |
| Huey dynamic task registration complexity | Test during Phase 1; fallback to module-level `huey` instance with config from env var |
| State CSV vs Huey DB divergence | Single source of truth: `state.py` CSVs are authoritative; Huey DB is just the transport queue |

---

## Open Questions

1. **Should `neuroflow run pipeline` block by default or enqueue by default?**
   - Option A: Enqueue by default, `--sync` to block (recommended)
   - Option B: Block by default, `--background` to enqueue

2. **Should the consumer be started implicitly?**
   - Option A: User must explicitly run `neuroflow worker start` (explicit, recommended)
   - Option B: `neuroflow run pipeline` auto-starts the consumer if not running (magic)

3. **Pipeline dependency chains** (e.g., run fmriprep only after bids_conversion completes):
   - Currently handled by `run all` running pipelines sequentially
   - With a queue, this becomes: enqueue bids_conversion, then enqueue fmriprep with a dependency
   - Huey supports `task.then(next_task)` for chaining -- investigate in Phase 1
