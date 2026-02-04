# Neuroflow - Implementation Guide

## Overview

This guide walks you through establishing the neuroflow project from scratch. Follow the phases in order.

---

## Prerequisites

Before starting, ensure you have:

1. **Python 3.10+** installed
2. **Redis** installed and running (`redis-server`)
3. **Git** for version control
4. **Optional**: PostgreSQL (SQLite works for development)

### Quick Redis Setup (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install redis-server
sudo systemctl start redis
sudo systemctl enable redis

# Verify
redis-cli ping  # Should return PONG
```

### Quick Redis Setup (macOS)

```bash
brew install redis
brew services start redis
```

---

## Phase 1: Project Foundation (Day 1)

### Step 1.1: Create Project Structure

```bash
# Create the project directory
mkdir neuroflow
cd neuroflow

# Initialize git
git init

# Create directory structure
mkdir -p neuroflow/{models,core,discovery,orchestrator,workers,adapters,cli,api}
mkdir -p tests/{unit,integration,fixtures}
mkdir -p configs migrations scripts docker docs

# Create __init__.py files
touch neuroflow/__init__.py
touch neuroflow/{models,core,discovery,orchestrator,workers,adapters,cli,api}/__init__.py
```

### Step 1.2: Create pyproject.toml

```bash
cat > pyproject.toml << 'EOF'
[project]
name = "neuroflow"
version = "0.1.0"
description = "Task orchestration for neuroimaging pipelines"
requires-python = ">=3.10"
dependencies = [
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "celery[redis]>=5.3",
    "watchdog>=4.0",
    "structlog>=24.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "pyyaml>=6.0",
    "pydicom>=2.4",
    "click>=8.1",
    "rich>=13.0",
    "python-dateutil>=2.8",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov",
    "ruff",
    "mypy",
]
postgres = ["psycopg2-binary>=2.9"]

[project.scripts]
neuroflow = "neuroflow.cli.main:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.mypy]
python_version = "3.10"
strict = true
EOF
```

### Step 1.3: Create Virtual Environment and Install

```bash
# Create venv
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or: .venv\Scripts\activate  # Windows

# Install in development mode
pip install -e ".[dev]"
```

### Step 1.4: Create Example Configuration

```bash
cat > configs/neuroflow.example.yaml << 'EOF'
# Neuroflow Configuration Example
# Copy to neuroflow.yaml and customize

paths:
  dicom_incoming: /mnt/62/Raw_Data
  bids_root: /data/brainbank/bids
  derivatives: /data/brainbank/derivatives
  work_dir: /data/brainbank/.neuroflow
  log_dir: /var/log/neuroflow

database:
  url: "sqlite:////data/brainbank/.neuroflow/neuroflow.db"

redis:
  url: "redis://localhost:6379/0"

dataset:
  name: "brainbank"
  session_ids: ["baseline", "followup"]
  dicom_participant_first: true

protocol:
  stability_wait_minutes: 180
  bids_conversion:
    min_dicom_files: 10

pipelines:
  bids_conversion:
    enabled: true
    tool: "heudiconv"
    version: "1.3.4"
    timeout_minutes: 60
    retries: 2
  
  session_level:
    - name: "mriqc"
      enabled: true
      runner: "voxelops.runners.mriqc"
      container: "nipreps/mriqc:24.0.0"
      timeout_minutes: 120
      requirements:
        bids_suffixes: ["T1w"]
    
    - name: "freesurfer"
      enabled: true
      runner: "voxelops.runners.freesurfer"
      container: "freesurfer/freesurfer:7.4.1"
      timeout_minutes: 720
      requirements:
        bids_suffixes: ["T1w"]

celery:
  worker_concurrency: 2
  task_soft_time_limit: 43200
  task_time_limit: 86400

logging:
  level: INFO
  format: console
EOF
```

### Step 1.5: Create .gitignore

```bash
cat > .gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
*.egg-info/
.eggs/
dist/
build/

# Virtual environments
.venv/
venv/

# IDE
.vscode/
.idea/

# Environment
.env
*.env.local

# Testing
.pytest_cache/
.coverage
htmlcov/

# Logs
*.log
logs/

# Database
*.db
*.sqlite3

# OS
.DS_Store
EOF
```

### Step 1.6: Verify Setup

```bash
# Verify Python environment
python -c "import sqlalchemy; print(f'SQLAlchemy {sqlalchemy.__version__}')"
python -c "import celery; print(f'Celery {celery.__version__}')"
python -c "import structlog; print(f'structlog {structlog.__version__}')"

# Verify Redis
redis-cli ping
```

**✅ Phase 1 Complete** when:
- [ ] Project structure created
- [ ] Dependencies installed
- [ ] Example config created
- [ ] All imports work

---

## Phase 2: Configuration and Models (Day 1-2)

### Step 2.1: Implement Configuration

Copy the configuration classes from `02_CONFIGURATION.md` to `neuroflow/config.py`.

Test:
```bash
python -c "from neuroflow.config import NeuroflowConfig; print('Config OK')"
```

### Step 2.2: Implement Database Models

Copy the SQLAlchemy models from `03_DATABASE_SCHEMA.md` to:
- `neuroflow/models/base.py`
- `neuroflow/models/subject.py`
- `neuroflow/models/session.py`
- `neuroflow/models/pipeline_run.py`
- `neuroflow/models/audit.py`

Create `neuroflow/models/__init__.py`:
```python
from .base import Base, TimestampMixin
from .subject import Subject, SubjectStatus
from .session import Session, SessionStatus
from .pipeline_run import PipelineRun, PipelineRunStatus
from .audit import AuditLog

__all__ = [
    "Base", "TimestampMixin",
    "Subject", "SubjectStatus",
    "Session", "SessionStatus",
    "PipelineRun", "PipelineRunStatus",
    "AuditLog",
]
```

### Step 2.3: Implement State Manager

Copy the StateManager from `05_CORE_COMPONENTS.md` to `neuroflow/core/state.py`.

### Step 2.4: Implement Logging

Copy the logging setup from `05_CORE_COMPONENTS.md` to `neuroflow/core/logging.py`.

### Step 2.5: Create Basic CLI

```python
# neuroflow/cli/main.py

import click
from rich.console import Console

from neuroflow.config import NeuroflowConfig
from neuroflow.core.state import StateManager
from neuroflow.core.logging import setup_logging

console = Console()


@click.group()
@click.option("--config", "-c", default="neuroflow.yaml", help="Config file path")
@click.option("--log-level", default="INFO", help="Log level")
@click.pass_context
def cli(ctx, config, log_level):
    """Neuroflow - Neuroimaging pipeline orchestration."""
    ctx.ensure_object(dict)
    
    try:
        ctx.obj["config"] = NeuroflowConfig.from_yaml(config)
    except FileNotFoundError:
        console.print(f"[red]Config file not found: {config}[/red]")
        raise SystemExit(1)
    
    setup_logging(level=log_level, format="console")


@cli.group()
def admin():
    """Administrative commands."""
    pass


@admin.command("init-db")
@click.pass_context
def init_db(ctx):
    """Initialize the database."""
    config = ctx.obj["config"]
    state = StateManager(config)
    state.init_db()
    console.print("[green]Database initialized successfully.[/green]")


@cli.command()
@click.pass_context
def status(ctx):
    """Show system status."""
    console.print("[bold]Neuroflow Status[/bold]")
    console.print("Database: OK")
    console.print("Redis: OK")


if __name__ == "__main__":
    cli()
```

### Step 2.6: Test Database Setup

```bash
# Create a test config
cp configs/neuroflow.example.yaml neuroflow.yaml

# Edit neuroflow.yaml to use a local test database
# Change database.url to: "sqlite:///test.db"

# Initialize database
neuroflow admin init-db

# Verify
python -c "
from neuroflow.config import NeuroflowConfig
from neuroflow.core.state import StateManager

config = NeuroflowConfig.from_yaml('neuroflow.yaml')
state = StateManager(config)

# Test creating a subject
subject = state.get_or_create_subject('sub-001')
print(f'Created subject: {subject.participant_id}')
"
```

**✅ Phase 2 Complete** when:
- [ ] Config loads from YAML
- [ ] Database initializes
- [ ] Can create subjects/sessions
- [ ] `neuroflow admin init-db` works

---

## Phase 3: Discovery System (Day 2-3)

### Step 3.1: Implement Scanner

Copy the SessionScanner from `05_CORE_COMPONENTS.md` to `neuroflow/discovery/scanner.py`.

### Step 3.2: Implement Validator

```python
# neuroflow/discovery/validator.py

import re
from dataclasses import dataclass
import structlog

from neuroflow.config import NeuroflowConfig, ScanRequirement
from neuroflow.discovery.scanner import ScanInfo

log = structlog.get_logger("validator")


@dataclass
class ValidationResult:
    is_valid: bool
    scans_found: dict[str, int]
    missing_required: list[str]
    message: str


class SessionValidator:
    """Validate sessions against protocol requirements."""
    
    def __init__(self, config: NeuroflowConfig):
        self.config = config
    
    def validate(self, scans: list[ScanInfo]) -> ValidationResult:
        """Validate a session's scans against protocol."""
        
        scans_found = {}
        matched_required = set()
        
        # Check each scan against required patterns
        for scan in scans:
            for req in self.config.protocol.required_scans:
                if re.match(req.series_description_pattern, scan.series_description, re.IGNORECASE):
                    scans_found[req.name] = scan.file_count
                    
                    if scan.file_count >= req.min_files:
                        if req.max_files is None or scan.file_count <= req.max_files:
                            matched_required.add(req.name)
        
        # Find missing required scans
        required_names = {r.name for r in self.config.protocol.required_scans}
        missing = list(required_names - matched_required)
        
        is_valid = len(missing) == 0
        
        if is_valid:
            message = f"Session valid: {len(scans_found)} scans found"
        else:
            message = f"Missing required scans: {', '.join(missing)}"
        
        return ValidationResult(
            is_valid=is_valid,
            scans_found=scans_found,
            missing_required=missing,
            message=message,
        )
```

### Step 3.3: Implement Watcher

Copy the DicomWatcher from `05_CORE_COMPONENTS.md` to `neuroflow/discovery/watcher.py`.

### Step 3.4: Add Discovery CLI Commands

```python
# neuroflow/cli/scan.py

import click
from rich.console import Console
from rich.table import Table

from neuroflow.discovery.scanner import SessionScanner

console = Console()


@click.group()
def scan():
    """Discovery commands."""
    pass


@scan.command("now")
@click.option("--dry-run", is_flag=True, help="Show what would be found")
@click.pass_context
def scan_now(ctx):
    """Scan for new DICOM sessions."""
    config = ctx.obj["config"]
    scanner = SessionScanner(config)
    
    with console.status("Scanning directories..."):
        results = scanner.scan_all()
    
    if not results:
        console.print("[yellow]No new sessions found.[/yellow]")
        return
    
    table = Table(title=f"Found {len(results)} Sessions")
    table.add_column("Subject")
    table.add_column("Session")
    table.add_column("Scans")
    table.add_column("Path")
    
    for r in results:
        table.add_row(
            r.subject_id,
            r.session_id,
            str(len(r.scans)),
            str(r.session_path)[:50],
        )
    
    console.print(table)
```

Update `neuroflow/cli/main.py` to include:
```python
from neuroflow.cli.scan import scan
cli.add_command(scan)
```

**✅ Phase 3 Complete** when:
- [ ] `neuroflow scan now` finds DICOM sessions
- [ ] Sessions are registered in database
- [ ] Validation works

---

## Phase 4: Celery Workers (Day 3-4)

### Step 4.1: Create Celery App

Copy the Celery configuration from `05_CORE_COMPONENTS.md` to `neuroflow/workers/celery_app.py`.

### Step 4.2: Create Tasks

Copy the task definitions from `05_CORE_COMPONENTS.md` to `neuroflow/workers/tasks.py`.

### Step 4.3: Create Voxelops Adapter

Copy the VoxelopsAdapter from `05_CORE_COMPONENTS.md` to `neuroflow/adapters/voxelops.py`.

### Step 4.4: Add Run Commands

```python
# neuroflow/cli/run.py

import click
from rich.console import Console

console = Console()


@click.group()
def run():
    """Service commands."""
    pass


@run.command("worker")
@click.option("-c", "--concurrency", default=2, help="Worker concurrency")
@click.pass_context
def run_worker(ctx):
    """Start Celery worker."""
    from neuroflow.workers.celery_app import celery_app
    
    console.print("[green]Starting Celery worker...[/green]")
    celery_app.worker_main(["worker", f"--concurrency={concurrency}", "--loglevel=INFO"])


@run.command("beat")
@click.pass_context
def run_beat(ctx):
    """Start Celery beat scheduler."""
    from neuroflow.workers.celery_app import celery_app
    
    console.print("[green]Starting Celery beat...[/green]")
    celery_app.worker_main(["beat", "--loglevel=INFO"])


@run.command("watcher")
@click.pass_context  
def run_watcher(ctx):
    """Start DICOM file watcher."""
    from neuroflow.discovery.watcher import DicomWatcher
    
    config = ctx.obj["config"]
    watcher = DicomWatcher(config)
    
    console.print(f"[green]Watching {config.paths.dicom_incoming}...[/green]")
    
    try:
        watcher.start()
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        watcher.stop()
        console.print("[yellow]Watcher stopped.[/yellow]")
```

### Step 4.5: Test Celery

```bash
# Terminal 1: Start Redis (if not running)
redis-server

# Terminal 2: Start worker
neuroflow run worker

# Terminal 3: Test task
python -c "
from neuroflow.workers.tasks import scan_directories
result = scan_directories.delay()
print(f'Task ID: {result.id}')
print(f'Result: {result.get(timeout=30)}')
"
```

**✅ Phase 4 Complete** when:
- [ ] Celery worker starts
- [ ] Tasks execute via queue
- [ ] File watcher runs

---

## Phase 5: Full Integration (Day 4-5)

### Step 5.1: Implement Workflow Manager

Copy the WorkflowManager from `05_CORE_COMPONENTS.md` to `neuroflow/orchestrator/workflow.py`.

### Step 5.2: Add Status Commands

```python
# neuroflow/cli/status.py

import click
from rich.console import Console
from rich.table import Table

from neuroflow.core.state import StateManager
from neuroflow.models import SessionStatus, PipelineRunStatus

console = Console()


@click.command("status")
@click.option("--sessions", is_flag=True, help="Show session details")
@click.option("--failed", is_flag=True, help="Show only failed")
@click.pass_context
def status(ctx, sessions, failed):
    """Show system status."""
    config = ctx.obj["config"]
    state = StateManager(config)
    
    # Get counts
    with state.get_session() as db:
        from sqlalchemy import select, func
        from neuroflow.models import Subject, Session, PipelineRun
        
        subject_count = db.execute(select(func.count(Subject.id))).scalar()
        session_count = db.execute(select(func.count(Session.id))).scalar()
        
        # Sessions by status
        session_stats = {}
        for status in SessionStatus:
            count = db.execute(
                select(func.count(Session.id)).where(Session.status == status)
            ).scalar()
            if count > 0:
                session_stats[status.value] = count
        
        # Pipeline runs by status
        run_stats = {}
        for status in PipelineRunStatus:
            count = db.execute(
                select(func.count(PipelineRun.id)).where(PipelineRun.status == status)
            ).scalar()
            if count > 0:
                run_stats[status.value] = count
    
    console.print("\n[bold]Neuroflow Status[/bold]\n")
    
    # Summary
    console.print(f"Subjects: {subject_count}")
    console.print(f"Sessions: {session_count}\n")
    
    # Session status table
    table = Table(title="Sessions by Status")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    for status, count in session_stats.items():
        table.add_row(status, str(count))
    console.print(table)
    
    # Pipeline runs table
    table = Table(title="Pipeline Runs by Status")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    for status, count in run_stats.items():
        table.add_row(status, str(count))
    console.print(table)
```

### Step 5.3: End-to-End Test

```bash
# 1. Initialize database
neuroflow admin init-db

# 2. Start worker (in separate terminal)
neuroflow run worker

# 3. Scan for sessions
neuroflow scan now

# 4. Check status
neuroflow status

# 5. Process pending sessions (if voxelops is configured)
neuroflow process pending
```

**✅ Phase 5 Complete** when:
- [ ] Full workflow executes: discover → validate → queue → process
- [ ] Status shows correct counts
- [ ] Audit log captures all changes

---

## Phase 6: Production Hardening (Day 5+)

### Step 6.1: Add Tests

```python
# tests/unit/test_scanner.py

import pytest
from pathlib import Path
from neuroflow.discovery.scanner import parse_dicom_path


def test_parse_dicom_path_participant_first():
    path = Path("/data/Raw_Data/sub-001/ses-baseline")
    result = parse_dicom_path(path, participant_first=True)
    assert result == ("sub-001", "ses-baseline")


def test_parse_dicom_path_session_first():
    path = Path("/data/Raw_Data/ses-baseline/sub-001")
    result = parse_dicom_path(path, participant_first=False)
    assert result == ("sub-001", "ses-baseline")
```

```bash
# Run tests
pytest tests/ -v
```

### Step 6.2: Add Docker Compose

```yaml
# docker/docker-compose.yml

version: "3.8"

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
  
  neuroflow-worker:
    build: ..
    command: neuroflow run worker
    depends_on:
      - redis
    environment:
      - NEUROFLOW_REDIS__URL=redis://redis:6379/0
    volumes:
      - ../neuroflow.yaml:/app/neuroflow.yaml
      - /data/brainbank:/data/brainbank
  
  neuroflow-beat:
    build: ..
    command: neuroflow run beat
    depends_on:
      - redis
    environment:
      - NEUROFLOW_REDIS__URL=redis://redis:6379/0

volumes:
  redis-data:
```

### Step 6.3: Add Systemd Services (Linux Production)

```ini
# /etc/systemd/system/neuroflow-worker.service

[Unit]
Description=Neuroflow Celery Worker
After=network.target redis.service

[Service]
Type=simple
User=neuroflow
WorkingDirectory=/opt/neuroflow
ExecStart=/opt/neuroflow/.venv/bin/neuroflow run worker
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## Quick Reference: Common Operations

```bash
# Initialize
neuroflow admin init-db

# Scan and process
neuroflow scan now
neuroflow status
neuroflow process pending

# Services
neuroflow run worker      # Start worker
neuroflow run beat        # Start scheduler
neuroflow run watcher     # Start file watcher

# Monitoring
neuroflow status
neuroflow status --sessions --failed

# Retry failures
neuroflow process retry --all
```

---

## Troubleshooting

### Redis Connection Failed
```bash
# Check Redis is running
redis-cli ping

# Start Redis
sudo systemctl start redis
```

### Database Locked (SQLite)
```bash
# Use PostgreSQL for production, or ensure only one writer
```

### Worker Not Processing
```bash
# Check worker logs
neuroflow run worker --loglevel=DEBUG

# Check Redis has tasks
redis-cli LLEN celery
```

---

## Next Steps

After completing the basic implementation:

1. **Customize voxelops adapter** for your specific pipelines
2. **Add web dashboard** (optional, see `04_CLI_SPECIFICATION.md` for API routes)
3. **Set up monitoring** with Prometheus/Grafana
4. **Configure notifications** for failures
5. **Add more pipelines** as needed
