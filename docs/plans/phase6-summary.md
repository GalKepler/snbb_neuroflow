# Phase 6 Implementation Summary: Priority Visibility

**Status:** ✅ Completed
**Date:** 2026-02-09
**Branch:** `feature/background-queue-phase6`
**Depends on:** Phase 5 (`feature/background-queue-phase5`)

## Overview

Phase 6 enhances monitoring by adding priority visibility to the status display and task logs. Users can now see task priorities when viewing the queue, making it easier to understand execution order and diagnose priority-related issues.

**Key Feature:** Priority display in status command and structured logs.

## What Was Implemented

### 🆕 Priority Visibility Features

**1. Priority Column in Status Display**
- Added "Priority" column to `neuroflow status --pipelines`
- Shows priority values for queued/scheduled tasks
- High priority (>0) displayed in yellow
- Low priority (<0) displayed dimmed
- Normal priority (0) displayed normally
- Completed tasks show dash (-) for priority

**2. Priority in Task Logs**
- Log priority when task starts (`task.start` event)
- Log priority when task completes (`task.complete` event)
- Helps debugging priority-based scheduling issues

**3. Priority Extraction from Queue**
- `get_queue_details()` now returns priority in metadata
- Priority extracted from Huey task objects
- Defaults to 0 if priority not set

### 📝 Files Modified

**1. `neuroflow/tasks.py`** (+8 lines)

**Modified functions:**
- `get_queue_details()` - Add priority to returned metadata
  ```python
  def extract_task_metadata(task, status: str) -> dict | None:
      # Extract priority from task (default to 0 if not set)
      priority = getattr(task, "priority", 0)

      return {
          "task_id": task.id,
          "pipeline_name": pipeline_name,
          "participant_id": participant_id,
          "session_id": session_id,
          "priority": priority,  # NEW
          "status": status,
      }
  ```

- `run_pipeline_task()` - Log priority in task.start and task.complete events
  ```python
  priority = getattr(task, "priority", 0) if task else 0

  log.info(
      "task.start",
      task_id=task_id,
      pipeline=pipeline_name,
      participant=participant_id,
      session=session_id,
      priority=priority,  # NEW
  )
  ```

**2. `neuroflow/cli/status.py`** (+21 lines)

**Modified function:**
- `_show_pipelines()` - Add Priority column and display logic
  ```python
  # Add priority column
  table.add_column("Priority", justify="right")

  # Show priority for queued/scheduled tasks
  if status_val in ("queued", "scheduled"):
      priority = row.get("priority", "")
      if priority != "" and str(priority) != "nan":
          priority_val = int(priority)
          if priority_val > 0:
              priority_str = f"[yellow]{priority_val}[/yellow]"
          elif priority_val < 0:
              priority_str = f"[dim]{priority_val}[/dim]"
          else:
              priority_str = str(priority_val)
  ```

**3. `tests/test_tasks.py`** (+68 lines, 1 new test)

**New test:**
- `test_get_queue_details_with_priority` - Verify priority extraction from Huey tasks

**Updated tests:**
- All `TestGetQueueDetails` tests now verify priority in returned metadata
- Mock tasks explicitly set `mock_task.priority = N` to avoid MagicMock issues

**4. `tests/unit/test_cli_status.py`** (+136 lines, 3 new tests)

**New test class: `TestStatusPipelinesPhase6`**
- test_pipelines_show_priority_for_queued_tasks
- test_pipelines_priority_column_empty_for_completed
- test_get_queue_details_returns_priority

## Usage Examples

### Viewing Priority in Status

```bash
# Show all pipeline runs with priority column
neuroflow status --pipelines
```

**Example output:**
```
                        Pipeline Runs (4 total)
┏━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┓
┃ Particip… ┃ Session┃ Pipeline ┃ Status   ┃ Priority ┃ Duration ┃ Task ID ┃
┡━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━┩
│ sub-urgent│ ses-01 │ fmriprep │ queued   │       10 │ -        │ abc12345│
│ sub-routi…│ ses-01 │ mriqc    │ queued   │        0 │ -        │ def67890│
│ sub-bulk  │ ses-01 │ qsiprep  │ scheduled│      -10 │ -        │ ghi09876│
│ sub-001   │ ses-01 │ qsiprep  │ completed│        - │ 120.5s   │ exit: 0 │
└───────────┴────────┴──────────┴──────────┴──────────┴──────────┴─────────┘
```

**Key observations:**
- High-priority urgent task shows priority=10 (yellow)
- Normal-priority routine task shows priority=0 (normal)
- Low-priority bulk task shows priority=-10 (dim)
- Completed tasks show dash (-) for priority

### Priority in Logs

**Task start log:**
```json
{
  "event": "task.start",
  "task_id": "abc12345-...",
  "pipeline": "qsiprep",
  "participant": "sub-urgent-001",
  "session": "ses-01",
  "priority": 10,
  "timestamp": "2026-02-09T10:00:00Z"
}
```

**Task completion log:**
```json
{
  "event": "task.complete",
  "task_id": "abc12345-...",
  "pipeline": "qsiprep",
  "participant": "sub-urgent-001",
  "session": "ses-01",
  "priority": 10,
  "success": true,
  "duration": 3600.5,
  "timestamp": "2026-02-09T11:00:00Z"
}
```

## Architecture

### Priority Display Logic

```
┌─────────────────────────────────────────────┐
│ get_queue_details()                         │
│  - Query Huey pending/scheduled tasks       │
│  - Extract priority from task.priority      │
│  - Default to 0 if not set                  │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│ _show_pipelines()                           │
│  - Merge queue details with state data      │
│  - Add priority column to table             │
│  - Format priority display:                 │
│    • >0: Yellow (high)                      │
│    • <0: Dim (low)                          │
│    • =0: Normal                             │
│    • Empty: Dash (completed tasks)          │
└─────────────────────────────────────────────┘
```

### Priority Logging Flow

```
Task Enqueue (Phase 5)
  └─> .schedule(args=..., priority=N)
        └─> Huey stores priority in task object
              └─> run_pipeline_task() reads task.priority
                    ├─> Log priority at task.start
                    └─> Log priority at task.complete
```

## Testing

### Test Results

```
253 passed, 12 skipped in 2.53s
```

**New tests:** 4 priority visibility tests (all passing)
**No regressions:** All existing tests continue to pass

### Test Coverage

**TestGetQueueDetails** (6 tests, +1 new):
- ✅ test_get_queue_details_with_priority (NEW)
- ✅ All existing tests updated to verify priority field

**TestStatusPipelinesPhase6** (3 new tests):
- ✅ test_pipelines_show_priority_for_queued_tasks
- ✅ test_pipelines_priority_column_empty_for_completed
- ✅ test_get_queue_details_returns_priority

**Test strategy:**
- Mock Huey tasks with different priority values (10, 0, -10)
- Verify priority displayed correctly in status output
- Verify priority column shows dash for completed tasks
- Verify get_queue_details includes priority in metadata

### Running Tests

```bash
# Priority visibility tests only
pytest tests/test_tasks.py::TestGetQueueDetails::test_get_queue_details_with_priority -v
pytest tests/unit/test_cli_status.py::TestStatusPipelinesPhase6 -v

# Full suite
pytest tests/ -v
```

## Benefits

| Feature | Before Phase 6 | After Phase 6 |
|---------|---------------|---------------|
| **Priority visibility** | Not shown | Priority column in status |
| **Queue debugging** | Check logs manually | See priority at a glance |
| **Priority verification** | No feedback | Visual confirmation |
| **Log correlation** | Priority not logged | Priority in task events |
| **Monitoring** | Basic status | Enhanced with priority |

## Use Cases

### 1. Verifying Priority Assignment

```bash
# Enqueue with high priority
neuroflow run pipeline qsiprep sub-urgent-001 ses-01 --priority 10

# Verify it shows in queue with priority=10
neuroflow status --pipelines --filter queued
```

**Before Phase 6:**
- No way to verify priority was set
- Must check Huey database directly

**After Phase 6:**
- Immediately see priority=10 in status output
- Visual confirmation (yellow color)

### 2. Debugging Priority Issues

**Scenario:** High-priority task seems to wait behind low-priority tasks.

```bash
# Check current queue
neuroflow status --pipelines

# Review priority values to diagnose
# - Are priorities set correctly?
# - Is high-priority task actually queued?
# - Any running tasks blocking the queue?
```

### 3. Monitoring Priority Distribution

```bash
# Watch queue in real-time
neuroflow status --pipelines --watch

# Observe:
# - How many high/normal/low priority tasks?
# - Are high-priority tasks executing first?
# - Queue balance over time
```

## Known Limitations

### 1. Priority Not Persisted in State

**Issue:** Priority not stored in `pipeline_runs.csv` state.

**Impact:** Completed tasks don't show their original priority.

**Workaround:** Check logs for historical priority values.

**Future:** Add priority column to state CSV (Phase 7).

### 2. No Priority Aggregation

**Issue:** Can't see "total high-priority tasks" in summary.

**Impact:** Must count manually in detailed view.

**Workaround:** Use `--filter queued` and visually scan.

**Future:** Add priority breakdown to summary (Phase 7).

### 3. Priority Column Always Shown

**Issue:** Priority column shown even when all tasks are completed (all dashes).

**Impact:** Minor visual clutter for completed-only views.

**Workaround:** None needed.

**Future:** Conditionally hide column if all values empty (Phase 7).

## Comparison with Other Systems

### vs. Manual Queue Inspection

**Before (Phase 5):**
- Run `huey_consumer` with verbose logging
- Parse logs to find priority values
- No at-a-glance view

**After (Phase 6):**
- `neuroflow status --pipelines` shows priority instantly
- Color-coded for easy scanning
- No log parsing needed

### vs. Generic Task Queues

**Celery:** Priority not visible in default CLI tools
**RQ:** Shows priority in web UI, not CLI
**Huey + Neuroflow Phase 6:** Priority in CLI status command

## Migration from Phase 5

**Phase 5 behavior:**
```bash
neuroflow status --pipelines
# Shows: Participant, Session, Pipeline, Status, Duration, Task ID
# Priority not visible
```

**Phase 6 behavior:**
```bash
neuroflow status --pipelines
# Shows: Participant, Session, Pipeline, Status, Priority, Duration, Task ID
#        Priority column added                      ^^^^^^^^
```

**No breaking changes:** Existing commands work unchanged, just show more info.

## Next Steps

### Phase 7: Priority Enhancements

**Goal:** Persist priority in state, add priority presets.

**Features:**
- Store priority in `pipeline_runs.csv`
- Show historical priority for completed tasks
- Add priority breakdown to summary
- `default_priority` in pipeline config
- Priority profiles (clinical/research/archive)

### Phase 8: Task Timeout Configuration

**Goal:** Add timeout limits to prevent runaway tasks.

**Features:**
- `timeout` parameter in pipeline config
- Timeout enforcement by worker
- Timeout exceeded alerts
- Graceful task termination

### Phase 9: Advanced Queue Management

**Goal:** Multiple queues and worker pools.

**Features:**
- Separate queues for different pipeline types
- Worker pools with queue affinity
- Queue-specific priorities
- Cross-queue load balancing

## References

- **Phase 1 Summary:** [phase1-summary.md](phase1-summary.md)
- **Phase 2 Summary:** [phase2-summary.md](phase2-summary.md)
- **Phase 3 Summary:** [phase3-summary.md](phase3-summary.md)
- **Phase 4 Summary:** [phase4-summary.md](phase4-summary.md)
- **Phase 5 Summary:** [phase5-summary.md](phase5-summary.md)
- **Implementation Plan:** [background-runner-migration.md](background-runner-migration.md)
- **User Guide:** [../background-queue.md](../background-queue.md)
- **Branch:** `feature/background-queue-phase6`
- **Huey Documentation:** https://huey.readthedocs.io/en/latest/
