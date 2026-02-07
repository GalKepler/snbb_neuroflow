# How to View Pipeline Logs

## Quick Answer

Failed pipeline logs are stored in multiple places:

1. **Database** - Error messages and basic info
2. **Work directory** - Full execution logs
3. **Command output** - When running manually

## Method 1: Check Failed Runs in Database

### Using CLI (Easiest)

```bash
# Show overall status
neuroflow status

# Show only failed sessions
neuroflow status --sessions --failed

# Show specific subject
neuroflow status --sessions --subject sub-001
```

### Using Python Script

```python
from neuroflow.config import NeuroflowConfig
from neuroflow.core.state import StateManager
from neuroflow.models import PipelineRun, PipelineRunStatus
from sqlalchemy import select

config = NeuroflowConfig.find_and_load()
state = StateManager(config)

# Get all failed pipeline runs
with state.get_session() as db:
    failed_runs = db.execute(
        select(PipelineRun)
        .where(PipelineRun.status == PipelineRunStatus.FAILED)
        .order_by(PipelineRun.created_at.desc())
    ).scalars().all()

    for run in failed_runs:
        print(f"\n{'='*60}")
        print(f"Pipeline: {run.pipeline_name}")
        print(f"Run ID: {run.id}")
        print(f"Session ID: {run.session_id}")
        print(f"Exit Code: {run.exit_code}")
        print(f"Started: {run.started_at}")
        print(f"Duration: {run.duration_seconds}s")
        print(f"\nError Message:")
        print(run.error_message or "No error message recorded")

        if run.log_path:
            print(f"\nLog File: {run.log_path}")
```

## Method 2: Check Log Files

### Default Log Location

Logs are stored in your configured `log_dir` (default: `/var/log/neuroflow`):

```bash
# Check your log directory
grep log_dir neuroflow.yaml

# List log files
ls -lth /var/log/neuroflow/  # Default location
# or
ls -lth /media/storage/yalab-dev/snbb_neuroflow/.neuroflow/logs/
```

### VoxelOps Execution Logs

VoxelOps stores detailed logs in the work directory:

```bash
# Check work directory from config
grep work_dir neuroflow.yaml

# Example: /media/storage/yalab-dev/snbb_neuroflow/.neuroflow

# Pipeline-specific logs
ls -lth <work_dir>/qsiprep/*/log/
ls -lth <work_dir>/qsirecon/*/log/
```

### Log File Structure

```
work_dir/
├── qsiprep/
│   └── sub-001_ses-01/
│       ├── log/
│       │   ├── qsiprep.log          # Main QSIPrep log
│       │   └── command.txt          # Command that was run
│       └── work/                    # Intermediate files
├── qsirecon/
│   └── sub-001_ses-01/
│       └── log/
│           └── qsirecon.log
└── logs/                            # General neuroflow logs
    ├── neuroflow.log
    └── celery/
        ├── worker.log
        └── beat.log
```

## Method 3: View Logs During Execution

When running pipelines manually, logs are shown in real-time:

```bash
python examples/voxelops/03_complete_workflow.py \
  --session-id 1 \
  2>&1 | tee pipeline_run.log
```

This will:
- Show logs in your terminal
- Save to `pipeline_run.log` file

## Method 4: Query Specific Pipeline Run

If you know the run ID:

```python
from neuroflow.config import NeuroflowConfig
from neuroflow.core.state import StateManager
from neuroflow.models import PipelineRun

config = NeuroflowConfig.find_and_load()
state = StateManager(config)

run_id = 123  # Your run ID

with state.get_session() as db:
    run = db.get(PipelineRun, run_id)

    if run:
        print(f"Pipeline: {run.pipeline_name}")
        print(f"Status: {run.status.value}")
        print(f"Session: {run.session_id}")
        print(f"\nError Message:")
        print(run.error_message or "No error")

        if run.error_traceback:
            print(f"\nTraceback:")
            print(run.error_traceback)

        if run.log_path:
            print(f"\nFull logs at: {run.log_path}")

            # Read the log file
            with open(run.log_path) as f:
                print("\nLast 50 lines:")
                lines = f.readlines()
                for line in lines[-50:]:
                    print(line.rstrip())
```

## Method 5: Create a Log Viewer Script

Save this as `view_logs.py`:

```python
#!/usr/bin/env python3
"""View logs for failed pipeline runs."""

import sys
from pathlib import Path

from neuroflow.config import NeuroflowConfig
from neuroflow.core.state import StateManager
from neuroflow.models import PipelineRun, PipelineRunStatus
from sqlalchemy import select

def main():
    config = NeuroflowConfig.find_and_load()
    state = StateManager(config)

    # Get recent failed runs
    with state.get_session() as db:
        failed_runs = db.execute(
            select(PipelineRun)
            .where(PipelineRun.status == PipelineRunStatus.FAILED)
            .order_by(PipelineRun.created_at.desc())
            .limit(10)
        ).scalars().all()

        if not failed_runs:
            print("No failed runs found!")
            return

        print(f"\nFound {len(failed_runs)} recent failed runs:\n")

        for i, run in enumerate(failed_runs, 1):
            print(f"{i}. Run #{run.id} - {run.pipeline_name}")
            print(f"   Session: {run.session_id}")
            print(f"   Failed: {run.completed_at}")

    # Let user select which to view
    choice = input("\nEnter number to view details (or 'q' to quit): ")

    if choice.lower() == 'q':
        return

    try:
        idx = int(choice) - 1
        run = failed_runs[idx]
    except (ValueError, IndexError):
        print("Invalid choice")
        return

    # Show detailed info
    print(f"\n{'='*70}")
    print(f"Pipeline Run #{run.id}")
    print(f"{'='*70}")
    print(f"Pipeline: {run.pipeline_name}")
    print(f"Level: {run.pipeline_level}")
    print(f"Session ID: {run.session_id}")
    print(f"Subject ID: {run.subject_id}")
    print(f"Status: {run.status.value}")
    print(f"Exit Code: {run.exit_code}")
    print(f"Attempt: {run.attempt_number}")

    if run.started_at:
        print(f"Started: {run.started_at}")
    if run.completed_at:
        print(f"Completed: {run.completed_at}")
    if run.duration_seconds:
        print(f"Duration: {run.duration_seconds:.1f}s ({run.duration_seconds/60:.1f} min)")

    print(f"\n{'-'*70}")
    print("ERROR MESSAGE:")
    print(f"{'-'*70}")
    print(run.error_message or "No error message recorded")

    if run.error_traceback:
        print(f"\n{'-'*70}")
        print("TRACEBACK:")
        print(f"{'-'*70}")
        print(run.error_traceback)

    if run.log_path and Path(run.log_path).exists():
        print(f"\n{'-'*70}")
        print(f"LOG FILE: {run.log_path}")
        print(f"{'-'*70}")

        view = input("\nView full log file? [y/N]: ")
        if view.lower() == 'y':
            with open(run.log_path) as f:
                print(f.read())
    elif run.log_path:
        print(f"\nLog file not found: {run.log_path}")
    else:
        print("\nNo log file path recorded")

if __name__ == "__main__":
    main()
```

Then use it:
```bash
chmod +x view_logs.py
python view_logs.py
```

## Common Log Locations

### Your Configuration

Based on your `neuroflow.yaml`:

```yaml
paths:
  work_dir: /media/storage/yalab-dev/snbb_neuroflow/.neuroflow
  log_dir: /var/log/neuroflow  # May not be writable
```

### Actual Log Locations

1. **Pipeline execution logs**: `work_dir/<pipeline>/<subject>_<session>/log/`
2. **Neuroflow system logs**: `log_dir/neuroflow.log`
3. **Celery logs**: `log_dir/celery/`
4. **Database error messages**: Query via Python/CLI

### Check Permissions

```bash
# Check if log_dir is writable
ls -ld /var/log/neuroflow
# If not, update neuroflow.yaml:
#   log_dir: /media/storage/yalab-dev/snbb_neuroflow/.neuroflow/logs
```

## Tips for Debugging Failed Runs

### 1. Start with the error message
```bash
neuroflow status --sessions --failed
```

### 2. Check the pipeline-specific logs
```bash
# For QSIPrep failure
find /media/storage/yalab-dev/snbb_neuroflow/.neuroflow/qsiprep \
  -name "*.log" -exec tail -50 {} \;
```

### 3. Look for common issues

**Memory errors:**
```bash
grep -i "memory\|killed" work_dir/*/log/*.log
```

**Missing files:**
```bash
grep -i "no such file\|not found" work_dir/*/log/*.log
```

**Permission errors:**
```bash
grep -i "permission denied" work_dir/*/log/*.log
```

### 4. Check container logs
```bash
# If using Docker/Apptainer
docker logs <container_id>
# or
apptainer logs <instance>
```

## Get Help With Specific Errors

If you share:
1. The pipeline name
2. The error message
3. The last 50 lines of the log file

I can help diagnose the issue!

## Summary

| Method | Speed | Detail | Use Case |
|--------|-------|--------|----------|
| `neuroflow status --failed` | ⚡ Fast | Low | Quick overview |
| Query database | ⚡ Fast | Medium | Error messages |
| Read log files | 🐌 Slow | High | Full debugging |
| `view_logs.py` script | ⚡ Fast | High | Interactive debugging |

**Most Common:**
1. Run `neuroflow status --sessions --failed`
2. Find the failed session
3. Look at work_dir logs: `<work_dir>/<pipeline>/sub-*/log/*.log`
