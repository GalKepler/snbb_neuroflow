# Neuroflow Specification Documents

## Overview

This folder contains the complete specification for **neuroflow**, a task orchestration system for neuroimaging pipelines at the VU Amsterdam brain bank.

## Quick Start

**To establish this project:**

1. Read `06_IMPLEMENTATION_GUIDE.md` - Follow the step-by-step setup
2. Reference other docs as needed during implementation

**To use with Claude Code:**

```
Read all files in this directory and implement the neuroflow package following
the implementation guide. Start with Phase 1 and proceed sequentially.
```

---

## Document Index

| Document | Purpose |
|----------|---------|
| `01_PROJECT_OVERVIEW.md` | Architecture, goals, project structure, tech stack |
| `02_CONFIGURATION.md` | YAML config schema, Pydantic classes, environment variables |
| `03_DATABASE_SCHEMA.md` | SQLAlchemy models, SQL tables, key queries |
| `04_CLI_SPECIFICATION.md` | All CLI commands with examples, Rich output formatting |
| `05_CORE_COMPONENTS.md` | Logging, Celery tasks, StateManager, VoxelopsAdapter |
| `06_IMPLEMENTATION_GUIDE.md` | **Step-by-step setup instructions** |

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                         NEUROFLOW                                │
├─────────────────────────────────────────────────────────────────┤
│  Watcher ──▶ Scanner ──▶ Validator ──▶ Workflow ──▶ Celery     │
│     │           │            │            │            │        │
│     └───────────┴────────────┴────────────┴────────────┘        │
│                              │                                   │
│                    ┌─────────▼─────────┐                        │
│                    │   State Manager   │                        │
│                    │    (Database)     │                        │
│                    └───────────────────┘                        │
├─────────────────────────────────────────────────────────────────┤
│                         VOXELOPS                                 │
│              (Your existing pipeline runners)                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

### 1. Subject-Centric Processing
- Process one subject through all pipelines (not pipeline-by-pipeline across subjects)
- Better for a continuously growing brain bank

### 2. Modality-Gated Pipelines
- Pipelines run based on what BIDS data types are actually present
- No pre-BIDS rejection; convert everything, then gate

### 3. Celery + Redis for Task Queue
- Battle-tested for long-running scientific workflows
- Built-in retry with exponential backoff
- Task routing for different queues (BIDS conversion vs processing)

### 4. Structured Logging with Structlog
- JSON format for production (log aggregation)
- Console format for development
- Context binding for tracing (subject_id, session_id, pipeline)

### 5. Comprehensive Audit Trail
- Every state change logged
- Easy to debug: "why did this session fail?"
- Regulatory compliance for brain bank

### 6. SQLite for Development, PostgreSQL for Production
- SQLite: zero setup, single file
- PostgreSQL: concurrent access, better performance

---

## Implementation Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| 1. Foundation | Day 1 | Project structure, dependencies, config |
| 2. Models | Day 1-2 | Database schema, StateManager |
| 3. Discovery | Day 2-3 | Scanner, Validator, Watcher |
| 4. Workers | Day 3-4 | Celery tasks, VoxelopsAdapter |
| 5. Integration | Day 4-5 | WorkflowManager, full CLI |
| 6. Hardening | Day 5+ | Tests, Docker, production setup |

---

## Dependencies Summary

**Core:**
- `sqlalchemy>=2.0` - Database ORM
- `celery[redis]>=5.3` - Task queue
- `structlog>=24.0` - Structured logging
- `pydantic>=2.0` - Configuration validation
- `click>=8.1` - CLI framework
- `rich>=13.0` - Beautiful terminal output
- `watchdog>=4.0` - File system monitoring
- `pydicom>=2.4` - DICOM parsing

**Infrastructure:**
- Redis 6+ (task broker)
- SQLite or PostgreSQL (state storage)

---

## CLI Quick Reference

```bash
# Setup
neuroflow admin init-db

# Discovery
neuroflow scan now
neuroflow scan validate /path/to/session

# Status
neuroflow status
neuroflow status --sessions --failed

# Processing
neuroflow process session sub-001 ses-baseline
neuroflow process pending
neuroflow process retry --all

# Services
neuroflow run worker
neuroflow run beat
neuroflow run watcher
neuroflow run all
```

---

## Integration with Voxelops

Neuroflow calls voxelops via the `VoxelopsAdapter`:

```python
# Option 1: Direct import (if voxelops installed)
from voxelops.runners import freesurfer
result = freesurfer.run(input_path, output_path)

# Option 2: Container execution
apptainer run freesurfer.sif ...
```

Configure runners in `neuroflow.yaml`:
```yaml
pipelines:
  session_level:
    - name: "freesurfer"
      runner: "voxelops.runners.freesurfer"  # Module path
      container: "freesurfer/freesurfer:7.4.1"  # Fallback
```

---

## Questions?

If implementing and something is unclear:

1. Check the relevant spec document
2. The Implementation Guide has troubleshooting tips
3. The code examples are meant to be copy-pasteable

Good luck! 🧠
