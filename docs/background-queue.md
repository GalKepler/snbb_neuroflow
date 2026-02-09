# Background Queue with Huey

> **Status:** Phases 1 & 2 Implemented - CLI Integration Complete
> **Date:** 2026-02-09
> **Phases:** 1 (Infrastructure) + 2 (CLI Integration)

Neuroflow uses [Huey](https://github.com/coleifer/huey) with a SQLite backend for background pipeline execution. This allows pipelines to run in the background without blocking the terminal, with persistent queue state that survives crashes.

**As of Phase 2:** The CLI (`neuroflow run pipeline`) now enqueues tasks to the background queue by default. Use `--sync` for the old blocking behavior.

## Quick Start

### 1. Install Dependencies

Huey is automatically installed with neuroflow:

```bash
pip install neuroflow
```

### 2. Start the Huey Consumer

The consumer is a long-running process that pulls tasks from the queue and executes them:

```bash
# Start with 4 parallel workers using process-based execution
huey_consumer neuroflow.tasks.huey -w 4 -k process -l logs/huey.log
```

**Key options:**
- `-w N` or `--workers N`: Number of parallel workers (default: 1)
- `-k process`: Use process-based workers (avoids GIL, recommended for CPU-bound pipelines)
- `-k thread`: Use thread-based workers (lighter weight, but affected by GIL)
- `-l FILE`: Log file path
- `-v` or `--verbose`: Verbose logging

For production, run the consumer as a systemd service (see [Production Deployment](#production-deployment) below).

### 3. Run Pipelines

**Option A: CLI (Phase 2 - Recommended)**

```bash
# Async mode (default) - enqueues and returns immediately
neuroflow run pipeline qsiprep

# Sync mode - blocks terminal until complete (useful for debugging)
neuroflow run pipeline qsiprep --sync
```

**Option B: Python API (Phase 1)**

```python
from neuroflow.tasks import enqueue_pipeline

task_id = enqueue_pipeline(
    config_path="/etc/neuroflow/neuroflow.yaml",
    participant_id="sub-01",
    session_id="ses-baseline",
    dicom_path="/data/dicom/sub-01/ses-baseline",
    pipeline_name="qsiprep",
    log_dir="/var/log/neuroflow",
    force=False,
    retries=0,
)

print(f"Enqueued task: {task_id}")
```

Both methods return immediately and tasks execute in the background consumer.

### 4. Monitor Tasks

Task state is tracked in `SessionState` (CSV files):

```python
from neuroflow.state import SessionState
from neuroflow.config import NeuroflowConfig

config = NeuroflowConfig.from_yaml("/etc/neuroflow/neuroflow.yaml")
state = SessionState(config.execution.state_dir)

# Get all pipeline runs
runs = state.load_pipeline_runs()
print(runs[runs["status"] == "running"])
```

Or use the CLI:

```bash
neuroflow status runs
```

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────┐
│ CLI / Application Code                                      │
│   enqueue_pipeline() → Returns immediately with task ID     │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ Huey Queue (SQLite database: .neuroflow/huey.db)           │
│   - Persistent task queue                                   │
│   - Survives crashes and restarts                           │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ Huey Consumer Process (huey_consumer)                       │
│   - Pulls tasks from queue                                  │
│   - Executes run_pipeline_task() in parallel workers        │
│   - Updates SessionState with status                        │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ run_single_pipeline() → Calls VoxelOps adapter              │
│   - Executes neuroimaging pipeline (qsiprep, fmriprep, etc) │
│   - Logs to per-session log file                            │
│   - Returns result dict                                      │
└─────────────────────────────────────────────────────────────┘
```

### Task Lifecycle

1. **Queued**: Task is added to the SQLite queue by `enqueue_pipeline()`
2. **Running**: Consumer picks up the task and begins execution
3. **Completed**: Task finishes successfully
4. **Failed**: Task fails (exit code != 0 or exception)

State transitions are recorded in `SessionState.record_pipeline_run()` and stored in `pipeline_runs.csv`.

### State Tracking

Neuroflow uses a hybrid state model:

- **Huey SQLite database** (`.neuroflow/huey.db`): Transient task queue state
- **SessionState CSV files** (`.neuroflow/pipeline_runs.csv`): Authoritative state-of-record

The CSV files are the **single source of truth**. Huey's database is just the transport queue. This design allows:
- Querying historical runs even after the task is dequeued from Huey
- Decoupling task execution from state persistence
- Using existing SessionState APIs without depending on Huey internals

## API Reference

### `enqueue_pipeline()`

Enqueue a pipeline run for background execution.

```python
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
```

**Parameters:**
- `config_path`: Path to neuroflow YAML configuration
- `participant_id`: Participant ID (with or without `sub-` prefix)
- `session_id`: Session ID (with or without `ses-` prefix)
- `dicom_path`: Path to DICOM directory for this session
- `pipeline_name`: Pipeline to run (e.g., `"qsiprep"`, `"fmriprep"`)
- `log_dir`: Directory for session-specific log files
- `force`: If True, re-run even if already completed (default: `False`)
- `retries`: Number of retry attempts on failure (default: `0`)

**Returns:**
- Task ID (UUID string)

### `configure_huey()`

Configure the Huey instance with a custom state directory.

```python
def configure_huey(state_dir: str | Path) -> None:
```

This is typically called automatically when loading the config. Explicitly call it if you need to change the Huey database location at runtime.

### `get_queue_stats()`

Get statistics about the current queue state.

```python
def get_queue_stats() -> dict:
```

**Returns:**
```python
{
    "pending": 5,      # Tasks waiting to run
    "scheduled": 2,    # Tasks scheduled for future execution
}
```

## Production Deployment

### Systemd Service

Create `/etc/systemd/system/neuroflow-worker.service`:

```ini
[Unit]
Description=Neuroflow Pipeline Worker
After=network.target

[Service]
Type=simple
User=neuroflow
Group=neuroflow
WorkingDirectory=/opt/neuroflow
Environment="PATH=/opt/neuroflow/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/opt/neuroflow/venv/bin/huey_consumer neuroflow.tasks.huey -w 4 -k process -l /var/log/neuroflow/huey.log
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Resource limits
LimitNOFILE=65536
Nice=10

[Install]
WantedBy=multi-user.target
```

**Enable and start:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable neuroflow-worker
sudo systemctl start neuroflow-worker
sudo systemctl status neuroflow-worker
```

**View logs:**

```bash
sudo journalctl -u neuroflow-worker -f
```

### Monitoring

Monitor the consumer process:

```bash
# Check if consumer is running
ps aux | grep huey_consumer

# View queue stats
python -c "from neuroflow.tasks import get_queue_stats; print(get_queue_stats())"

# Check pipeline run status
neuroflow status runs
```

### Resource Configuration

Adjust worker count based on available resources:

```bash
# For 16-core machine with memory-intensive pipelines:
huey_consumer neuroflow.tasks.huey -w 4 -k process

# For 64-core machine with lighter pipelines:
huey_consumer neuroflow.tasks.huey -w 16 -k process
```

**Rule of thumb:**
- qsiprep/fmriprep: 1 worker per 4-8 GB RAM, max workers = cores / 4
- Lighter pipelines: 1 worker per 2 GB RAM, max workers = cores / 2

## Troubleshooting

### Consumer Not Processing Tasks

**Symptoms:** Tasks are enqueued but never run.

**Diagnosis:**
1. Check if consumer is running: `ps aux | grep huey_consumer`
2. Check consumer logs for errors
3. Verify Huey database exists: `ls -lh .neuroflow/huey.db`

**Solution:**
```bash
# Restart consumer
sudo systemctl restart neuroflow-worker

# Or manually:
huey_consumer neuroflow.tasks.huey -w 4 -k process -l logs/huey.log
```

### Tasks Stuck in "Running" State

**Symptoms:** `pipeline_runs.csv` shows `status=running` but task isn't executing.

**Diagnosis:**
- Task may have crashed without updating state
- Consumer may have been killed mid-execution

**Solution:**
```python
from neuroflow.state import SessionState
from neuroflow.config import NeuroflowConfig

config = NeuroflowConfig.from_yaml("neuroflow.yaml")
state = SessionState(config.execution.state_dir)

# Find stuck tasks
runs = state.load_pipeline_runs()
stuck = runs[runs["status"] == "running"]
print(stuck[["participant_id", "session_id", "pipeline_name", "start_time"]])

# Manually update stuck tasks (use with caution):
# state.record_pipeline_run(
#     participant_id="sub-01",
#     session_id="ses-baseline",
#     pipeline_name="qsiprep",
#     status="failed",
#     error_message="Consumer crashed, manually marked as failed",
# )
```

### SQLite Database Locked

**Symptoms:** `sqlite3.OperationalError: database is locked`

**Cause:** Multiple consumers trying to write to the same database, or SQLite busy timeout too low.

**Solution:**
- Only run **one consumer process** per Huey database
- If you need multiple consumers, use separate state directories
- Huey's SQLite storage uses a default busy timeout of 5 seconds, which should be sufficient for most cases

### High Memory Usage

**Symptoms:** Consumer process uses excessive memory.

**Cause:** Process workers don't share memory, each loads the full environment.

**Solution:**
1. Reduce worker count: `huey_consumer ... -w 2`
2. Use thread workers for lighter tasks: `-k thread` (but be aware of GIL limitations)
3. Increase available RAM or use a smaller batch size

## Configuration

### Huey Database Location

By default, Huey stores its queue in `.neuroflow/huey.db` (relative to the current directory). To change this:

```python
from neuroflow.tasks import configure_huey

configure_huey("/var/lib/neuroflow/state")
# Database will be at /var/lib/neuroflow/state/huey.db
```

Or set the state directory in your neuroflow config:

```yaml
execution:
  state_dir: /var/lib/neuroflow/state
```

### Consumer Options

Full list of `huey_consumer` options:

```bash
huey_consumer [module.path] [options]

Options:
  -w, --workers N       Number of worker processes/threads (default: 1)
  -k, --worker-type     Worker type: process, thread, greenlet (default: thread)
  -l, --logfile FILE    Path to log file
  -v, --verbose         Verbose logging
  -q, --quiet           Minimal logging
  -C, --check-worker-health  Enable worker health checks
  -d, --delay SECONDS   Polling delay in seconds (default: 0.1)
  -m, --max-delay SECS  Maximum polling delay (default: 10)
  -n, --no-periodic     Disable periodic task execution
  -s, --scheduler-interval SECS  Scheduler check interval (default: 1)
```

## Differences from Celery

For users migrating from Celery:

| Feature | Celery | Huey |
|---|---|---|
| **Message broker** | Requires Redis or RabbitMQ | SQLite (built-in) |
| **Result backend** | Requires Redis, DB, or file | SQLite (built-in) |
| **Dependencies** | 10+ packages | 1 package (zero deps) |
| **Worker types** | Prefork, threads, eventlet, gevent | Process, thread, greenlet |
| **Task retries** | Built-in with backoff | Built-in (fixed delay) |
| **Task scheduling** | Requires Celery Beat | Built-in cron decorators |
| **Canvas (chains, groups)** | Yes | Limited (pipelines via `.then()`) |
| **Monitoring UI** | Flower | None (use logs + SessionState) |

**Key advantages of Huey:**
- Zero infrastructure (no Redis to install/manage)
- Simpler setup and deployment
- Lower resource overhead
- Better fit for neuroflow's lightweight philosophy

**Celery advantages:**
- More mature ecosystem
- Better monitoring tools (Flower)
- More sophisticated task routing and prioritization
- Better suited for high-throughput (1000+ tasks/sec)

For neuroflow's use case (dozens to hundreds of long-running neuroimaging pipelines), Huey is the better choice.

## Future Enhancements

Planned improvements for future phases:

- **Phase 2**: CLI integration (`neuroflow run pipeline --background`)
- **Phase 3**: Worker management (`neuroflow worker start/stop/status`)
- **Phase 4**: Queue-aware status display (`neuroflow status runs --live`)
- **Phase 5**: Pipeline dependency chains (run fmriprep after bids_conversion)
- **Phase 6**: Task priority and scheduling (run at specific times, priority queues)

See [docs/plans/background-runner-migration.md](plans/background-runner-migration.md) for the full implementation roadmap.
