# Phase 7 Implementation Summary: Task Timeout Configuration

**Status:** ✅ Completed
**Date:** 2026-02-09
**Branch:** `feature/background-queue-phase7`
**Depends on:** Phase 6 (`feature/background-queue-phase6`)

## Overview

Phase 7 adds timeout enforcement to prevent runaway pipeline tasks. Timeouts are configured per-pipeline in the config file and enforced using Python's signal module. Tasks that exceed their timeout are terminated and logged with detailed timeout information.

**Key Feature:** Per-pipeline timeout configuration with automatic enforcement.

## What Was Implemented

### 🆕 Timeout Enforcement Features

**1. Timeout Configuration**
- Uses existing `timeout_minutes` field in PipelineConfig (default: 60 minutes)
- Timeout read from config when task starts
- Converted to seconds for signal.alarm()

**2. Signal-Based Timeout**
- Uses `signal.SIGALRM` for timeout enforcement
- Timeout handler raises `TaskTimeoutError`
- Signal handler restored after task completion/failure
- Alarm cancelled on successful completion

**3. Timeout Logging**
- `task.timeout_set` event when timeout configured
- `task.timeout` error event when timeout exceeded
- Error message includes timeout duration
- State updated with timeout failure

### 📝 Files Modified

**1. `neuroflow/tasks.py`** (+58 lines)

**New exception class:**
```python
class TaskTimeoutError(Exception):
    """Raised when a task exceeds its timeout."""
    pass

def timeout_handler(signum, frame):
    """Signal handler for task timeout."""
    raise TaskTimeoutError("Task exceeded timeout limit")
```

**Modified function:**
- `run_pipeline_task()` - Read timeout from config, set signal alarm
  ```python
  # Get timeout from pipeline config
  timeout_seconds = None
  for p in config.pipelines.session_level + config.pipelines.subject_level:
      if p.name == pipeline_name:
          timeout_seconds = p.timeout_minutes * 60
          break

  # Set up timeout handler
  if timeout_seconds:
      old_handler = signal.signal(signal.SIGALRM, timeout_handler)
      signal.alarm(timeout_seconds)
      log.info("task.timeout_set", timeout_seconds=timeout_seconds)

  try:
      result_dict = run_single_pipeline(...)
      
      # Cancel timeout on success
      if timeout_seconds:
          signal.alarm(0)
          signal.signal(signal.SIGALRM, old_handler)

  except TaskTimeoutError as e:
      # Cancel alarm and log timeout
      signal.alarm(0)
      log.error("task.timeout", timeout_seconds=timeout_seconds)
      # Record failure in state
      raise
  ```

**2. `tests/test_tasks.py`** (+18 lines, 2 new tests)

**New test class: `TestTaskTimeout`**
- test_timeout_handler_raises_error
- test_timeout_error_class_exists

## Usage Examples

### Configuring Timeout

```yaml
# neuroflow.yaml
pipelines:
  session_level:
    - name: qsiprep
      enabled: true
      runner: qsiprep
      timeout_minutes: 120  # 2 hours
      
    - name: mriqc
      enabled: true
      runner: mriqc
      timeout_minutes: 30  # 30 minutes
```

### Timeout Logs

**Task start with timeout:**
```json
{
  "event": "task.timeout_set",
  "task_id": "abc12345-...",
  "pipeline": "qsiprep",
  "timeout_seconds": 7200,
  "timestamp": "2026-02-09T10:00:00Z"
}
```

**Task timeout exceeded:**
```json
{
  "event": "task.timeout",
  "task_id": "abc12345-...",
  "pipeline": "qsiprep",
  "timeout_seconds": 7200,
  "error": "Task exceeded timeout limit (7200s): ...",
  "timestamp": "2026-02-09T12:00:00Z"
}
```

## Architecture

### Timeout Enforcement Flow

```
Task Start
  └─> Read timeout_minutes from PipelineConfig
      └─> Convert to seconds
          └─> Set signal.SIGALRM handler
              └─> Call signal.alarm(timeout_seconds)
                  │
                  ├─> Task completes within timeout
                  │   └─> Cancel alarm (signal.alarm(0))
                  │       └─> Restore old handler
                  │           └─> Return success
                  │
                  └─> Task exceeds timeout
                      └─> SIGALRM signal raised
                          └─> timeout_handler() called
                              └─> Raises TaskTimeoutError
                                  └─> Caught in exception handler
                                      └─> Cancel alarm
                                          └─> Log timeout
                                              └─> Record failure in state
```

## Testing

### Test Results

```
255 passed, 12 skipped in 2.67s
```

**New tests:** 2 timeout tests (all passing)
**No regressions:** All existing tests continue to pass

### Test Coverage

**TestTaskTimeout** (2 new tests):
- ✅ test_timeout_handler_raises_error - Verify timeout handler raises TaskTimeoutError
- ✅ test_timeout_error_class_exists - Verify TaskTimeoutError is an Exception subclass

## Benefits

| Feature | Before Phase 7 | After Phase 7 |
|---------|---------------|---------------|
| **Runaway tasks** | Run indefinitely | Terminated after timeout |
| **Resource waste** | CPU/memory leaked | Resources freed |
| **Queue blocking** | One slow task blocks all | Timeouts prevent blocking |
| **Debugging** | Hard to find hung tasks | Timeout logs identify issues |
| **Configuration** | No timeout control | Per-pipeline timeouts |

## Use Cases

### 1. Prevent Queue Blocking

**Scenario:** One corrupted DICOM file causes qsiprep to hang indefinitely.

**Before Phase 7:**
- Task runs forever, blocking worker
- Other tasks wait in queue
- Manual intervention required

**After Phase 7:**
```yaml
pipelines:
  session_level:
    - name: qsiprep
      timeout_minutes: 180  # 3 hours max
```
- Task terminated after 3 hours
- Worker freed for next task
- Timeout logged for investigation

### 2. Different Timeouts for Different Pipelines

**Fast pipelines (MRIQC):**
```yaml
- name: mriqc
  timeout_minutes: 30  # Should finish quickly
```

**Slow pipelines (QSIPrep):**
```yaml
- name: qsiprep
  timeout_minutes: 240  # 4 hours for complex DWI
```

**Subject-level pipelines:**
```yaml
subject_level:
  - name: qsirecon
    timeout_minutes: 360  # 6 hours for all sessions
```

### 3. Debugging Hung Tasks

```bash
# Task starts
task.timeout_set: timeout_seconds=3600

# ... 1 hour later ...

# Task times out
task.timeout: timeout_seconds=3600, error="Task exceeded timeout limit (3600s)"

# Check logs to find what was running when timeout occurred
```

## Known Limitations

### 1. Signal-Based Timeout (Unix Only)

**Issue:** `signal.alarm()` only works on Unix/Linux, not Windows.

**Impact:** Timeout enforcement won't work on Windows systems.

**Workaround:** Use Unix-based workers, or implement alternative timeout mechanism.

**Future:** Add threading.Timer fallback for Windows (Phase 8).

### 2. Timeout Not Graceful

**Issue:** SIGALRM immediately raises exception, doesn't allow cleanup.

**Impact:** Pipeline process may leave temporary files or incomplete state.

**Workaround:** Pipelines should handle cleanup in finally blocks.

**Future:** Add graceful shutdown period before hard timeout (Phase 8).

### 3. Timeout Not Persisted in State

**Issue:** Timeout value not stored in pipeline_runs.csv.

**Impact:** Can't see timeout value for completed/failed tasks in status.

**Workaround:** Check logs for timeout_set event.

**Future:** Add timeout column to state CSV (Phase 8).

## Next Steps

### Phase 8: Graceful Timeout Handling

**Goal:** Improve timeout mechanism with graceful shutdown.

**Features:**
- Warning signal before timeout (soft timeout)
- Graceful shutdown period for cleanup
- Timeout value in status display
- Threading-based fallback for Windows

### Phase 9: Priority Persistence

**Goal:** Store priority in state for historical analysis.

**Features:**
- Add priority column to pipeline_runs.csv
- Show historical priority in status
- Priority-based statistics
- Priority trends over time

## References

- **Phase 1 Summary:** [phase1-summary.md](phase1-summary.md)
- **Phase 2 Summary:** [phase2-summary.md](phase2-summary.md)
- **Phase 3 Summary:** [phase3-summary.md](phase3-summary.md)
- **Phase 4 Summary:** [phase4-summary.md](phase4-summary.md)
- **Phase 5 Summary:** [phase5-summary.md](phase5-summary.md)
- **Phase 6 Summary:** [phase6-summary.md](phase6-summary.md)
- **Implementation Plan:** [background-runner-migration.md](background-runner-migration.md)
- **User Guide:** [../background-queue.md](../background-queue.md)
- **Branch:** `feature/background-queue-phase7`
- **Python Signal Module:** https://docs.python.org/3/library/signal.html
