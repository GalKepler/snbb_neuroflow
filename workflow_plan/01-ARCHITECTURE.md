# Architecture Design

## System Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              NEUROFLOW SYSTEM                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────────┐    ┌──────────────────────┐    ┌───────────────┐ │
│  │   CLI / API Layer    │    │   Celery Beat        │    │   Watcher     │ │
│  │   (neuroflow/cli/)   │    │   (Scheduler)        │    │   (Optional)  │ │
│  └──────────┬───────────┘    └──────────┬───────────┘    └───────┬───────┘ │
│             │                           │                         │         │
│             ▼                           ▼                         ▼         │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                        WORKFLOW SCHEDULER                            │  │
│  │                  (neuroflow/orchestrator/scheduler.py)               │  │
│  │  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐           │  │
│  │  │ Stage Manager  │ │ Dependency     │ │ Resource       │           │  │
│  │  │                │ │ Resolver       │ │ Allocator      │           │  │
│  │  └────────────────┘ └────────────────┘ └────────────────┘           │  │
│  └──────────────────────────────────────┬───────────────────────────────┘  │
│                                         │                                   │
│  ┌──────────────────────────────────────┼───────────────────────────────┐  │
│  │                         CORE LAYER   │                               │  │
│  │                                      ▼                               │  │
│  │  ┌─────────────────┐  ┌──────────────────────┐  ┌─────────────────┐ │  │
│  │  │ Pipeline        │  │ State Manager        │  │ Audit Logger    │ │  │
│  │  │ Registry        │  │ (core/state.py)      │  │                 │ │  │
│  │  │                 │  │                      │  │                 │ │  │
│  │  └─────────────────┘  └──────────────────────┘  └─────────────────┘ │  │
│  │                                │                                     │  │
│  └────────────────────────────────┼─────────────────────────────────────┘  │
│                                   │                                         │
│  ┌────────────────────────────────┼─────────────────────────────────────┐  │
│  │                    EXECUTION LAYER                                   │  │
│  │                                ▼                                     │  │
│  │  ┌──────────────────────────────────────────────────────────────┐   │  │
│  │  │                    CELERY WORKERS                            │   │  │
│  │  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐│   │  │
│  │  │  │ Discovery  │ │ BIDS Queue │ │ Processing │ │ Heavy      ││   │  │
│  │  │  │ Queue      │ │            │ │ Queue      │ │ Queue      ││   │  │
│  │  │  └────────────┘ └────────────┘ └────────────┘ └────────────┘│   │  │
│  │  └──────────────────────────────────────────────────────────────┘   │  │
│  │                                │                                     │  │
│  │  ┌──────────────────────────────────────────────────────────────┐   │  │
│  │  │                    VOXELOPS ADAPTER                          │   │  │
│  │  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐│   │  │
│  │  │  │ HeudiConv  │ │ QSIPrep    │ │ QSIRecon   │ │ QSIParc    ││   │  │
│  │  │  │ Builder    │ │ Builder    │ │ Builder    │ │ Builder    ││   │  │
│  │  │  └────────────┘ └────────────┘ └────────────┘ └────────────┘│   │  │
│  │  └──────────────────────────────────────────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         DATA LAYER                                   │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────────┐ │  │
│  │  │ PostgreSQL │  │ Redis      │  │ File System│  │ Google Sheet   │ │  │
│  │  │ (State DB) │  │ (Queue)    │  │ (Data)     │  │ (Mapping)      │ │  │
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   DICOM     │────▶│   BIDS      │────▶│  QSIPrep    │────▶│  QSIRecon   │
│   Incoming  │     │   Dataset   │     │  Outputs    │     │  Outputs    │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
      │                   │                   │                   │
      │                   │                   │                   ▼
      │                   │                   │           ┌─────────────┐
      │                   │                   │           │  QSIParc    │
      │                   │                   │           │  Outputs    │
      │                   │                   │           └─────────────┘
      │                   │                   │                   │
      ▼                   ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          DATABASE STATE                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ Subject  │  │ Session  │  │ Pipeline │  │ Audit    │  │ Workflow │  │
│  │ Records  │  │ Records  │  │ Runs     │  │ Log      │  │ Runs     │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## New Components to Create

### 1. Pipeline Registry (`neuroflow/orchestrator/registry.py`)

```python
"""Pipeline Registry - Central registry of all pipelines with dependencies."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

class PipelineLevel(str, Enum):
    SESSION = "session"
    SUBJECT = "subject"

class PipelineStage(int, Enum):
    DISCOVERY = 0
    BIDS_CONVERSION = 1
    PREPROCESSING = 2
    RECONSTRUCTION = 3
    PARCELLATION = 4

@dataclass
class PipelineDefinition:
    """Definition of a pipeline with its dependencies and configuration."""
    name: str
    stage: PipelineStage
    level: PipelineLevel
    runner: str
    depends_on: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)  # Pipelines this triggers
    required_inputs: list[str] = field(default_factory=list)  # BIDS suffixes
    retry_policy: dict = field(default_factory=dict)
    resource_requirements: dict = field(default_factory=dict)
    
class PipelineRegistry:
    """Registry of all available pipelines."""
    
    def __init__(self):
        self._pipelines: dict[str, PipelineDefinition] = {}
        self._register_default_pipelines()
    
    def register(self, pipeline: PipelineDefinition) -> None:
        """Register a pipeline definition."""
        pass
    
    def get(self, name: str) -> PipelineDefinition | None:
        """Get pipeline definition by name."""
        pass
    
    def get_by_stage(self, stage: PipelineStage) -> list[PipelineDefinition]:
        """Get all pipelines for a stage."""
        pass
    
    def get_dependencies(self, name: str) -> list[PipelineDefinition]:
        """Get all dependencies for a pipeline (recursive)."""
        pass
    
    def get_execution_order(self) -> list[PipelineDefinition]:
        """Get pipelines in dependency-resolved execution order."""
        pass
```

### 2. Workflow Scheduler (`neuroflow/orchestrator/scheduler.py`)

```python
"""Master Workflow Scheduler - Orchestrates the complete processing workflow."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class WorkflowRun:
    """Represents a single workflow execution."""
    id: int
    started_at: datetime
    completed_at: datetime | None
    status: WorkflowStatus
    stages_completed: list[str]
    current_stage: str | None
    error_message: str | None
    metrics: dict

class WorkflowScheduler:
    """Master scheduler for the complete workflow cycle."""
    
    def __init__(self, config: NeuroflowConfig, state: StateManager):
        self.config = config
        self.state = state
        self.registry = PipelineRegistry()
    
    def run_workflow(self, force_stage: str | None = None) -> WorkflowRun:
        """Execute the complete workflow cycle."""
        pass
    
    def run_stage_discovery(self, workflow_run_id: int) -> list[int]:
        """Stage 1: Scan and register new sessions."""
        pass
    
    def run_stage_bids_conversion(self, workflow_run_id: int) -> list[int]:
        """Stage 2: Convert DICOM to BIDS for eligible sessions."""
        pass
    
    def run_stage_qsiprep(self, workflow_run_id: int) -> list[int]:
        """Stage 3: Run QSIPrep for eligible subjects."""
        pass
    
    def run_stage_qsirecon(self, workflow_run_id: int) -> list[int]:
        """Stage 4: Run QSIRecon for eligible sessions."""
        pass
    
    def run_stage_qsiparc(self, workflow_run_id: int) -> list[int]:
        """Stage 5: Run QSIParc for eligible sessions."""
        pass
    
    def _get_eligible_sessions_for_bids(self) -> list[Session]:
        """Get sessions needing BIDS conversion."""
        pass
    
    def _get_eligible_subjects_for_qsiprep(self) -> list[Subject]:
        """Get subjects needing QSIPrep."""
        pass
    
    def _check_dependencies_met(
        self, pipeline: PipelineDefinition, session_or_subject
    ) -> bool:
        """Check if all dependencies are satisfied."""
        pass
```

### 3. Workflow Run Model (`neuroflow/models/workflow_run.py`)

```python
"""WorkflowRun model for tracking workflow executions."""

class WorkflowRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class WorkflowRun(Base, TimestampMixin):
    """Tracks a complete workflow execution cycle."""
    __tablename__ = "workflow_runs"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[WorkflowRunStatus]
    trigger_type: Mapped[str]  # "scheduled", "manual", "event"
    started_at: Mapped[datetime]
    completed_at: Mapped[Optional[datetime]]
    
    # Stage tracking
    stages_completed: Mapped[list] = mapped_column(JSON)
    current_stage: Mapped[Optional[str]]
    
    # Metrics
    sessions_discovered: Mapped[int]
    sessions_converted: Mapped[int]
    subjects_preprocessed: Mapped[int]
    sessions_reconstructed: Mapped[int]
    sessions_parcellated: Mapped[int]
    
    # Error handling
    error_message: Mapped[Optional[str]]
    error_stage: Mapped[Optional[str]]
    
    # Related pipeline runs
    pipeline_runs: Mapped[list["PipelineRun"]] = relationship(...)
```

### 4. Enhanced Celery Tasks (`neuroflow/workers/workflow_tasks.py`)

```python
"""Celery tasks for workflow orchestration."""

@shared_task(name="neuroflow.workers.workflow_tasks.run_master_workflow")
def run_master_workflow() -> dict:
    """Master workflow task - runs the complete cycle."""
    pass

@shared_task(name="neuroflow.workers.workflow_tasks.run_discovery_stage")
def run_discovery_stage(workflow_run_id: int) -> dict:
    """Discovery stage task."""
    pass

@shared_task(name="neuroflow.workers.workflow_tasks.run_bids_stage")
def run_bids_stage(workflow_run_id: int) -> dict:
    """BIDS conversion stage task."""
    pass

@shared_task(name="neuroflow.workers.workflow_tasks.run_qsiprep_stage")
def run_qsiprep_stage(workflow_run_id: int) -> dict:
    """QSIPrep stage task."""
    pass

@shared_task(name="neuroflow.workers.workflow_tasks.run_qsirecon_stage")
def run_qsirecon_stage(workflow_run_id: int) -> dict:
    """QSIRecon stage task."""
    pass

@shared_task(name="neuroflow.workers.workflow_tasks.run_qsiparc_stage")
def run_qsiparc_stage(workflow_run_id: int) -> dict:
    """QSIParc stage task."""
    pass
```

## Directory Structure Changes

```
neuroflow/
├── __init__.py
├── adapters/
│   ├── __init__.py
│   ├── voxelops.py
│   └── voxelops_schemas.py
├── api/
│   └── __init__.py
├── cli/
│   ├── __init__.py
│   ├── export.py
│   ├── main.py
│   ├── process.py
│   ├── run.py
│   ├── scan.py
│   ├── status.py
│   └── workflow.py              # NEW: Workflow CLI commands
├── config.py
├── core/
│   ├── __init__.py
│   ├── logging.py
│   └── state.py
├── discovery/
│   ├── __init__.py
│   ├── scanner.py
│   ├── sheet_mapper.py
│   ├── validator.py
│   └── watcher.py
├── models/
│   ├── __init__.py
│   ├── audit.py
│   ├── base.py
│   ├── pipeline_run.py
│   ├── session.py
│   ├── subject.py
│   └── workflow_run.py          # NEW: Workflow run model
├── orchestrator/
│   ├── __init__.py
│   ├── registry.py              # NEW: Pipeline registry
│   ├── scheduler.py             # NEW: Workflow scheduler
│   ├── stages.py                # NEW: Stage implementations
│   └── workflow.py              # MODIFY: Enhance existing
└── workers/
    ├── __init__.py
    ├── callbacks.py
    ├── celery_app.py
    ├── tasks.py
    └── workflow_tasks.py        # NEW: Workflow-specific tasks
```

## Database Schema Changes

### New Table: `workflow_runs`

```sql
CREATE TABLE workflow_runs (
    id SERIAL PRIMARY KEY,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    trigger_type VARCHAR(32) NOT NULL,
    trigger_details JSONB,
    
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    
    stages_completed JSONB DEFAULT '[]',
    current_stage VARCHAR(64),
    
    sessions_discovered INTEGER DEFAULT 0,
    sessions_converted INTEGER DEFAULT 0,
    subjects_preprocessed INTEGER DEFAULT 0,
    sessions_reconstructed INTEGER DEFAULT 0,
    sessions_parcellated INTEGER DEFAULT 0,
    
    error_message TEXT,
    error_stage VARCHAR(64),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_workflow_runs_status ON workflow_runs(status);
CREATE INDEX idx_workflow_runs_started_at ON workflow_runs(started_at);
```

### Modifications to Existing Tables

```sql
-- Add workflow_run_id to pipeline_runs
ALTER TABLE pipeline_runs 
ADD COLUMN workflow_run_id INTEGER REFERENCES workflow_runs(id);

CREATE INDEX idx_pipeline_runs_workflow ON pipeline_runs(workflow_run_id);

-- Add needs_rerun flag to sessions
ALTER TABLE sessions
ADD COLUMN needs_rerun BOOLEAN DEFAULT FALSE,
ADD COLUMN last_failure_reason TEXT;

-- Add processing flags to subjects
ALTER TABLE subjects
ADD COLUMN needs_qsiprep BOOLEAN DEFAULT FALSE,
ADD COLUMN qsiprep_last_run_at TIMESTAMP WITH TIME ZONE;
```

## Configuration Updates

### Enhanced `neuroflow.yaml`

```yaml
# Workflow configuration
workflow:
  # Schedule: cron expression for when to run the master workflow
  schedule: "0 2 */3 * *"  # Every 3 days at 2 AM
  
  # Maximum concurrent pipelines per stage
  max_concurrent:
    bids_conversion: 4
    qsiprep: 1  # Heavy, run one at a time
    qsirecon: 2
    qsiparc: 4
  
  # Retry policy
  retry:
    max_attempts: 3
    initial_delay_minutes: 5
    max_delay_minutes: 60
    exponential_backoff: true
  
  # Notifications
  notifications:
    on_workflow_complete: true
    on_stage_failure: true
    on_pipeline_failure: true
    slack_webhook: ${SLACK_WEBHOOK_URL}
    email_recipients: ["admin@example.com"]
  
  # Resource limits
  resources:
    max_total_memory_gb: 64
    max_total_cpus: 16
    qsiprep_memory_gb: 32
    qsiprep_cpus: 8

# Pipeline-specific retry policies
pipelines:
  bids_conversion:
    # ... existing config ...
    retry:
      max_attempts: 2
      delay_minutes: 5
  
  session_level:
    - name: "qsirecon"
      # ... existing config ...
      retry:
        max_attempts: 3
        delay_minutes: 30
```

## Task Queue Design

```
┌────────────────────────────────────────────────────────────────────────┐
│                          CELERY QUEUES                                  │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ QUEUE: workflow (Priority: High)                                 │  │
│  │ Tasks: run_master_workflow, stage orchestration                  │  │
│  │ Workers: 1 (single workflow at a time)                           │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ QUEUE: discovery (Priority: High)                                │  │
│  │ Tasks: scan_directories, validate_sessions                       │  │
│  │ Workers: 2                                                       │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ QUEUE: bids (Priority: Medium)                                   │  │
│  │ Tasks: run_bids_conversion                                       │  │
│  │ Workers: 4 (or max_concurrent.bids_conversion)                   │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ QUEUE: heavy_processing (Priority: Low, Resource-intensive)      │  │
│  │ Tasks: run_qsiprep                                               │  │
│  │ Workers: 1 (single heavy job at a time)                          │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ QUEUE: processing (Priority: Medium)                             │  │
│  │ Tasks: run_qsirecon, run_qsiparc                                 │  │
│  │ Workers: 2-4                                                     │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ QUEUE: default (Priority: Normal)                                │  │
│  │ Tasks: notifications, cleanup, misc                              │  │
│  │ Workers: 2                                                       │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

## Alembic Migration

Create migration for new schema:

```python
"""Add workflow_runs table and enhance existing tables.

Revision ID: xxxx
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade() -> None:
    # Create workflow_runs table
    op.create_table(
        'workflow_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('status', sa.String(32), nullable=False, default='pending'),
        sa.Column('trigger_type', sa.String(32), nullable=False),
        sa.Column('trigger_details', sa.JSON()),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('stages_completed', sa.JSON(), default=[]),
        sa.Column('current_stage', sa.String(64)),
        sa.Column('sessions_discovered', sa.Integer(), default=0),
        sa.Column('sessions_converted', sa.Integer(), default=0),
        sa.Column('subjects_preprocessed', sa.Integer(), default=0),
        sa.Column('sessions_reconstructed', sa.Integer(), default=0),
        sa.Column('sessions_parcellated', sa.Integer(), default=0),
        sa.Column('error_message', sa.Text()),
        sa.Column('error_stage', sa.String(64)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    # Add indexes
    op.create_index('idx_workflow_runs_status', 'workflow_runs', ['status'])
    op.create_index('idx_workflow_runs_started_at', 'workflow_runs', ['started_at'])
    
    # Modify pipeline_runs
    op.add_column('pipeline_runs', sa.Column('workflow_run_id', sa.Integer()))
    op.create_foreign_key(
        'fk_pipeline_runs_workflow', 
        'pipeline_runs', 'workflow_runs',
        ['workflow_run_id'], ['id']
    )
    op.create_index('idx_pipeline_runs_workflow', 'pipeline_runs', ['workflow_run_id'])
    
    # Modify sessions
    op.add_column('sessions', sa.Column('needs_rerun', sa.Boolean(), default=False))
    op.add_column('sessions', sa.Column('last_failure_reason', sa.Text()))
    
    # Modify subjects
    op.add_column('subjects', sa.Column('needs_qsiprep', sa.Boolean(), default=False))
    op.add_column('subjects', sa.Column('qsiprep_last_run_at', sa.DateTime(timezone=True)))

def downgrade() -> None:
    op.drop_column('subjects', 'qsiprep_last_run_at')
    op.drop_column('subjects', 'needs_qsiprep')
    op.drop_column('sessions', 'last_failure_reason')
    op.drop_column('sessions', 'needs_rerun')
    op.drop_constraint('fk_pipeline_runs_workflow', 'pipeline_runs')
    op.drop_index('idx_pipeline_runs_workflow')
    op.drop_column('pipeline_runs', 'workflow_run_id')
    op.drop_table('workflow_runs')
```
