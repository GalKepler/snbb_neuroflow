# Testing Strategy

## Overview

This document describes the testing approach for neuroflow workflow automation, including unit tests, integration tests, and end-to-end testing.

## Test Structure

```
tests/
├── conftest.py                 # Shared fixtures
├── unit/
│   ├── test_registry.py       # Pipeline registry tests
│   ├── test_scheduler.py      # Workflow scheduler tests
│   ├── test_retry.py          # Retry logic tests
│   └── test_state.py          # State manager tests
├── integration/
│   ├── test_workflow.py       # Full workflow tests
│   └── test_celery_tasks.py   # Task execution tests
└── e2e/
    └── test_complete_workflow.py
```

## Shared Fixtures

### File: `tests/conftest.py`

```python
"""Shared test fixtures."""

import tempfile
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from neuroflow.config import NeuroflowConfig
from neuroflow.models.base import Base


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_config(temp_dir: Path) -> NeuroflowConfig:
    """Provide a test configuration."""
    config_data = {
        "paths": {
            "dicom_root": str(temp_dir / "dicom"),
            "bids_root": str(temp_dir / "bids"),
            "derivatives_root": str(temp_dir / "derivatives"),
            "log_dir": str(temp_dir / "logs"),
        },
        "database": {"url": f"sqlite:///{temp_dir}/test.db"},
        "redis": {"url": "redis://localhost:6379/15"},
    }
    
    for key in ["dicom_root", "bids_root", "derivatives_root", "log_dir"]:
        Path(config_data["paths"][key]).mkdir(parents=True, exist_ok=True)
    
    return NeuroflowConfig.from_dict(config_data)


@pytest.fixture
def db_engine(test_config: NeuroflowConfig):
    """Create a test database engine."""
    engine = create_engine(test_config.database.url, echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    """Provide a database session for tests."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def state_manager(test_config: NeuroflowConfig, db_engine):
    """Provide a StateManager for tests."""
    from neuroflow.core.state import StateManager
    return StateManager(test_config, engine=db_engine)


@pytest.fixture
def registry():
    """Provide a fresh pipeline registry."""
    from neuroflow.orchestrator.registry import PipelineRegistry
    return PipelineRegistry()


@pytest.fixture
def sample_subject(state_manager):
    """Create a sample subject for testing."""
    return state_manager.create_subject(
        subject_label="sub-001",
        dicom_path="/data/dicom/sub-001",
    )


@pytest.fixture
def sample_session(state_manager, sample_subject):
    """Create a sample session for testing."""
    return state_manager.create_session(
        subject_id=sample_subject.id,
        session_label="ses-01",
        dicom_path="/data/dicom/sub-001/ses-01",
    )
```

## Unit Tests

### File: `tests/unit/test_registry.py`

```python
"""Tests for the pipeline registry."""

import pytest

from neuroflow.orchestrator.registry import (
    DependencyError,
    PipelineDefinition,
    PipelineLevel,
    PipelineRegistry,
    PipelineStage,
    RetryPolicy,
)


class TestPipelineRegistry:
    """Tests for PipelineRegistry."""
    
    def test_default_pipelines_registered(self, registry):
        """Default pipelines should be registered on init."""
        assert registry.get("bids_conversion") is not None
        assert registry.get("qsiprep") is not None
        assert registry.get("qsirecon") is not None
        assert registry.get("qsiparc") is not None
    
    def test_get_by_stage(self, registry):
        """Should filter pipelines by stage."""
        bids_pipelines = registry.get_by_stage(PipelineStage.BIDS_CONVERSION)
        assert len(bids_pipelines) == 1
        assert bids_pipelines[0].name == "bids_conversion"
    
    def test_get_by_level(self, registry):
        """Should filter pipelines by level."""
        subject_pipelines = registry.get_by_level(PipelineLevel.SUBJECT)
        names = [p.name for p in subject_pipelines]
        assert "qsiprep" in names
        assert "qsirecon" not in names
    
    def test_get_dependencies(self, registry):
        """Should resolve dependencies correctly."""
        deps = registry.get_dependencies("qsirecon")
        dep_names = [d.name for d in deps]
        assert "qsiprep" in dep_names
        assert "bids_conversion" in dep_names
    
    def test_execution_order(self, registry):
        """Should return correct execution order."""
        order = registry.get_execution_order()
        names = [p.name for p in order]
        
        assert names.index("bids_conversion") < names.index("qsiprep")
        assert names.index("qsiprep") < names.index("qsirecon")
        assert names.index("qsirecon") < names.index("qsiparc")
    
    def test_circular_dependency_detection(self, registry):
        """Should detect circular dependencies."""
        registry.register(PipelineDefinition(
            name="circular_a",
            display_name="Circular A",
            stage=PipelineStage.RECONSTRUCTION,
            level=PipelineLevel.SESSION,
            runner="test.run",
            depends_on=["circular_b"],
        ))
        registry.register(PipelineDefinition(
            name="circular_b",
            display_name="Circular B",
            stage=PipelineStage.RECONSTRUCTION,
            level=PipelineLevel.SESSION,
            runner="test.run",
            depends_on=["circular_a"],
        ))
        
        with pytest.raises(DependencyError):
            registry.get_execution_order(enabled_only=False)


class TestRetryPolicy:
    """Tests for RetryPolicy."""
    
    def test_exponential_backoff(self):
        """Should apply exponential backoff."""
        policy = RetryPolicy(
            initial_delay_seconds=60,
            max_delay_seconds=3600,
            exponential_backoff=True,
            jitter=False,
        )
        
        assert policy.get_delay(1) == 60
        assert policy.get_delay(2) == 120
        assert policy.get_delay(3) == 240
    
    def test_max_delay_cap(self):
        """Should cap delay at max_delay_seconds."""
        policy = RetryPolicy(
            initial_delay_seconds=1000,
            max_delay_seconds=2000,
            exponential_backoff=True,
            jitter=False,
        )
        
        assert policy.get_delay(5) == 2000
```

### File: `tests/unit/test_error_classifier.py`

```python
"""Tests for error classification."""

import pytest

from neuroflow.core.error_classifier import classify_error
from neuroflow.core.retry import (
    ConfigurationError,
    ResourceError,
    TransientError,
    ValidationError,
)


class TestErrorClassifier:
    """Tests for error classification."""
    
    @pytest.mark.parametrize("error_text,expected_class", [
        ("Connection refused", TransientError),
        ("Cannot allocate memory", ResourceError),
        ("Invalid BIDS dataset", ValidationError),
        ("Config file not found", ConfigurationError),
    ])
    def test_pattern_classification(self, error_text, expected_class):
        """Should classify known error patterns correctly."""
        exc = Exception(error_text)
        result = classify_error(exc)
        assert result == expected_class
    
    def test_oom_exit_code(self):
        """Should classify OOM killer exit code."""
        result = classify_error(Exception("Process died"), exit_code=137)
        assert result == ResourceError
```

## Integration Tests

### File: `tests/integration/test_workflow.py`

```python
"""Integration tests for workflow execution."""

import pytest
from unittest.mock import patch

from neuroflow.models import SessionStatus
from neuroflow.orchestrator.scheduler import WorkflowScheduler


class TestWorkflowScheduler:
    """Integration tests for WorkflowScheduler."""
    
    @pytest.fixture
    def scheduler(self, test_config, state_manager):
        return WorkflowScheduler(test_config, state_manager=state_manager)
    
    def test_get_sessions_for_bids(self, scheduler, state_manager, sample_session):
        """Should identify sessions needing BIDS conversion."""
        state_manager.update_session(sample_session.id, status=SessionStatus.VALIDATED)
        
        sessions = scheduler._get_sessions_for_bids_conversion()
        assert len(sessions) == 1
        assert sessions[0].id == sample_session.id
    
    @patch("neuroflow.orchestrator.scheduler.run_bids_conversion")
    def test_run_bids_stage(self, mock_task, scheduler, state_manager, sample_session):
        """Should queue BIDS conversion tasks."""
        state_manager.update_session(sample_session.id, status=SessionStatus.VALIDATED)
        workflow_run = state_manager.create_workflow_run(trigger_type="test")
        
        result = scheduler._run_bids_conversion_stage(workflow_run.id)
        
        assert result.success
        assert result.tasks_queued == 1
        mock_task.delay.assert_called_once()
    
    def test_dry_run(self, scheduler, state_manager, sample_session):
        """Dry run should not create actual tasks."""
        state_manager.update_session(sample_session.id, status=SessionStatus.VALIDATED)
        
        result = scheduler.run_workflow(dry_run=True)
        
        assert result.workflow_run_id is None or result.status.value != "running"
```

## Running Tests

```bash
# Run all tests
pytest

# Run unit tests only
pytest tests/unit/

# Run with coverage
pytest --cov=neuroflow --cov-report=html

# Run specific test
pytest tests/unit/test_registry.py::TestPipelineRegistry::test_get_by_stage

# Run parallel
pytest -n auto
```

## pytest.ini

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*

markers =
    unit: Unit tests
    integration: Integration tests
    e2e: End-to-end tests

addopts = --strict-markers -v --tb=short
```
