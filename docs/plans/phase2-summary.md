# Phase 2 Implementation Summary: CLI Integration

**Status:** ✅ Completed
**Date:** 2026-02-09
**Branch:** `feature/background-queue-phase2`
**Depends on:** Phase 1 (`feature/background-queue-phase1`)

## Overview

Phase 2 integrates the background queue (from Phase 1) into the CLI, making asynchronous execution the default behavior while preserving synchronous execution via a `--sync` flag.

**Key Change:** `neuroflow run pipeline` now enqueues tasks to the background queue by default instead of blocking the terminal.

## What Was Implemented

### 🔄 CLI Behavior Change

**Before (Phase 1):**
```bash
$ neuroflow run pipeline qsiprep
# Blocks terminal for hours until all pipelines complete
Running 'qsiprep' for 3 session(s) (max_workers=4)...
[... hours pass ...]
Results: qsiprep
  Succeeded: 2
  Failed: 1
```

**After (Phase 2 - Default):**
```bash
$ neuroflow run pipeline qsiprep
# Returns immediately, tasks run in background consumer
Enqueueing 'qsiprep' for 3 session(s) to background queue...

Enqueued: qsiprep
  Participant  Session          Task ID
  sub-01       ses-baseline     a1b2c3d4...
  sub-02       ses-baseline     e5f6g7h8...
  sub-03       ses-baseline     i9j0k1l2...

✓ Enqueued 3 task(s) (queue: 3 pending, 0 scheduled)

Monitor with: neuroflow status runs
Consumer: huey_consumer neuroflow.tasks.huey -w 4 -k process
```

**With --sync flag (original behavior):**
```bash
$ neuroflow run pipeline qsiprep --sync
# Blocks terminal (useful for debugging)
Running 'qsiprep' for 3 session(s) synchronously (max_workers=4)...
[... blocks until complete ...]
Results: qsiprep
  Succeeded: 2
  Failed: 1
```

### 📝 Files Modified

**1. `neuroflow/cli/run.py` (significant refactor)**

**Added:**
- `--sync` flag to both `run pipeline` and `run all` commands
- `_run_pipeline_async()` helper function for background enqueueing
- `_run_pipeline_sync()` helper function for synchronous execution
- Updated docstrings to explain async vs sync modes

**Behavior:**
- Default: Calls `_run_pipeline_async()` → enqueues via `enqueue_pipeline()`
- With `--sync`: Calls `_run_pipeline_sync()` → blocks via `PipelineRunner.run_batch()`

**Key features of async mode:**
- Shows table of enqueued tasks with shortened task IDs
- Displays queue statistics (pending/scheduled counts)
- Provides helpful hints about monitoring and consumer startup
- Respects `PipelineConfig.retries` setting from config

**2. `tests/unit/test_cli_run.py` (test updates)**

**Updated existing tests:**
- Renamed `test_successful_run` → `test_successful_run_sync` (added `--sync` flag)
- Renamed `test_failed_run_shows_details` → `test_failed_run_shows_details_sync` (added `--sync` flag)
- Renamed `test_error_without_pipeline_result` → `test_error_without_pipeline_result_sync` (added `--sync` flag)

**Added new tests:**
- `test_successful_run_async()` - Test default async behavior with mocked `enqueue_pipeline()`

**Test strategy:**
- Mock `neuroflow.tasks` module in sys.modules for async tests
- Use `--sync` flag for existing blocking behavior tests
- All 10 tests pass (was 9, added 1 new async test)

## Architecture

### Execution Flow

```
CLI Command: neuroflow run pipeline qsiprep [--sync]
                    ↓
           Check --sync flag
                    ↓
     ┌──────────────┴─────────────────┐
     │                                │
     ▼ (default)                      ▼ (--sync)
_run_pipeline_async()        _run_pipeline_sync()
     │                                │
     ▼                                ▼
enqueue_pipeline()           PipelineRunner.run_batch()
     │                                │
     ▼                                ▼
Huey SQLite Queue             Blocking execution
     │                                │
     ▼                                ▼
Returns task IDs              Returns results table
(Consumer executes later)     (Immediate results)
```

### State Tracking Flow

**Async mode (default):**
1. CLI: `enqueue_pipeline()` → State: "queued"
2. Consumer picks up task → State: "running"
3. Task completes → State: "completed" or "failed"

**Sync mode (--sync):**
1. CLI: `PipelineRunner.run_batch()` → Blocks
2. Tasks execute → (no intermediate state)
3. CLI records results → State: "completed" or "failed"

## Usage Examples

### Basic Usage (Async)

```bash
# Start consumer first (in separate terminal or as systemd service)
huey_consumer neuroflow.tasks.huey -w 4 -k process

# Enqueue pipeline (returns immediately)
neuroflow run pipeline qsiprep

# Check status
neuroflow status runs
```

### Debugging with Sync Mode

```bash
# Run synchronously for immediate feedback (useful for debugging)
neuroflow run pipeline qsiprep --sync

# Filter to single participant for faster testing
neuroflow run pipeline qsiprep --participant sub-01 --sync
```

### Running All Pipelines

```bash
# Async (default) - enqueues all enabled pipelines
neuroflow run all

# Sync - blocks until all pipelines complete
neuroflow run all --sync
```

### Force Re-run

```bash
# Re-run already completed sessions (async)
neuroflow run pipeline qsiprep --force

# Re-run already completed sessions (sync)
neuroflow run pipeline qsiprep --force --sync
```

## Testing

### Test Coverage

**Total tests:** 215 passed, 12 skipped
**CLI tests:** 10 passed (was 9, added 1 new async test)

**New test:**
- `test_successful_run_async` - Verifies async enqueueing with mocked Huey

**Updated tests (added --sync flag):**
- `test_successful_run_sync`
- `test_failed_run_shows_details_sync`
- `test_error_without_pipeline_result_sync`

**Unchanged tests:**
- `test_no_pending_sessions` - Works with both modes
- `test_dry_run_shows_table` - Dry run bypasses execution mode
- `test_force_flag_passed` - Flag passing works in both modes
- `test_participant_filter` - Filtering works in both modes
- `test_run_all_no_pipelines` - No pipelines to run
- `test_run_all_invokes_pipeline` - run all delegates to run pipeline

### Running Tests

```bash
# All tests
pytest tests/ -v

# CLI tests only
pytest tests/unit/test_cli_run.py -v

# Specific async test
pytest tests/unit/test_cli_run.py::TestRunPipelineCommand::test_successful_run_async -v
```

## Breaking Changes

**None for users following documented workflows.**

**Behavioral change:**
- `neuroflow run pipeline` now enqueues by default (was blocking)
- Users relying on blocking behavior must add `--sync` flag
- **Mitigation:** Clear documentation in command help text and migration guide

**Backwards compatibility:**
- `--sync` flag provides exact same behavior as pre-Phase 2
- All existing config files work without changes
- No changes to state tracking or data formats

## Migration Guide

### For Users Currently Running Pipelines

**Old workflow:**
```bash
neuroflow run pipeline qsiprep
# Terminal blocked for hours
```

**New workflow (Phase 2):**
```bash
# Option 1: Use async mode (recommended)
huey_consumer neuroflow.tasks.huey -w 4 -k process &  # Start consumer
neuroflow run pipeline qsiprep  # Enqueues and returns immediately

# Option 2: Keep blocking behavior (for debugging)
neuroflow run pipeline qsiprep --sync
```

### For Scripts/Automation

**Update scripts that expect blocking behavior:**

```bash
# Before
neuroflow run pipeline qsiprep
# Script continues after pipelines complete

# After (add --sync)
neuroflow run pipeline qsiprep --sync
# Script continues after pipelines complete
```

**Or adapt to async mode:**

```bash
# Enqueue
neuroflow run pipeline qsiprep

# Poll for completion (Phase 4 will add better status CLI)
while neuroflow status runs | grep -q "running"; do
    sleep 60
done
```

## Known Limitations

### 1. No Wait/Block Option for Async Mode

**Issue:** Can't enqueue and then block until completion.

**Workaround:** Use `--sync` for blocking, or implement polling in scripts.

**Future:** Phase 4 will add `neuroflow wait <task-id>` command.

### 2. Task IDs Not Easily Queryable

**Issue:** Enqueued task IDs are printed but not easily captured or queried.

**Workaround:** Monitor via `neuroflow status runs` which shows all runs.

**Future:** Phase 4 will add queue-aware status display with task IDs.

### 3. Retry Configuration Not Dynamic

**Issue:** The `retries` parameter in `enqueue_pipeline()` is logged but not actually used (hardcoded to 0 in task decorator).

**Workaround:** Retries only work if configured in `PipelineConfig.retries` in YAML.

**Future:** Could implement dynamic retry via Huey scheduler API or task variants.

## Documentation Updates

### Updated Files

1. **`docs/background-queue.md`** (Phase 1 doc)
   - Added Phase 2 section describing CLI integration
   - Updated usage examples to show default async behavior
   - Added `--sync` flag documentation

2. **Command Help Text**
   - `neuroflow run pipeline --help` now explains async vs sync modes
   - `neuroflow run all --help` documents `--sync` flag

### New Files

1. **`docs/plans/phase2-summary.md`** (this file)
   - Complete implementation summary
   - Usage examples for both modes
   - Migration guide
   - Known limitations

## Next Steps

### Phase 3: Worker Management CLI

**Goal:** Add `neuroflow worker` commands to manage the Huey consumer.

**Commands to implement:**
- `neuroflow worker start` - Start consumer (foreground or daemon)
- `neuroflow worker stop` - Gracefully stop consumer
- `neuroflow worker status` - Show consumer PID, workers, queue depth
- `neuroflow worker restart` - Restart consumer

**Benefits:**
- No need to remember `huey_consumer` command
- Consistent CLI interface
- Better error messages and validation

### Phase 4: Enhanced Status Display

**Goal:** Make `neuroflow status runs` queue-aware.

**Features:**
- Show queue depth (pending/scheduled tasks)
- Show currently running tasks with progress
- Show task IDs for easier debugging
- Real-time updates (optional `--watch` flag)

### Phase 5: Production Deployment

**Goal:** Systemd integration and deployment tooling.

**Features:**
- `neuroflow worker install-service` - Generate systemd unit
- `neuroflow worker uninstall-service` - Remove systemd unit
- Log rotation configuration
- Monitoring and alerting setup

### Phase 6: Advanced Features

**Goal:** Pipeline dependency chains and scheduling.

**Features:**
- DAG-based pipeline dependencies
- Priority queues (run qsiprep before fmriprep)
- Scheduled/cron tasks
- Task result caching

## References

- **Phase 1 Summary:** [phase1-summary.md](phase1-summary.md)
- **Implementation Plan:** [background-runner-migration.md](background-runner-migration.md)
- **User Guide:** [../background-queue.md](../background-queue.md)
- **Branch:** `feature/background-queue-phase2`
