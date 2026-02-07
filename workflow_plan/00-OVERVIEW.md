# Neuroflow Workflow Implementation Plan

## Overview

This document provides a comprehensive implementation plan for the neuroflow orchestration system. The goal is to create a robust, maintainable workflow that automatically processes neuroimaging data through multiple pipeline stages with proper logging, error handling, and resource management.

## Implementation Documents

| Document | Purpose |
|----------|---------|
| [01-ARCHITECTURE.md](./01-ARCHITECTURE.md) | System architecture, data flow, and component relationships |
| [02-WORKFLOW-SCHEDULER.md](./02-WORKFLOW-SCHEDULER.md) | Master workflow scheduler implementation |
| [03-PIPELINE-REGISTRY.md](./03-PIPELINE-REGISTRY.md) | Pipeline registration and dependency management |
| [04-STATE-MACHINE.md](./04-STATE-MACHINE.md) | Session and subject state transitions |
| [05-CELERY-CONFIGURATION.md](./05-CELERY-CONFIGURATION.md) | Celery beat schedules and task queues |
| [06-LOGGING-MONITORING.md](./06-LOGGING-MONITORING.md) | Comprehensive logging and monitoring system |
| [07-ERROR-HANDLING.md](./07-ERROR-HANDLING.md) | Retry logic, failure handling, and recovery |
| [08-CLI-COMMANDS.md](./08-CLI-COMMANDS.md) | New CLI commands for workflow management |
| [09-TESTING.md](./09-TESTING.md) | Testing strategy and test implementations |
| [10-DEPLOYMENT.md](./10-DEPLOYMENT.md) | Deployment configuration and operations |

## Current State Analysis

### What Exists

1. **Discovery System** (`neuroflow/discovery/`)
   - `scanner.py` - Scans DICOM directories
   - `sheet_mapper.py` - Maps ScanIDs to SubjectCodes via Google Sheet/CSV
   - `validator.py` - Validates sessions against protocol
   - `watcher.py` - File system watcher for incoming data

2. **State Management** (`neuroflow/core/state.py`)
   - `StateManager` class with SQLAlchemy integration
   - Audit logging for all state changes
   - Subject, Session, and PipelineRun operations

3. **Models** (`neuroflow/models/`)
   - `Subject` with status tracking
   - `Session` with pipeline counters and status
   - `PipelineRun` with comprehensive tracking
   - `AuditLog` for all operations

4. **Adapters** (`neuroflow/adapters/`)
   - `VoxelopsAdapter` for pipeline execution
   - Schema builders for HeudiConv, QSIPrep, QSIRecon, QSIParc

5. **Workers** (`neuroflow/workers/`)
   - Basic Celery app configuration
   - `run_pipeline` and `scan_directories` tasks

6. **Basic Workflow** (`neuroflow/orchestrator/workflow.py`)
   - `WorkflowManager` with `process_session` method
   - Basic subject-level pipeline triggering

### What Needs to Be Built

1. **Master Workflow Scheduler**
   - Orchestrates the complete workflow cycle
   - Handles dependencies between stages
   - Manages resource allocation

2. **Pipeline Dependency Graph**
   - Define execution order
   - Track inter-pipeline dependencies
   - Handle subject-level vs session-level transitions

3. **Enhanced State Machine**
   - More granular status tracking
   - Automatic state transitions
   - Failure state handling

4. **Retry and Recovery System**
   - Intelligent retry logic with backoff
   - Dead letter queue for permanent failures
   - Manual recovery tools

5. **Comprehensive Logging**
   - Pipeline execution logs
   - Structured log aggregation
   - Dashboard-ready metrics

6. **Workflow CLI**
   - Manual workflow triggers
   - Status monitoring
   - Debug and recovery commands

## Workflow Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         MASTER WORKFLOW CYCLE                          │
│                       (Runs every N days/hours)                        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STAGE 1: DISCOVERY                                                      │
│ ┌─────────────────────────────────────────────────────────────────────┐ │
│ │ 1. Scan DICOM directory for new folders                             │ │
│ │ 2. Fetch Google Sheet mapping (ScanID → SubjectCode)                │ │
│ │ 3. Register new sessions in database                                │ │
│ │ 4. Validate sessions against protocol                               │ │
│ └─────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STAGE 2: BIDS CONVERSION (Session-level)                                │
│ ┌─────────────────────────────────────────────────────────────────────┐ │
│ │ For: New sessions OR sessions with failed BIDS conversion           │ │
│ │ Run: HeudiConv via VoxelOps                                         │ │
│ │ Output: BIDS-formatted data                                         │ │
│ └─────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STAGE 3: QSIPREP (Subject-level)                                        │
│ ┌─────────────────────────────────────────────────────────────────────┐ │
│ │ For: New subjects OR subjects with new sessions added               │ │
│ │ Run: QSIPrep via VoxelOps (all sessions for subject)                │ │
│ │ Output: Preprocessed diffusion data                                 │ │
│ └─────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STAGE 4: QSIRECON (Session-level)                                       │
│ ┌─────────────────────────────────────────────────────────────────────┐ │
│ │ For: New sessions OR sessions with failed reconstruction            │ │
│ │ Depends: QSIPrep completed for subject                              │ │
│ │ Run: QSIRecon via VoxelOps                                          │ │
│ │ Output: Reconstructed diffusion models                              │ │
│ └─────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STAGE 5: QSIPARC (Session-level)                                        │
│ ┌─────────────────────────────────────────────────────────────────────┐ │
│ │ For: New sessions OR sessions with failed parcellation              │ │
│ │ Depends: QSIRecon completed for session                             │ │
│ │ Run: QSIParc via VoxelOps                                           │ │
│ │ Output: Connectivity matrices                                       │ │
│ └─────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Pipeline Levels

- **Session-level pipelines**: BIDS conversion, QSIRecon, QSIParc
  - Run independently for each session
  - Can be parallelized across sessions

- **Subject-level pipelines**: QSIPrep
  - Process all sessions for a subject together
  - Must wait for all session-level prerequisites

### 2. Execution Strategy

- **Celery Beat** for scheduled workflow triggers
- **Task queues** for resource management (CPU-intensive vs I/O-bound)
- **Soft rate limiting** to prevent system overload

### 3. State Management

- Explicit state machine for sessions and subjects
- Pipeline run states independent from session states
- Audit trail for all transitions

### 4. Failure Handling

- Automatic retry with exponential backoff
- Maximum retry count before marking as permanently failed
- Manual recovery tools for stuck pipelines

## Implementation Order

1. **Phase 1: Core Infrastructure**
   - Pipeline registry with dependency graph
   - Enhanced state machine
   - Celery configuration

2. **Phase 2: Workflow Scheduler**
   - Master workflow task
   - Stage-based execution
   - Dependency resolution

3. **Phase 3: Error Handling**
   - Retry logic
   - Failure notifications
   - Recovery tools

4. **Phase 4: Logging & Monitoring**
   - Structured logging
   - Metrics collection
   - Status dashboard

5. **Phase 5: CLI & Operations**
   - Workflow commands
   - Debug tools
   - Documentation

## Success Criteria

1. **Reliability**: Workflow completes without manual intervention
2. **Observability**: All operations logged and queryable
3. **Recoverability**: Failed pipelines can be automatically or manually retried
4. **Scalability**: Can handle growing number of subjects/sessions
5. **Maintainability**: Clear code structure and documentation
