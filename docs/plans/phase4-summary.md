# Phase 4 Implementation Summary: Enhanced Status Display

**Status:** ✅ Completed
**Date:** 2026-02-09
**Branch:** `feature/background-queue-phase4`
**Depends on:** Phase 3 (`feature/background-queue-phase3`)

## Overview

Phase 4 enhances the `neuroflow status` command to be queue-aware, providing real-time visibility into background tasks and worker status. This transforms the status command from a passive view of completed runs into an active monitoring tool for ongoing pipeline execution.

**Key Feature:** Queue-aware status display with filtering, real-time updates, and worker integration.

## What Was Implemented

### 🆕 Enhanced Status Features

**1. Queue-Aware Pipeline Display**
- Shows queued tasks alongside completed runs
- Displays task IDs for queued tasks (first 8 characters)
- Combines queue data with historical state data
- Automatic state directory configuration

**2. Status Filtering**
- `--filter` option to filter by status
- Supported filters: `all`, `queued`, `running`, `completed`, `failed`
- Works with both CSV and state-based data
- Shows filtered count in table title

**3. Real-Time Watch Mode**
- `--watch` flag for automatic refresh
- Configurable refresh interval (`--interval N`)
- Clears screen and updates display
- Shows last update timestamp
- Graceful Ctrl+C handling

**4. Worker Status Integration**
- Shows worker status in summary view
- Displays PID when worker is running
- Shows queue depth (pending + scheduled)
- Visual indicators for running/stopped worker

**5. Enhanced Task Information**
- Task IDs for queued/scheduled tasks
- Exit codes for completed tasks
- Duration for finished runs
- Color-coded status indicators

### 📝 Files Created

**1. Added function to `neuroflow/tasks.py` (70 lines)**

**New function:**
- `get_queue_details()` - Get detailed task information from queue
  - Extracts task metadata (ID, pipeline, participant, session)
  - Handles both pending and scheduled tasks
  - Returns list of task dictionaries
  - Gracefully skips invalid tasks

### 📝 Files Modified

**1. `neuroflow/cli/status.py` (184 lines added)**

**New function:**
- `_show_worker_status()` - Display worker and queue status
  - Shows worker PID or "not running"
  - Displays pending task count
  - Visual indicators (✓/✗)

**Enhanced functions:**
- `status()` command - Added `--filter` and `--watch` options
- `_show_summary()` - Integrated worker status display
- `_show_pipelines()` - Queue-aware with filtering
  - Fetches queue details via `get_queue_details()`
  - Combines queue and state data
  - Applies status filters
  - Shows task IDs for queued tasks
  - Shows exit codes for completed tasks

**New function:**
- `_watch_status()` - Watch mode with auto-refresh
  - Clears screen between updates
  - Reloads state on each refresh
  - Shows update timestamp
  - Handles KeyboardInterrupt

**2. `tests/unit/test_cli_status.py` (186 lines added, 6 new tests)**

**New test classes:**
- `TestStatusPipelinesPhase4` (4 tests)
  - test_pipelines_with_queued_tasks
  - test_pipelines_filter_queued
  - test_pipelines_filter_completed
  - test_pipelines_filter_no_matches

- `TestStatusWorkerStatusPhase4` (2 tests)
  - test_summary_shows_worker_running
  - test_summary_shows_worker_not_running

**3. `tests/test_tasks.py` (129 lines added, 5 new tests)**

**New test class:**
- `TestGetQueueDetails` (5 tests)
  - test_get_queue_details_pending
  - test_get_queue_details_scheduled
  - test_get_queue_details_mixed
  - test_get_queue_details_empty
  - test_get_queue_details_invalid_task

## Usage Examples

### Show Summary with Worker Status

```bash
neuroflow status
```

**Output:**
```
Neuroflow Status

Worker: ✓ Running (PID: 12345)  |  Queue: 4 pending

Sessions: 15

Sessions by Status
┏━━━━━━━━━━━┳━━━━━━━┓
┃ Status    ┃ Count ┃
┡━━━━━━━━━━━╇━━━━━━━┩
│ validated │ 10    │
│ completed │ 3     │
│ failed    │ 2     │
└───────────┴───────┘

Pipeline Runs
┏━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━┓
┃ Pipeline ┃ Status    ┃ Count ┃
┡━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━┩
│ qsiprep  │ completed │ 8     │
│ qsiprep  │ queued    │ 3     │
│ qsiprep  │ failed    │ 1     │
└──────────┴───────────┴───────┘
```

### Show All Pipeline Runs (Including Queued)

```bash
neuroflow status --pipelines
```

**Output:**
```
Pipeline Runs (12 total)
┏━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┓
┃ Participant ┃ Session ┃ Pipeline ┃ Status    ┃ Duration ┃ Task ID  ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━┩
│ sub-001     │ ses-01  │ qsiprep  │ queued    │ -        │ abc12345 │
│ sub-002     │ ses-01  │ qsiprep  │ queued    │ -        │ def67890 │
│ sub-003     │ ses-02  │ fmriprep │ scheduled │ -        │ ghi13579 │
│ sub-004     │ ses-01  │ qsiprep  │ completed │ 3600.2s  │ exit: 0  │
│ sub-005     │ ses-01  │ qsiprep  │ completed │ 3821.5s  │ exit: 0  │
│ sub-006     │ ses-01  │ qsiprep  │ failed    │ 120.0s   │ exit: 1  │
└─────────────┴─────────┴──────────┴───────────┴──────────┴──────────┘
```

### Filter by Status

```bash
# Show only queued tasks
neuroflow status --pipelines --filter queued

# Show only completed runs
neuroflow status --pipelines --filter completed

# Show only failed runs
neuroflow status --pipelines --filter failed
```

**Output (queued filter):**
```
Pipeline Runs (3 total, filtered: queued)
┏━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┓
┃ Participant ┃ Session ┃ Pipeline ┃ Status ┃ Duration ┃ Task ID  ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━┩
│ sub-001     │ ses-01  │ qsiprep  │ queued │ -        │ abc12345 │
│ sub-002     │ ses-01  │ qsiprep  │ queued │ -        │ def67890 │
│ sub-007     │ ses-02  │ fmriprep │ queued │ -        │ jkl24680 │
└─────────────┴─────────┴──────────┴────────┴──────────┴──────────┘
```

### Watch Mode (Real-Time Updates)

```bash
# Watch with default 5s interval
neuroflow status --pipelines --watch

# Watch with custom interval
neuroflow status --pipelines --watch --interval 10

# Watch filtered view
neuroflow status --pipelines --filter queued --watch
```

**Output:**
```
Pipeline Runs (3 total, filtered: queued)
┏━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┓
┃ Participant ┃ Session ┃ Pipeline ┃ Status ┃ Duration ┃ Task ID  ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━┩
│ sub-001     │ ses-01  │ qsiprep  │ queued │ -        │ abc12345 │
│ sub-002     │ ses-01  │ qsiprep  │ queued │ -        │ def67890 │
└─────────────┴─────────┴──────────┴────────┴──────────┴──────────┘

Last updated: 2026-02-09 14:32:15 | Refresh every 5s | Press Ctrl+C to exit
```

## Architecture

### Data Flow

```
neuroflow status --pipelines --filter queued
         ↓
    Load config, create SessionState
         ↓
    Configure Huey with state_dir
         ↓
    Get queue details from Huey
         ↓
    Load pipeline runs from CSV state
         ↓
    Combine queue + state data
         ↓
    Apply status filter
         ↓
    Display table with task IDs
```

### Queue Integration

**Phase 4 integrates three data sources:**

1. **Huey Queue** (via `get_queue_details()`)
   - Pending tasks (ready to run)
   - Scheduled tasks (future execution)
   - Task metadata (ID, pipeline, participant, session)

2. **CSV State** (via `SessionState.load_pipeline_runs()`)
   - Completed runs with duration and exit code
   - Failed runs with error messages
   - Running tasks (set by worker)

3. **Worker Status** (via `_read_pid()` and `get_queue_stats()`)
   - Worker PID if running
   - Queue depth (pending + scheduled counts)

### get_queue_details() Function

```python
def get_queue_details() -> list[dict]:
    """Get detailed information about tasks in the queue.

    Returns list of queued tasks with metadata:
    - task_id: Task ID (string UUID)
    - pipeline_name: Name of the pipeline
    - participant_id: Participant identifier
    - session_id: Session identifier
    - status: "queued" or "scheduled"
    """
    tasks = []

    # Get pending tasks (ready to run)
    for task in huey.pending():
        tasks.append({
            "task_id": task.id,
            "pipeline_name": task.args[4],  # pipeline_name
            "participant_id": task.args[1],  # participant_id
            "session_id": task.args[2],  # session_id
            "status": "queued",
        })

    # Get scheduled tasks (future execution)
    for task in huey.scheduled():
        tasks.append({
            "task_id": task.id,
            "pipeline_name": task.args[4],
            "participant_id": task.args[1],
            "session_id": task.args[2],
            "status": "scheduled",
        })

    return tasks
```

### Watch Mode Implementation

```python
def _watch_status(...):
    """Watch status with automatic refresh."""
    try:
        while True:
            # Clear screen
            console.clear()

            # Reload state
            state = SessionState(config.execution.state_dir)

            # Display status
            _show_pipelines(state, "table", status_filter)

            # Show refresh info
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            console.print(f"Last updated: {now} | Refresh every {interval}s")

            # Wait for next refresh
            time.sleep(interval)

    except KeyboardInterrupt:
        console.print("Watch mode stopped")
```

## Testing

### Test Results

```
244 passed, 12 skipped in 2.74s
```

**New tests:** 11 total (5 tasks, 4 pipelines, 2 worker status)
**No regressions:** All existing tests continue to pass

### Test Coverage

**1. get_queue_details() Tests (5 tests)**
- ✅ Get pending tasks
- ✅ Get scheduled tasks
- ✅ Mixed pending and scheduled
- ✅ Empty queue
- ✅ Invalid task handling (graceful skip)

**2. Pipeline Filtering Tests (4 tests)**
- ✅ Show queued tasks in pipelines
- ✅ Filter by queued status
- ✅ Filter by completed status
- ✅ No matches for filter

**3. Worker Status Tests (2 tests)**
- ✅ Summary shows worker running (with PID)
- ✅ Summary shows worker not running

### Test Strategy

- Mock `huey.pending()` and `huey.scheduled()` for queue data
- Mock `SessionState` for CSV state data
- Mock `_read_pid()` for worker status
- Mock `configure_huey()` to prevent actual Huey configuration
- Use real pandas DataFrames for data manipulation
- Test both table and CSV/JSON output formats

### Running Tests

```bash
# All Phase 4 tests
pytest tests/unit/test_cli_status.py::TestStatusPipelinesPhase4 -v
pytest tests/unit/test_cli_status.py::TestStatusWorkerStatusPhase4 -v
pytest tests/test_tasks.py::TestGetQueueDetails -v

# Specific test
pytest tests/unit/test_cli_status.py::TestStatusPipelinesPhase4::test_pipelines_with_queued_tasks -v

# Full suite
pytest tests/ -v
```

## Benefits Over Phase 3

| Feature | Phase 3 | Phase 4 |
|---------|---------|---------|
| **Queue visibility** | Via `worker status` only | Integrated in all status views |
| **Queued tasks** | Not shown | Shown with task IDs |
| **Status filtering** | Not available | Filter by queued/running/completed/failed |
| **Real-time updates** | Manual refresh | `--watch` mode with auto-refresh |
| **Worker status** | Separate command | Integrated in summary |
| **Task tracking** | No task IDs | Task IDs for queued tasks |
| **Monitoring** | Passive (completed only) | Active (ongoing + completed) |

## Use Cases

### 1. Monitor Queue During Batch Processing

```bash
# Watch queued tasks in real-time
neuroflow status --pipelines --filter queued --watch
```

**Scenario:** You've enqueued 100 pipelines. Watch mode shows tasks moving from queued → running → completed.

### 2. Check Worker Status

```bash
# Quick status check
neuroflow status
```

**Shows:**
- Is worker running? (PID)
- How many tasks in queue?
- Recent completions/failures

### 3. Debug Failed Runs

```bash
# Show only failed runs
neuroflow status --pipelines --filter failed
```

**Shows:** All failed runs with exit codes and participant/session IDs for investigation.

### 4. Track Specific Task

```bash
# Get task ID when enqueueing
neuroflow run pipeline qsiprep sub-001 ses-01
# Output: Enqueued: abc12345...

# Find task in queue
neuroflow status --pipelines --filter queued | grep abc12345
```

## Known Limitations

### 1. Task State vs Queue State

**Issue:** Tasks may briefly appear in both "queued" and "running" status during state transitions.

**Reason:** Worker updates CSV state to "running" before removing task from queue.

**Workaround:** Phase 4 shows queue state (authoritative for queued tasks).

### 2. Watch Mode Screen Flicker

**Issue:** Screen clears between refreshes, causing flicker.

**Reason:** Terminal clears entire screen each refresh.

**Future:** Use ncurses or rich.live for smoother updates.

### 3. No Running Task Details

**Issue:** Running tasks show in state but not in queue details.

**Reason:** Once dequeued, task is no longer in Huey queue.

**Future:** Add worker heartbeat to track currently executing tasks.

### 4. CSV/JSON Format with Watch

**Issue:** Watch mode only works with table format.

**Reason:** CSV/JSON don't support terminal clearing and refresh timestamps.

**Workaround:** Use table format for watch mode.

## Comparison with External Tools

### vs. Manual Queue Inspection

**Before (manual):**
```python
from neuroflow.tasks import huey
pending = len(huey.pending())
scheduled = len(huey.scheduled())
print(f"Pending: {pending}, Scheduled: {scheduled}")
```

**After (Phase 4):**
```bash
neuroflow status
# Shows: Queue: 15 pending
```

### vs. Worker Status Command

**Before (Phase 3):**
```bash
# Worker status
neuroflow worker status
# Shows: Pending: 3, Scheduled: 1

# Pipeline status
neuroflow status --pipelines
# Shows: Only completed runs
```

**After (Phase 4):**
```bash
# Integrated view
neuroflow status --pipelines
# Shows: Worker status + queue + completed runs
```

## Migration from Phase 3

**Phase 3 workflow:**
```bash
# Check worker
neuroflow worker status
# Output: Pending: 3, Scheduled: 1

# Check runs (only completed)
neuroflow status --pipelines
```

**Phase 4 workflow:**
```bash
# Check everything at once
neuroflow status --pipelines
# Shows: Queued (3) + Scheduled (1) + Completed runs

# Or watch in real-time
neuroflow status --pipelines --watch
```

## Next Steps

### Phase 5: Enhanced Worker Management

**Goal:** Multi-worker support and worker pools.

**Features:**
- Multiple worker profiles (fast/slow queues)
- Task priorities (high/low/normal)
- Worker pools for different pipeline types
- Auto-scaling based on queue depth

### Phase 6: Production Monitoring

**Goal:** Production-ready monitoring and alerting.

**Features:**
- Prometheus metrics endpoint
- Grafana dashboard templates
- Alert rules for failed tasks and stalled queues
- Integration with PagerDuty/Slack

### Phase 7: Task Retry and Recovery

**Goal:** Automatic retry with exponential backoff.

**Features:**
- Configurable retry policies per pipeline
- Dead letter queue for permanently failed tasks
- Task replay from specific point
- Automatic cleanup of stale tasks

## References

- **Phase 1 Summary:** [phase1-summary.md](phase1-summary.md)
- **Phase 2 Summary:** [phase2-summary.md](phase2-summary.md)
- **Phase 3 Summary:** [phase3-summary.md](phase3-summary.md)
- **Implementation Plan:** [background-runner-migration.md](background-runner-migration.md)
- **User Guide:** [../background-queue.md](../background-queue.md)
- **Branch:** `feature/background-queue-phase4`
