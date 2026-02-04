# Neuroflow - Database Schema Specification

## Overview

The database tracks subjects, sessions, pipeline runs, and provides comprehensive audit logging. 

**Design priorities:**
1. **Query-friendly**: Easy to find failed sessions, pending work, subject histories
2. **Audit-complete**: Full history of all state changes
3. **Flexible**: Support different protocols and procedure configurations

---

## Entity Relationship Diagram

```
┌──────────────┐
│   Subject    │
└──────┬───────┘
       │ 1
       │
       │ *
┌──────▼───────┐
│   Session    │
└──────┬───────┘
       │ 1
       │
       │ *
┌──────▼───────┐
│ PipelineRun  │
└──────────────┘

All entities ──► AuditLog
```

---

## Tables

### subjects

Tracks unique subjects in the brain bank.

```sql
CREATE TABLE subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Identifiers
    participant_id VARCHAR(64) NOT NULL UNIQUE,  -- BIDS-style: sub-001
    recruitment_id VARCHAR(128),                  -- Original ID if different (CLMC, scanner ID)
    
    -- Status tracking
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    -- Values: pending, validating, valid, invalid, processing, completed, failed
    
    -- Counts (denormalized for quick queries)
    session_count INTEGER DEFAULT 0,
    completed_pipelines INTEGER DEFAULT 0,
    failed_pipelines INTEGER DEFAULT 0,
    
    -- Metadata
    metadata JSONB,  -- Flexible storage (demographics, notes, etc.)
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_subjects_participant ON subjects(participant_id);
CREATE INDEX idx_subjects_status ON subjects(status);
CREATE INDEX idx_subjects_updated ON subjects(updated_at);
```

### sessions

Tracks individual scanning sessions.

```sql
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Foreign key
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    
    -- Identifiers
    session_id VARCHAR(64) NOT NULL,  -- BIDS-style: ses-baseline
    
    -- Paths
    dicom_path VARCHAR(1024),         -- Source DICOM directory
    bids_path VARCHAR(1024),          -- After conversion: .../sub-001/ses-baseline/
    
    -- Discovery & Validation
    discovered_at TIMESTAMP NOT NULL,
    validated_at TIMESTAMP,
    last_dicom_modified TIMESTAMP,    -- For stability checking
    
    -- Validation results
    is_valid BOOLEAN,
    validation_message TEXT,          -- Detailed validation result
    scans_found JSONB,                -- {"T1w": 176, "FLAIR": 48, "DWI": 65}
    
    -- Status tracking
    status VARCHAR(32) NOT NULL DEFAULT 'discovered',
    -- Values: discovered, validating, validated, invalid, 
    --         converting, converted, processing, completed, failed, excluded
    
    -- Processing tracking (denormalized)
    pipelines_pending INTEGER DEFAULT 0,
    pipelines_completed INTEGER DEFAULT 0,
    pipelines_failed INTEGER DEFAULT 0,
    
    -- BIDS metadata (after conversion)
    bids_suffixes JSONB,              -- ["T1w", "T2w", "dwi"] - what's actually in BIDS
    
    -- Metadata
    acquisition_date DATE,            -- From DICOM headers
    scanner_id VARCHAR(64),
    metadata JSONB,
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(subject_id, session_id)
);

CREATE INDEX idx_sessions_subject ON sessions(subject_id);
CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_sessions_discovered ON sessions(discovered_at);
CREATE INDEX idx_sessions_updated ON sessions(updated_at);
CREATE INDEX idx_sessions_acquisition ON sessions(acquisition_date);
```

### pipeline_runs

Tracks individual pipeline executions.

```sql
CREATE TABLE pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Foreign keys
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    subject_id INTEGER REFERENCES subjects(id) ON DELETE CASCADE,
    -- One of these will be set depending on pipeline level
    
    -- Pipeline identification
    pipeline_name VARCHAR(64) NOT NULL,     -- e.g., "freesurfer", "mriqc"
    pipeline_version VARCHAR(32),           -- e.g., "7.4.1"
    pipeline_level VARCHAR(16) NOT NULL,    -- "session" or "subject"
    
    -- For subject-level pipelines: which sessions were included
    sessions_included JSONB,                -- [session_id, session_id, ...]
    
    -- Execution tracking
    attempt_number INTEGER DEFAULT 1,
    
    -- Status
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    -- Values: pending, queued, running, completed, failed, cancelled, skipped
    
    -- Timing
    queued_at TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_seconds FLOAT,
    
    -- Results
    output_path VARCHAR(1024),
    exit_code INTEGER,
    error_message TEXT,
    error_traceback TEXT,
    
    -- Logs and metrics
    log_path VARCHAR(1024),
    metrics JSONB,                          -- Pipeline-specific metrics (QC scores, etc.)
    
    -- Celery integration
    celery_task_id VARCHAR(64),
    
    -- Trigger context (for subject-level pipelines)
    trigger_reason VARCHAR(32),             -- "new_session", "manual", "retry"
    trigger_session_id INTEGER REFERENCES sessions(id),
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_pipeline_runs_session ON pipeline_runs(session_id);
CREATE INDEX idx_pipeline_runs_subject ON pipeline_runs(subject_id);
CREATE INDEX idx_pipeline_runs_pipeline ON pipeline_runs(pipeline_name);
CREATE INDEX idx_pipeline_runs_status ON pipeline_runs(status);
CREATE INDEX idx_pipeline_runs_celery ON pipeline_runs(celery_task_id);
CREATE INDEX idx_pipeline_runs_queued ON pipeline_runs(queued_at);
```

### audit_log

Comprehensive audit trail of all state changes.

```sql
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Timestamp
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- What changed
    entity_type VARCHAR(32) NOT NULL,       -- subject, session, pipeline_run
    entity_id INTEGER NOT NULL,
    
    -- Change details
    action VARCHAR(64) NOT NULL,
    -- Actions: created, status_changed, validated, queued, started, 
    --          completed, failed, retried, cancelled, updated
    
    old_value TEXT,                         -- Previous value (JSON for complex)
    new_value TEXT,                         -- New value
    
    -- Context
    triggered_by VARCHAR(64),               -- system, user, watcher, scheduler, celery
    user_id VARCHAR(64),                    -- If user-initiated (CLI, API)
    
    -- Additional details
    message TEXT,                           -- Human-readable description
    details JSONB,                          -- Extra context
    
    -- Denormalized for easier querying
    subject_id INTEGER REFERENCES subjects(id),
    session_id INTEGER REFERENCES sessions(id)
);

CREATE INDEX idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_action ON audit_log(action);
CREATE INDEX idx_audit_subject ON audit_log(subject_id);
CREATE INDEX idx_audit_session ON audit_log(session_id);
```

---

## SQLAlchemy Models

```python
# neuroflow/models/base.py

from datetime import datetime
from sqlalchemy import Column, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """Adds created_at and updated_at columns."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
```

```python
# neuroflow/models/subject.py

from enum import Enum
from typing import Optional
from sqlalchemy import String, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class SubjectStatus(str, Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    VALID = "valid"
    INVALID = "invalid"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Subject(Base, TimestampMixin):
    __tablename__ = "subjects"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    recruitment_id: Mapped[Optional[str]] = mapped_column(String(128))
    
    status: Mapped[SubjectStatus] = mapped_column(default=SubjectStatus.PENDING)
    
    session_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_pipelines: Mapped[int] = mapped_column(Integer, default=0)
    failed_pipelines: Mapped[int] = mapped_column(Integer, default=0)
    
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    
    # Relationships
    sessions: Mapped[list["Session"]] = relationship(back_populates="subject")
    pipeline_runs: Mapped[list["PipelineRun"]] = relationship(back_populates="subject")
```

```python
# neuroflow/models/session.py

from enum import Enum
from datetime import datetime, date
from typing import Optional
from sqlalchemy import String, Integer, Boolean, DateTime, Date, ForeignKey, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class SessionStatus(str, Enum):
    DISCOVERED = "discovered"
    VALIDATING = "validating"
    VALIDATED = "validated"
    INVALID = "invalid"
    CONVERTING = "converting"
    CONVERTED = "converted"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXCLUDED = "excluded"


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    session_id: Mapped[str] = mapped_column(String(64))
    
    dicom_path: Mapped[Optional[str]] = mapped_column(String(1024))
    bids_path: Mapped[Optional[str]] = mapped_column(String(1024))
    
    discovered_at: Mapped[datetime] = mapped_column(DateTime)
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_dicom_modified: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    is_valid: Mapped[Optional[bool]] = mapped_column(Boolean)
    validation_message: Mapped[Optional[str]] = mapped_column(Text)
    scans_found: Mapped[Optional[dict]] = mapped_column(JSON)
    
    status: Mapped[SessionStatus] = mapped_column(default=SessionStatus.DISCOVERED)
    
    pipelines_pending: Mapped[int] = mapped_column(Integer, default=0)
    pipelines_completed: Mapped[int] = mapped_column(Integer, default=0)
    pipelines_failed: Mapped[int] = mapped_column(Integer, default=0)
    
    bids_suffixes: Mapped[Optional[list]] = mapped_column(JSON)
    
    acquisition_date: Mapped[Optional[date]] = mapped_column(Date)
    scanner_id: Mapped[Optional[str]] = mapped_column(String(64))
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    
    # Relationships
    subject: Mapped["Subject"] = relationship(back_populates="sessions")
    pipeline_runs: Mapped[list["PipelineRun"]] = relationship(back_populates="session")
```

```python
# neuroflow/models/pipeline_run.py

from enum import Enum
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class PipelineRunStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class PipelineRun(Base, TimestampMixin):
    __tablename__ = "pipeline_runs"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    
    session_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sessions.id"))
    subject_id: Mapped[Optional[int]] = mapped_column(ForeignKey("subjects.id"))
    
    pipeline_name: Mapped[str] = mapped_column(String(64))
    pipeline_version: Mapped[Optional[str]] = mapped_column(String(32))
    pipeline_level: Mapped[str] = mapped_column(String(16))  # "session" or "subject"
    
    sessions_included: Mapped[Optional[list]] = mapped_column(JSON)
    
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    
    status: Mapped[PipelineRunStatus] = mapped_column(default=PipelineRunStatus.PENDING)
    
    queued_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)
    
    output_path: Mapped[Optional[str]] = mapped_column(String(1024))
    exit_code: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    error_traceback: Mapped[Optional[str]] = mapped_column(Text)
    
    log_path: Mapped[Optional[str]] = mapped_column(String(1024))
    metrics: Mapped[Optional[dict]] = mapped_column(JSON)
    
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    
    trigger_reason: Mapped[Optional[str]] = mapped_column(String(32))
    trigger_session_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sessions.id"))
    
    # Relationships
    session: Mapped[Optional["Session"]] = relationship(
        back_populates="pipeline_runs", foreign_keys=[session_id]
    )
    subject: Mapped[Optional["Subject"]] = relationship(back_populates="pipeline_runs")
```

---

## Key Queries

### Find all failed pipeline runs with context

```sql
SELECT 
    pr.id,
    s.participant_id,
    sess.session_id,
    pr.pipeline_name,
    pr.error_message,
    pr.completed_at,
    pr.attempt_number
FROM pipeline_runs pr
JOIN subjects s ON pr.subject_id = s.id
LEFT JOIN sessions sess ON pr.session_id = sess.id
WHERE pr.status = 'failed'
ORDER BY pr.completed_at DESC
LIMIT 50;
```

### Find sessions pending processing

```sql
SELECT 
    s.participant_id,
    sess.session_id,
    sess.status,
    sess.discovered_at,
    sess.pipelines_pending
FROM sessions sess
JOIN subjects s ON sess.subject_id = s.id
WHERE sess.status IN ('validated', 'converted')
AND sess.pipelines_pending > 0
ORDER BY sess.discovered_at;
```

### Get subject processing summary

```sql
SELECT 
    s.participant_id,
    s.status,
    s.session_count,
    s.completed_pipelines,
    s.failed_pipelines,
    COUNT(DISTINCT pr.pipeline_name) as unique_pipelines_run
FROM subjects s
LEFT JOIN pipeline_runs pr ON s.id = pr.subject_id
GROUP BY s.id
ORDER BY s.updated_at DESC;
```

### Sessions ready for subject-level pipelines

```sql
-- Find subjects with 2+ sessions where all sessions have completed freesurfer
SELECT 
    s.participant_id,
    s.id as subject_id,
    COUNT(sess.id) as session_count
FROM subjects s
JOIN sessions sess ON s.id = sess.subject_id
WHERE sess.status = 'completed'
AND EXISTS (
    SELECT 1 FROM pipeline_runs pr 
    WHERE pr.session_id = sess.id 
    AND pr.pipeline_name = 'freesurfer' 
    AND pr.status = 'completed'
)
GROUP BY s.id
HAVING COUNT(sess.id) >= 2
AND NOT EXISTS (
    -- And longitudinal hasn't been run yet
    SELECT 1 FROM pipeline_runs pr2
    WHERE pr2.subject_id = s.id
    AND pr2.pipeline_name = 'longitudinal_freesurfer'
    AND pr2.status IN ('completed', 'running', 'queued')
);
```

### Audit trail for a session

```sql
SELECT 
    timestamp,
    action,
    old_value,
    new_value,
    triggered_by,
    message
FROM audit_log
WHERE entity_type = 'session'
AND entity_id = ?
ORDER BY timestamp;
```

### Processing statistics summary

```sql
SELECT
    -- Sessions by status
    (SELECT COUNT(*) FROM sessions WHERE status = 'discovered') as sessions_discovered,
    (SELECT COUNT(*) FROM sessions WHERE status = 'validated') as sessions_validated,
    (SELECT COUNT(*) FROM sessions WHERE status = 'processing') as sessions_processing,
    (SELECT COUNT(*) FROM sessions WHERE status = 'completed') as sessions_completed,
    (SELECT COUNT(*) FROM sessions WHERE status = 'failed') as sessions_failed,
    
    -- Pipeline runs by status
    (SELECT COUNT(*) FROM pipeline_runs WHERE status = 'pending') as runs_pending,
    (SELECT COUNT(*) FROM pipeline_runs WHERE status = 'running') as runs_running,
    (SELECT COUNT(*) FROM pipeline_runs WHERE status = 'completed') as runs_completed,
    (SELECT COUNT(*) FROM pipeline_runs WHERE status = 'failed') as runs_failed,
    
    -- Totals
    (SELECT COUNT(*) FROM subjects) as total_subjects,
    (SELECT COUNT(*) FROM sessions) as total_sessions;
```
