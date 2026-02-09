# Phase 3 Implementation Summary: Worker Management CLI

**Status:** ✅ Completed
**Date:** 2026-02-09
**Branch:** `feature/background-queue-phase3`
**Depends on:** Phase 2 (`feature/background-queue-phase2`)

## Overview

Phase 3 adds `neuroflow worker` commands to manage the Huey consumer process, replacing the need to manually run `huey_consumer` with environment variables. This provides a unified CLI interface for starting, stopping, and monitoring the background worker.

**Key Feature:** `neuroflow worker start/stop/status/restart` commands with PID tracking, daemon mode, and queue statistics.

## What Was Implemented

### 🆕 CLI Commands

**New command group: `neuroflow worker`**

1. **`neuroflow worker start`** - Start the Huey consumer
   - Foreground or daemon (--daemon) mode
   - Custom worker count (-w N)
   - Custom log file (-l FILE)
   - Automatically sets NEUROFLOW_STATE_DIR environment variable
   - Writes PID file for tracking

2. **`neuroflow worker stop`** - Stop the consumer gracefully
   - Sends SIGTERM for graceful shutdown
   - Falls back to SIGKILL after timeout
   - Cleans up PID file
   - Configurable timeout (-t SECONDS)

3. **`neuroflow worker status`** - Show worker and queue info
   - Worker process status (PID, CPU, memory, uptime)
   - Queue statistics (pending/scheduled tasks)
   - State directory location

4. **`neuroflow worker restart`** - Restart the consumer
   - Stops existing worker
   - Starts new worker in daemon mode
   - Optional custom worker count (-w N)

### 📝 Files Created

**1. `neuroflow/cli/worker.py` (421 lines)**

**Core functionality:**
- `_get_pid_file()` - Get PID file path in state directory
- `_read_pid()` - Read PID from file, verify process exists
- `_write_pid()` - Write PID to file
- `_get_worker_info()` - Get process info (CPU, memory, uptime)

**Commands:**
- `worker start` - Launches `huey_consumer` with proper environment
- `worker stop` - Graceful shutdown with SIGTERM/SIGKILL escalation
- `worker status` - Shows process info and queue stats
- `worker restart` - Convenience command for stop + start

**Key features:**
- PID file tracking in `.neuroflow/worker.pid`
- Automatic NEUROFLOW_STATE_DIR environment setup
- Process health checking with psutil
- Rich console output with tables
- Daemon mode with background execution

**2. `tests/unit/test_cli_worker.py` (346 lines, 15 tests)**

**Test coverage:**
- `TestWorkerStart` - 5 tests (foreground, daemon, already running, failure, custom workers)
- `TestWorkerStop` - 3 tests (stop, no worker, SIGKILL escalation)
- `TestWorkerStatus` - 3 tests (running, not running, stale PID)
- `TestWorkerRestart` - 1 test (full restart cycle)
- `TestPIDFileOperations` - 3 tests (read/write, nonexistent, invalid)

### 📝 Files Modified

**1. `pyproject.toml`**
- Added `psutil>=6.0` dependency for process management

**2. `neuroflow/cli/main.py`**
- Registered `worker` command group in `_register_commands()`

## Usage Examples

### Start Worker (Foreground)

```bash
# Start with default config (2 workers)
neuroflow worker start

# Start with custom worker count
neuroflow worker start -w 8

# Start with custom log file
neuroflow worker start -l /var/log/neuroflow/worker.log
```

**Output:**
```
Starting Huey consumer...
  Workers: 2
  State dir: /var/lib/neuroflow/state
  Log file: /var/log/neuroflow/worker.log
  Mode: foreground

Running consumer in foreground (Ctrl+C to stop)...
```

### Start Worker (Daemon)

```bash
# Start in background
neuroflow worker start --daemon

# Start daemon with custom workers
neuroflow worker start --daemon -w 4
```

**Output:**
```
Starting Huey consumer...
  Workers: 4
  State dir: /var/lib/neuroflow/state
  Log file: /var/log/neuroflow/logs/worker.log
  Mode: daemon

Starting consumer in background...

✓ Worker started successfully (PID: 12345)
  Monitor: tail -f /var/log/neuroflow/logs/worker.log
  Status: neuroflow worker status
  Stop: neuroflow worker stop
```

### Check Worker Status

```bash
neuroflow worker status
```

**Output:**
```
Worker: Running

Worker Process
┏━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ Property ┃ Value       ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━┩
│ PID      │ 12345       │
│ Status   │ running     │
│ CPU %    │ 10.5%       │
│ Memory   │ 256.3 MB    │
│ Threads  │ 5           │
│ Uptime   │ 2.3 hours   │
└──────────┴─────────────┘

Queue Statistics:
  Pending: 3
  Scheduled: 1

State directory: /var/lib/neuroflow/state
```

### Stop Worker

```bash
# Stop with default 30s timeout
neuroflow worker stop

# Stop with custom timeout
neuroflow worker stop -t 60
```

**Output:**
```
Stopping worker (PID: 12345)...
  Sending SIGTERM (graceful shutdown)...
✓ Worker stopped successfully
```

### Restart Worker

```bash
# Restart with same config
neuroflow worker restart

# Restart with different worker count
neuroflow worker restart -w 8
```

**Output:**
```
Restarting worker...

Stopping worker (PID: 12345)...
  Sending SIGTERM (graceful shutdown)...
✓ Worker stopped successfully

Starting Huey consumer...
  Workers: 8
  State dir: /var/lib/neuroflow/state
  Log file: /var/log/neuroflow/logs/worker.log
  Mode: daemon

✓ Worker started successfully (PID: 54321)
  Monitor: tail -f /var/log/neuroflow/logs/worker.log
  Status: neuroflow worker status
  Stop: neuroflow worker stop
```

## Architecture

### PID File Tracking

```
State Directory: .neuroflow/
├── huey.db              # Task queue database
├── sessions.csv         # Session state
├── pipeline_runs.csv    # Run history
└── worker.pid           # Worker process ID
```

**PID lifecycle:**
1. `worker start` writes PID to `worker.pid`
2. `worker status` reads PID and checks if process exists
3. `worker stop` reads PID, sends signals, removes file
4. Stale PID files (process dead) are automatically cleaned up

### Process Management Flow

```
neuroflow worker start
         ↓
    Check PID file
         ↓
    No existing worker?
         ↓
    Build huey_consumer command
         ↓
    Set NEUROFLOW_STATE_DIR env var
         ↓
    Launch subprocess
         ↓
    Write PID file
         ↓
    Return (foreground waits, daemon returns)
```

### Environment Variable Setup

The worker commands automatically set `NEUROFLOW_STATE_DIR` before launching the consumer, solving the Phase 2 issue where users had to manually set this environment variable.

**Before (Phase 2):**
```bash
# User had to manually set env var
NEUROFLOW_STATE_DIR=/var/lib/neuroflow/state \
  huey_consumer neuroflow.tasks.huey -w 4 -k process
```

**After (Phase 3):**
```bash
# CLI sets env var automatically
neuroflow worker start -w 4 --daemon
```

## Testing

### Test Results

```
230 passed, 12 skipped in 2.39s
```

**Worker tests:** 15 passed (all new)
- 5 start tests
- 3 stop tests
- 3 status tests
- 1 restart test
- 3 PID file operation tests

**Test strategy:**
- Mock `subprocess.Popen` for process launching
- Mock `psutil.Process` for process management
- Mock `psutil.pid_exists` for PID validation
- Use real filesystem for PID file operations

### Key Test Cases

1. **Start foreground** - Verifies command construction and subprocess launch
2. **Start daemon** - Tests background mode and PID file writing
3. **Start when running** - Ensures only one worker runs at a time
4. **Start failure** - Handles process startup failures
5. **Stop graceful** - Tests SIGTERM shutdown
6. **Stop with SIGKILL** - Tests escalation on timeout
7. **Status running** - Shows process info and queue stats
8. **Status not running** - Handles missing worker
9. **Restart** - Tests stop + start cycle
10. **PID file operations** - Tests read/write/cleanup

### Running Tests

```bash
# All worker tests
pytest tests/unit/test_cli_worker.py -v

# Specific test
pytest tests/unit/test_cli_worker.py::TestWorkerStart::test_start_daemon -v

# Full suite
pytest tests/ -v
```

## Benefits Over Manual `huey_consumer`

| Feature | Manual `huey_consumer` | `neuroflow worker` |
|---------|------------------------|---------------------|
| **Ease of use** | Complex command with env vars | Simple `neuroflow worker start` |
| **Environment setup** | Manual NEUROFLOW_STATE_DIR | Automatic from config |
| **Process tracking** | Manual PID management | Automatic PID file |
| **Daemon mode** | Manual nohup/systemd | Built-in `--daemon` |
| **Status checking** | Manual ps/top | Built-in `status` command |
| **Graceful shutdown** | Manual kill -TERM | Built-in `stop` command |
| **Worker count** | Remember -w flag | Defaults from config |
| **Log file** | Manual -l flag | Defaults from config |

## Dependencies

**New dependency:**
- `psutil>=6.0` - Process and system utilities for Python

**Why psutil:**
- Cross-platform process management
- Process info (CPU, memory, status)
- PID existence checking
- Graceful process termination

## Known Limitations

### 1. No Multi-Worker Support

**Issue:** Only one worker instance can run at a time (enforced by PID file).

**Workaround:** Start multiple workers manually with different state directories.

**Future:** Could support multiple workers with different profiles.

### 2. No Log Rotation

**Issue:** Worker log file grows indefinitely.

**Workaround:** Use external log rotation (logrotate).

**Future:** Add built-in log rotation or integration with logrotate.

### 3. No Process Supervision

**Issue:** If worker crashes, it doesn't auto-restart.

**Workaround:** Use systemd with `Restart=always` (see below).

**Future:** Add watchdog for auto-restart.

### 4. Status Command CPU/Memory

**Issue:** CPU percentage requires 0.1s sleep, adds latency.

**Workaround:** Acceptable for occasional status checks.

**Future:** Make CPU check optional with `--no-cpu` flag.

## Production Deployment

### Systemd Integration

While Phase 3 adds worker commands, systemd is still recommended for production:

**`/etc/systemd/system/neuroflow-worker.service`:**
```ini
[Unit]
Description=Neuroflow Pipeline Worker
After=network.target

[Service]
Type=simple
User=neuroflow
Group=neuroflow
WorkingDirectory=/opt/neuroflow

# Use neuroflow worker start instead of raw huey_consumer
ExecStart=/opt/neuroflow/venv/bin/neuroflow --config /etc/neuroflow/neuroflow.yaml worker start
ExecStop=/opt/neuroflow/venv/bin/neuroflow --config /etc/neuroflow/neuroflow.yaml worker stop

Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Benefits:**
- Auto-start on boot
- Auto-restart on crash
- Log to systemd journal
- Process isolation

**Commands:**
```bash
sudo systemctl start neuroflow-worker
sudo systemctl enable neuroflow-worker
sudo systemctl status neuroflow-worker
sudo journalctl -u neuroflow-worker -f
```

## Migration from Phase 2

**Phase 2 (manual consumer):**
```bash
# Terminal 1: Start consumer
NEUROFLOW_STATE_DIR=/var/lib/neuroflow/state \
  huey_consumer neuroflow.tasks.huey -w 4 -k process

# Terminal 2: Enqueue tasks
neuroflow run pipeline qsiprep
```

**Phase 3 (worker commands):**
```bash
# Start worker once (daemon mode)
neuroflow worker start --daemon -w 4

# Enqueue tasks (worker runs in background)
neuroflow run pipeline qsiprep

# Check worker status
neuroflow worker status

# Stop worker when done
neuroflow worker stop
```

## Next Steps

### Phase 4: Enhanced Status Display

**Goal:** Make `neuroflow status runs` queue-aware.

**Features:**
- Show queue depth in status output
- Show currently running tasks with task IDs
- Real-time updates with `--watch` flag
- Filter by status (`--status running`)
- Integration with worker status

### Phase 5: Production Deployment Tools

**Goal:** Automate systemd setup.

**Features:**
- `neuroflow worker install-service` - Generate systemd unit
- `neuroflow worker uninstall-service` - Remove systemd unit
- Log rotation configuration
- Monitoring and alerting setup

### Phase 6: Advanced Worker Features

**Goal:** Multi-worker and priority queues.

**Features:**
- Multiple worker profiles (fast/slow queues)
- Task priorities
- Worker pools for different pipeline types
- Auto-scaling based on queue depth

## References

- **Phase 1 Summary:** [phase1-summary.md](phase1-summary.md)
- **Phase 2 Summary:** [phase2-summary.md](phase2-summary.md)
- **Implementation Plan:** [background-runner-migration.md](background-runner-migration.md)
- **User Guide:** [../background-queue.md](../background-queue.md)
- **Branch:** `feature/background-queue-phase3`
