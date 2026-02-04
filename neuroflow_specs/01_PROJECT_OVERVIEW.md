# Neuroflow - Project Specification

## Overview

**Neuroflow** is a task orchestration system for neuroimaging pipelines at the VU Amsterdam brain bank. It monitors DICOM directories, validates scanning sessions against protocol requirements, orchestrates processing procedures from the `voxelops` package, and maintains comprehensive audit trails.

## Core Problem

The brain bank continuously receives DICOM files from scanning sessions that need to pass through various processing procedures. Currently there's no automated system to:
1. Detect when new sessions are ready for processing
2. Validate session completeness against protocol requirements  
3. Track which sessions have been processed and their status
4. Handle re-processing when new sessions are added for existing subjects (longitudinal studies)
5. Provide clear visibility into pipeline status and failures

## Goals

1. **Automated Detection**: Monitor DICOM directories for new/complete sessions
2. **Validation**: Ensure sessions meet predefined scan requirements before processing
3. **Subject-Centric Processing**: Process subjects through the full pipeline chain, not just individual procedures
4. **Subject-Level Awareness**: Re-run specific procedures when new sessions added for existing subjects
5. **Observability**: Easy querying of session status, failures, and audit history
6. **Reliability**: Handle failures gracefully, support retries, maintain state across restarts

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         NEUROFLOW                                    │
├─────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │   Watcher    │───▶│  Validator   │───▶│  Subject Processor   │  │
│  │  (watchdog)  │    │  (protocol)  │    │  (workflow engine)   │  │
│  └──────────────┘    └──────────────┘    └──────────────────────┘  │
│         │                   │                       │               │
│         ▼                   ▼                       ▼               │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                      State Manager                            │  │
│  │    (SQLite/PostgreSQL: subjects, sessions, runs, audit)      │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                │                                    │
│                                ▼                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                     Task Queue (Celery + Redis)               │  │
│  │           Long-running tasks, retries, concurrency            │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                │                                    │
├────────────────────────────────┼────────────────────────────────────┤
│                                ▼                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                         VOXELOPS                              │  │
│  │     (BIDS conversion, preprocessing, QC, analysis)           │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **Subject-centric**: Process one subject at a time through all pipelines (not procedure-by-procedure across all subjects)
2. **Incremental**: Only process new/changed subjects; skip already-completed work
3. **Resilient**: Handle failures gracefully, support retries with exponential backoff
4. **Observable**: Comprehensive structured logging and status tracking
5. **Modality-gated**: Pipelines run based on what BIDS data types are actually present after conversion

---

## Integration with Voxelops

Neuroflow is a separate package that orchestrates `voxelops` procedures:

- **Import and call** voxelops runners/procedures
- **Capture** outputs, logs, and metrics
- **Not duplicate** voxelops functionality
- Provide a **clean adapter interface** for voxelops integration

---

## Technical Stack

### Python Version
- Python 3.10+

### Core Dependencies

```
# Database & ORM
sqlalchemy>=2.0
alembic>=1.13
psycopg2-binary>=2.9  # PostgreSQL driver (optional)

# Task Queue
celery[redis]>=5.3
redis>=5.0

# File Monitoring
watchdog>=4.0

# Logging
structlog>=24.0

# Configuration
pydantic>=2.0
pydantic-settings>=2.0
pyyaml>=6.0

# DICOM Processing
pydicom>=2.4

# CLI & Terminal UI
click>=8.1
rich>=13.0

# Utilities
python-dateutil>=2.8
```

### Database
- **SQLite** for development/small deployments
- **PostgreSQL** for production/scale

### Message Broker
- **Redis** for Celery task queue and result backend

---

## Project Structure

```
neuroflow/
├── neuroflow/
│   ├── __init__.py
│   ├── config.py              # Pydantic configuration
│   │
│   ├── models/                # SQLAlchemy models
│   │   ├── __init__.py
│   │   ├── base.py            # Base, mixins
│   │   ├── subject.py
│   │   ├── session.py
│   │   ├── pipeline_run.py
│   │   └── audit.py
│   │
│   ├── core/                  # Core logic
│   │   ├── __init__.py
│   │   ├── state.py           # StateManager (DB operations)
│   │   └── logging.py         # Structlog setup
│   │
│   ├── discovery/             # Session discovery & validation
│   │   ├── __init__.py
│   │   ├── scanner.py         # DICOM directory scanning
│   │   ├── validator.py       # Protocol validation
│   │   └── watcher.py         # File system watcher
│   │
│   ├── orchestrator/          # Task orchestration
│   │   ├── __init__.py
│   │   ├── workflow.py        # Workflow definitions & DAG
│   │   ├── scheduler.py       # Task scheduling logic
│   │   └── engine.py          # Orchestration engine
│   │
│   ├── workers/               # Celery tasks
│   │   ├── __init__.py
│   │   ├── celery_app.py      # Celery application config
│   │   ├── tasks.py           # Task definitions
│   │   └── callbacks.py       # Task callbacks (on_success, on_failure)
│   │
│   ├── adapters/              # External integrations
│   │   ├── __init__.py
│   │   └── voxelops.py        # Voxelops adapter
│   │
│   ├── cli/                   # Command-line interface
│   │   ├── __init__.py
│   │   ├── main.py            # Entry point
│   │   ├── status.py          # Status commands
│   │   ├── run.py             # Run/service commands
│   │   ├── scan.py            # Discovery commands
│   │   ├── process.py         # Processing commands
│   │   ├── admin.py           # Admin commands
│   │   └── export.py          # Export commands
│   │
│   └── api/                   # Optional REST API
│       ├── __init__.py
│       ├── app.py             # FastAPI/Flask app
│       └── routes.py
│
├── migrations/                # Alembic migrations
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── configs/                   # Example configurations
│   ├── neuroflow.example.yaml
│   └── protocols/
│       └── standard.yaml
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml     # Full stack (app, redis, postgres)
├── scripts/
│   └── init_db.py
├── pyproject.toml
└── README.md
```

---

## Success Criteria

The implementation is complete when:

1. ✅ `neuroflow run` starts watching directories and processing new sessions
2. ✅ `neuroflow status` shows pipeline state summary
3. ✅ `neuroflow status sessions --failed` lists failures with reasons
4. ✅ New sessions are automatically validated and queued
5. ✅ Subject-level procedures trigger when new sessions added for existing subjects
6. ✅ Full audit trail in database
7. ✅ Retry logic works for transient failures
8. ✅ CLI provides easy access to all operational data
