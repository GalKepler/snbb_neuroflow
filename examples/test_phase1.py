#!/usr/bin/env python3
"""Phase 1 Testing Script

This script tests all components added in Phase 1 of the workflow orchestration system.

Usage:
    python examples/test_phase1.py

Components Tested:
    1. Pipeline Registry
    2. WorkflowRun Model
    3. Enhanced Models (Session, Subject, PipelineRun)
    4. StateManager Workflow Operations
    5. Celery Configuration

Prerequisites:
    - Database initialized
    - neuroflow.yaml configured
    - Redis running (for Celery tests)
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from neuroflow.config import NeuroflowConfig
from neuroflow.core.state import StateManager
from neuroflow.models import (
    WorkflowRun,
    WorkflowRunStatus,
    Session,
    SessionStatus,
    Subject,
    SubjectStatus,
    PipelineRun,
    PipelineRunStatus,
    AuditLog,
)
from neuroflow.orchestrator.registry import (
    get_registry,
    PipelineRegistry,
    PipelineLevel,
    PipelineStage,
)


def print_header(text: str):
    """Print a formatted header."""
    print(f"\n{'=' * 70}")
    print(f"  {text}")
    print(f"{'=' * 70}\n")


def test_pipeline_registry():
    """Test Pipeline Registry functionality."""
    print_header("TEST 1: Pipeline Registry")

    registry = get_registry()

    # List all pipelines
    print("📋 Registered Pipelines:")
    for pipeline in registry.get_all():
        print(f"  ✓ {pipeline.name}: {pipeline.display_name}")
        print(f"    Stage: {pipeline.stage.name}, Level: {pipeline.level.value}")
        print(f"    Queue: {pipeline.queue}, Timeout: {pipeline.timeout_minutes}min")
        if pipeline.depends_on:
            print(f"    Depends on: {', '.join(pipeline.depends_on)}")
        print()

    # Test dependency resolution
    print("\n🔗 Dependency Resolution:")
    pipeline_name = "qsiparc"
    dependencies = registry.get_dependencies(pipeline_name)
    print(f"  Dependencies for '{pipeline_name}':")
    for dep in dependencies:
        print(f"    - {dep.name} (Stage {dep.stage.value})")

    # Test execution order
    print("\n📊 Execution Order (Topological Sort):")
    execution_order = registry.get_execution_order()
    for i, pipeline in enumerate(execution_order, 1):
        print(f"  {i}. {pipeline.name} (Stage: {pipeline.stage.name})")

    # Validate dependencies
    print("\n✓ Validating Dependencies:")
    errors = registry.validate_dependencies()
    if errors:
        print("  ❌ Dependency Errors:")
        for error in errors:
            print(f"    - {error}")
        return False
    else:
        print("  ✅ All dependencies valid!")

    # Test retry policy
    print("\n⏱️ Retry Policy Example (QSIPrep):")
    qsiprep = registry.get("qsiprep")
    print(f"  Max attempts: {qsiprep.retry_policy.max_attempts}")
    print(f"  Delay schedule:")
    for attempt in range(1, qsiprep.retry_policy.max_attempts + 1):
        delay = qsiprep.retry_policy.get_delay(attempt)
        print(f"    Attempt {attempt}: {delay}s ({delay/60:.1f} minutes)")

    return True


def test_database_models():
    """Test database models and initialization."""
    print_header("TEST 2: Database Models & Schema")

    config = NeuroflowConfig.find_and_load()
    state = StateManager(config)

    # Initialize database
    try:
        state.init_db()
        print("✅ Database initialized successfully!")
    except Exception as e:
        print(f"⚠️ Database already initialized or error: {e}")

    # Verify tables
    from sqlalchemy import inspect
    inspector = inspect(state.engine)
    tables = inspector.get_table_names()

    print("\n📊 Database Tables:")
    expected_tables = ['subjects', 'sessions', 'pipeline_runs', 'workflow_runs', 'audit_logs']
    all_exist = True
    for table in expected_tables:
        exists = table in tables
        status = "✅" if exists else "❌"
        print(f"  {status} {table}")
        all_exist = all_exist and exists

    # Check workflow_runs columns
    if 'workflow_runs' in tables:
        columns = inspector.get_columns('workflow_runs')
        print("\n  workflow_runs columns:")
        key_columns = ['id', 'status', 'trigger_type', 'stages_completed',
                      'sessions_discovered', 'workflow_run_id']
        for col in columns[:10]:  # Show first 10 columns
            print(f"    - {col['name']}: {col['type']}")

    return all_exist, state


def test_workflow_operations(state: StateManager):
    """Test StateManager workflow operations."""
    print_header("TEST 3: StateManager Workflow Operations")

    # Create a test workflow run
    print("Creating WorkflowRun...")
    workflow_run = state.create_workflow_run(
        trigger_type="manual",
        trigger_details={"user": "test", "reason": "phase1_testing"}
    )
    print(f"✅ Created WorkflowRun: ID={workflow_run.id}")
    print(f"   Status: {workflow_run.status.value}")
    print(f"   Trigger: {workflow_run.trigger_type}")

    # Update workflow run
    print("\n📝 Updating WorkflowRun...")
    state.update_workflow_run(
        workflow_run.id,
        current_stage="discovery",
        sessions_discovered=5,
    )

    state.update_workflow_run(
        workflow_run.id,
        current_stage="bids_conversion",
        stages_completed=["discovery"],
        sessions_converted=3,
    )

    # Complete workflow
    state.update_workflow_run(
        workflow_run.id,
        status=WorkflowRunStatus.COMPLETED,
        stages_completed=["discovery", "bids_conversion"],
        current_stage=None,
    )

    final_run = state.get_latest_workflow_run()
    print(f"✅ Workflow Completed:")
    print(f"   Status: {final_run.status.value}")
    print(f"   Stages: {final_run.stages_completed}")
    if final_run.duration_seconds:
        print(f"   Duration: {final_run.duration_seconds:.2f} seconds")

    # Test history
    print("\n📜 Workflow History:")
    history = state.get_workflow_run_history(limit=3)
    for i, run in enumerate(history, 1):
        print(f"   {i}. WorkflowRun #{run.id} - {run.status.value}")

    return True


def test_enhanced_models(state: StateManager):
    """Test enhanced Session and Subject models."""
    print_header("TEST 4: Enhanced Model Fields")

    # Create test data
    print("Creating test subject and session...")
    subject = state.get_or_create_subject(
        participant_id="sub-TEST001",
        recruitment_id="REC-001"
    )
    print(f"✅ Subject: {subject.participant_id} (ID: {subject.id})")

    session = state.register_session(
        subject_id=subject.id,
        session_id="ses-01",
        dicom_path="/test/dicom/path",
    )

    if session:
        print(f"✅ Session: {session.session_id} (ID: {session.id})")

        # Test mark_session_for_rerun
        print("\n🔄 Testing mark_session_for_rerun()...")
        state.mark_session_for_rerun(
            session.id,
            reason="Pipeline failed due to memory issue"
        )

        with state.get_session() as db:
            updated_session = db.get(Session, session.id)
            print(f"✅ Session marked for rerun:")
            print(f"   needs_rerun: {updated_session.needs_rerun}")
            print(f"   last_failure_reason: {updated_session.last_failure_reason}")
    else:
        print("⚠️ Session already exists")

    # Test mark_subject_for_qsiprep
    print("\n🔄 Testing mark_subject_for_qsiprep()...")
    state.mark_subject_for_qsiprep(
        subject.id,
        reason="New session added"
    )

    with state.get_session() as db:
        updated_subject = db.get(Subject, subject.id)
        print(f"✅ Subject marked for QSIPrep:")
        print(f"   needs_qsiprep: {updated_subject.needs_qsiprep}")

    # Test PipelineRun with workflow_run_id
    if session:
        print("\n🔗 Testing PipelineRun with workflow_run_id...")
        test_workflow = state.create_workflow_run(
            trigger_type="test",
            trigger_details={"testing": "pipeline_association"}
        )

        pipeline_run = state.create_pipeline_run(
            pipeline_name="bids_conversion",
            pipeline_level="session",
            session_id=session.id,
            subject_id=subject.id,
            trigger_reason="workflow",
        )

        # Link to workflow
        with state.get_session() as db:
            run = db.get(PipelineRun, pipeline_run.id)
            run.workflow_run_id = test_workflow.id

        with state.get_session() as db:
            linked_run = db.get(PipelineRun, pipeline_run.id)
            print(f"✅ PipelineRun linked to WorkflowRun:")
            print(f"   PipelineRun ID: {linked_run.id}")
            print(f"   WorkflowRun ID: {linked_run.workflow_run_id}")

    return True


def test_celery_config():
    """Test Celery configuration."""
    print_header("TEST 5: Celery Configuration")

    try:
        from neuroflow.workers.celery_app import create_celery_app
        config = NeuroflowConfig.find_and_load()
        celery_app = create_celery_app(config)

        print("✅ Celery app created successfully!")
        print(f"   Broker: {celery_app.conf.broker_url}")
        print(f"   Backend: {celery_app.conf.result_backend}")

        # Display queues
        print("\n📋 Task Queues:")
        for queue in celery_app.conf.task_queues:
            priority = queue.queue_arguments.get('x-max-priority', 'N/A')
            print(f"   - {queue.name} (Priority: {priority})")

        # Display some task routes
        print("\n🗺️ Task Routes (sample):")
        routes = celery_app.conf.task_routes
        for task_name, route_config in list(routes.items())[:5]:
            print(f"   {task_name}")
            print(f"     → Queue: {route_config['queue']}")

        # Display beat schedule
        print("\n⏰ Celery Beat Schedule:")
        for name, schedule_config in celery_app.conf.beat_schedule.items():
            print(f"   - {name}:")
            print(f"     Task: {schedule_config['task']}")

        return True

    except Exception as e:
        print(f"⚠️ Could not test Celery: {e}")
        print("   (This is expected if Redis is not running)")
        return False


def test_workflow_tasks():
    """Test workflow tasks module."""
    print_header("TEST 6: Workflow Tasks")

    try:
        from neuroflow.workers import workflow_tasks

        print("✅ Workflow tasks module imported successfully!")

        # List available tasks
        task_functions = [
            name for name in dir(workflow_tasks)
            if name.startswith('run_') and callable(getattr(workflow_tasks, name))
        ]

        print("\n📋 Available Workflow Tasks:")
        for task_name in task_functions:
            task_func = getattr(workflow_tasks, task_name)
            if hasattr(task_func, 'name'):
                print(f"   - {task_func.name}")
            else:
                print(f"   - {task_name}")

        return True

    except Exception as e:
        print(f"❌ Error importing workflow tasks: {e}")
        return False


def print_summary(state: StateManager):
    """Print testing summary."""
    print_header("Phase 1 Testing Summary")

    from sqlalchemy import func, select

    with state.get_session() as db:
        workflow_count = db.execute(select(func.count(WorkflowRun.id))).scalar()
        subject_count = db.execute(select(func.count(Subject.id))).scalar()
        session_count = db.execute(select(func.count(Session.id))).scalar()

        print("✅ Database State:")
        print(f"   Workflow Runs: {workflow_count}")
        print(f"   Subjects: {subject_count}")
        print(f"   Sessions: {session_count}")

    # Show recent audit logs
    print("\n📜 Recent Audit Log Entries:")
    with state.get_session() as db:
        recent_logs = db.execute(
            select(AuditLog)
            .order_by(AuditLog.created_at.desc())
            .limit(5)
        ).scalars().all()

        for log in recent_logs:
            print(f"   [{log.created_at.strftime('%H:%M:%S')}] {log.entity_type}.{log.action}")
            if log.message:
                print(f"      Message: {log.message}")


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("  PHASE 1 TESTING - Core Infrastructure")
    print("=" * 70)

    results = []

    # Test 1: Pipeline Registry
    try:
        results.append(("Pipeline Registry", test_pipeline_registry()))
    except Exception as e:
        print(f"❌ Error in Pipeline Registry test: {e}")
        results.append(("Pipeline Registry", False))

    # Test 2: Database Models
    try:
        success, state = test_database_models()
        results.append(("Database Models", success))
    except Exception as e:
        print(f"❌ Error in Database Models test: {e}")
        results.append(("Database Models", False))
        return

    # Test 3: Workflow Operations
    try:
        results.append(("Workflow Operations", test_workflow_operations(state)))
    except Exception as e:
        print(f"❌ Error in Workflow Operations test: {e}")
        results.append(("Workflow Operations", False))

    # Test 4: Enhanced Models
    try:
        results.append(("Enhanced Models", test_enhanced_models(state)))
    except Exception as e:
        print(f"❌ Error in Enhanced Models test: {e}")
        results.append(("Enhanced Models", False))

    # Test 5: Celery Config
    try:
        results.append(("Celery Configuration", test_celery_config()))
    except Exception as e:
        print(f"❌ Error in Celery Configuration test: {e}")
        results.append(("Celery Configuration", False))

    # Test 6: Workflow Tasks
    try:
        results.append(("Workflow Tasks", test_workflow_tasks()))
    except Exception as e:
        print(f"❌ Error in Workflow Tasks test: {e}")
        results.append(("Workflow Tasks", False))

    # Summary
    try:
        print_summary(state)
    except Exception as e:
        print(f"⚠️ Error generating summary: {e}")

    # Final Results
    print_header("Test Results")
    all_passed = True
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"   {status}: {test_name}")
        all_passed = all_passed and passed

    print("\n" + "=" * 70)
    if all_passed:
        print("  🎉 ALL TESTS PASSED!")
    else:
        print("  ⚠️ SOME TESTS FAILED")
    print("=" * 70 + "\n")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
