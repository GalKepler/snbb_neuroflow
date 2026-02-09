# Phase 1 Implementation Summary: Background Queue with Huey

**Status:** ✅ Completed
**Date:** 2026-02-09
**Branch:** `feature/background-queue-phase1`
**Commit:** 7bfe0a2

## What Was Implemented

Phase 1 adds the core infrastructure for background pipeline execution using Huey with a SQLite backend. The implementation allows pipelines to be enqueued and executed in the background without blocking the CLI terminal.

### Files Added

1. **`neuroflow/tasks.py`** (283 lines)
   - `huey` global instance (SqliteHuey)
   - `configure_huey()` - Configure Huey database location
   - `run_pipeline_task()` - Huey task decorator wrapping `run_single_pipeline()`
   - `enqueue_pipeline()` - Public API to enqueue pipeline runs
   - `get_queue_stats()` - Query pending/scheduled task counts
   - `get_task_result()` - Placeholder for future result retrieval

2. **`tests/test_tasks.py`** (399 lines)
   - 13 comprehensive tests covering:
     - Task enqueueing and ID generation
     - State tracking (queued → running → completed/failed)
     - Error handling and exceptions
     - Multiple tasks per session
     - Queue statistics
   - All tests pass with mock isolation

3. **`docs/background-queue.md`** (full user guide)
   - Quick start guide
   - Architecture diagrams
   - API reference
   - Production deployment with systemd
   - Troubleshooting guide
   - Comparison with Celery

4. **`docs/plans/background-runner-migration.md`** (research + plan)
   - Evaluation of 6 workflow managers
   - Justification for Huey selection
   - 6-phase implementation roadmap
   - Risk mitigation strategies

### Files Modified

1. **`pyproject.toml`**
   - Added `huey>=2.5` dependency

2. **`tests/conftest.py`**
   - Added `sample_config_path` fixture for YAML-based tests

## How It Works

### Architecture

```
┌─────────────────────┐
│ Application Code    │
│ enqueue_pipeline()  │ ← Returns task ID immediately
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Huey SQLite Queue   │ ← Persistent (survives crashes)
│ .neuroflow/huey.db  │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Huey Consumer       │ ← Separate process (huey_consumer)
│ - Pulls tasks       │
│ - Parallel workers  │
│ - Updates state     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ run_pipeline_task() │ ← Wraps run_single_pipeline()
│ - Calls VoxelOps    │
│ - Logs execution    │
│ - Updates CSV state │
└─────────────────────┘
```

### Task Lifecycle

1. **Enqueueing:**
   ```python
   from neuroflow.tasks import enqueue_pipeline

   task_id = enqueue_pipeline(
       config_path="config.yaml",
       participant_id="sub-01",
       session_id="ses-baseline",
       dicom_path="/data/dicom",
       pipeline_name="qsiprep",
       log_dir="/var/log/neuroflow",
   )
   # Returns immediately with task UUID
   # State: "queued" recorded in pipeline_runs.csv
   ```

2. **Execution (in consumer process):**
   ```bash
   # Start consumer in separate terminal/process
   huey_consumer neuroflow.tasks.huey -w 4 -k process
   ```
   - Consumer picks up task from SQLite queue
   - State updated to "running"
   - `run_single_pipeline()` executes
   - VoxelOps runs the actual pipeline (qsiprep, fmriprep, etc.)
   - State updated to "completed" or "failed"

3. **Monitoring:**
   ```python
   from neuroflow.state import SessionState

   state = SessionState(".neuroflow")
   runs = state.load_pipeline_runs()
   print(runs[runs["status"] == "running"])
   ```

### State Tracking

**Hybrid model:**
- **Huey SQLite DB** (`.neuroflow/huey.db`): Transient queue state
- **SessionState CSVs** (`.neuroflow/pipeline_runs.csv`): Authoritative record

This design keeps SessionState as the single source of truth, while Huey handles task distribution.

## Testing

All existing tests continue to pass, plus 13 new tests for the task queue:

```bash
$ pytest tests/test_tasks.py -v
================================= 13 passed =================================

$ pytest tests/ -q
214 passed, 12 skipped in 1.59s
```

### Key Test Coverage

- ✅ Task enqueueing returns valid task ID
- ✅ "queued" status recorded in SessionState
- ✅ Task execution updates state to "running"
- ✅ Successful completion updates to "completed"
- ✅ Failures update to "failed" with error message
- ✅ Exceptions are caught and recorded
- ✅ Multiple tasks for same session work correctly
- ✅ Queue statistics (pending/scheduled counts)

## Documentation

### For Users

**`docs/background-queue.md`** provides:
1. Quick start (install → start consumer → enqueue)
2. API reference with examples
3. Production deployment (systemd service template)
4. Troubleshooting common issues
5. Comparison with Celery

### For Developers

**`docs/plans/background-runner-migration.md`** contains:
1. Technology evaluation (Huey vs 5 alternatives)
2. Decision rationale (why Huey won)
3. 6-phase implementation plan
4. Files changed per phase
5. Migration strategy

## Example Usage

### Starting the Consumer

```bash
# Development
huey_consumer neuroflow.tasks.huey -w 2 -k process -v

# Production (systemd)
sudo systemctl start neuroflow-worker
```

### Enqueueing Tasks

```python
from neuroflow.tasks import enqueue_pipeline, get_queue_stats

# Enqueue a pipeline
task_id = enqueue_pipeline(
    config_path="/etc/neuroflow/config.yaml",
    participant_id="sub-01",
    session_id="ses-baseline",
    dicom_path="/data/raw/sub-01/ses-baseline",
    pipeline_name="qsiprep",
    log_dir="/var/log/neuroflow",
    force=False,
)

print(f"Enqueued: {task_id}")

# Check queue depth
stats = get_queue_stats()
print(f"Pending: {stats['pending']}, Scheduled: {stats['scheduled']}")
```

### Monitoring State

```python
from neuroflow.config import NeuroflowConfig
from neuroflow.state import SessionState

config = NeuroflowConfig.from_yaml("/etc/neuroflow/config.yaml")
state = SessionState(config.execution.state_dir)

# Get all runs for a pipeline
runs = state.load_pipeline_runs()
qsiprep_runs = runs[runs["pipeline_name"] == "qsiprep"]

# Filter by status
running = qsiprep_runs[qsiprep_runs["status"] == "running"]
print(f"Currently running: {len(running)}")

completed = qsiprep_runs[qsiprep_runs["status"] == "completed"]
print(f"Completed: {len(completed)}")
```

## What's NOT Included (Yet)

Phase 1 is **core infrastructure only**. The following are deferred to future phases:

- ❌ CLI integration (`neuroflow run pipeline --background`)
  - Current CLI still uses blocking `PipelineRunner.run_batch()`
  - Will be Phase 2

- ❌ Worker management (`neuroflow worker start/stop/status`)
  - Must start consumer manually with `huey_consumer`
  - Will be Phase 3

- ❌ Queue-aware status display
  - `neuroflow status runs` doesn't show queue depth yet
  - Will be Phase 4

- ❌ Pipeline dependency chains
  - Can't specify "run B after A completes"
  - Will be Phase 5

- ❌ Dynamic retry configuration
  - Tasks currently have `retries=0` hardcoded
  - `retries` parameter in `enqueue_pipeline()` is logged but not used
  - Would need Huey task variants or scheduler API

## Next Steps

### Phase 2: CLI Integration

Update `neuroflow/cli/run.py` to use `enqueue_pipeline()` instead of blocking `run_batch()`:

```python
# Before (blocks):
runner = PipelineRunner(config, config_path)
results = runner.run_batch(requests)

# After (enqueues):
from neuroflow.tasks import enqueue_pipeline
for req in requests:
    task_id = enqueue_pipeline(...)
    console.print(f"Enqueued: {task_id}")
```

Add `--sync` flag to preserve blocking behavior for debugging.

### Phase 3: Worker Management

Add `neuroflow worker` CLI group:
- `neuroflow worker start [-w N] [--daemon]`
- `neuroflow worker stop`
- `neuroflow worker status`

Manage the `huey_consumer` process lifecycle.

### Phase 4: Enhanced Status Display

Update `neuroflow status runs` to show:
- Queue depth (pending tasks)
- Currently running tasks
- Worker count and health

### Phase 5: Production Deployment

- Systemd service integration
- Log rotation
- Monitoring and alerting
- Resource limits

### Phase 6: Advanced Features

- Pipeline dependency chains (DAGs)
- Task priority queues
- Scheduled/cron tasks
- Result caching

## Deployment Checklist

To use Phase 1 in production:

1. ✅ Install neuroflow with Huey: `pip install neuroflow` (includes huey>=2.5)
2. ✅ Configure state directory in `neuroflow.yaml`:
   ```yaml
   execution:
     state_dir: /var/lib/neuroflow/state
   ```
3. ✅ Start Huey consumer:
   ```bash
   huey_consumer neuroflow.tasks.huey -w 4 -k process -l /var/log/neuroflow/huey.log
   ```
4. ✅ Enqueue tasks via Python API (CLI integration not ready yet)
5. ✅ Monitor via SessionState CSVs or `neuroflow status runs`

**Note:** The CLI (`neuroflow run pipeline`) still uses blocking execution. To use the queue, you must enqueue tasks programmatically via the Python API until Phase 2 is complete.

## References

- **Huey Documentation:** https://huey.readthedocs.io/
- **Huey GitHub:** https://github.com/coleifer/huey
- **Migration Plan:** [background-runner-migration.md](background-runner-migration.md)
- **User Guide:** [../background-queue.md](../background-queue.md)
- **Commit:** 7bfe0a2 on `feature/background-queue-phase1`
