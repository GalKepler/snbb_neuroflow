# Phase 1 Testing Guide

This guide explains how to test the Phase 1 core infrastructure components.

## Prerequisites

### 1. Install Dependencies
```bash
pip install -e .
```

### 2. Configure Database
Ensure your `neuroflow.yaml` has a database configured:
```yaml
database:
  url: "sqlite:///./neuroflow.db"  # Or PostgreSQL URL
```

### 3. (Optional) Start Redis
For Celery testing:
```bash
# Using Docker
docker run -d -p 6379:6379 redis:7-alpine

# Or using system package manager
sudo systemctl start redis
```

## Testing Options

### Option 1: Interactive Notebook (Recommended)

The notebook provides step-by-step testing with detailed explanations:

```bash
cd /home/galkepler/Projects/neuroflow
jupyter notebook examples/phase1_testing.ipynb
```

**What it tests:**
- Pipeline Registry functionality
- Database schema and models
- Workflow operations
- Enhanced model fields
- Celery configuration
- Audit logging

**Benefits:**
- See each test result immediately
- Modify and rerun individual cells
- Great for exploring and debugging

### Option 2: Automated Script

Quick automated testing from command line:

```bash
cd /home/galkepler/Projects/neuroflow
python examples/test_phase1.py
```

**Output:**
```
======================================================================
  PHASE 1 TESTING - Core Infrastructure
======================================================================

======================================================================
  TEST 1: Pipeline Registry
======================================================================

📋 Registered Pipelines:
  ✓ bids_conversion: BIDS Conversion (HeudiConv)
    Stage: BIDS_CONVERSION, Level: session
    Queue: bids, Timeout: 60min
...

======================================================================
  Test Results
======================================================================
   ✅ PASS: Pipeline Registry
   ✅ PASS: Database Models
   ✅ PASS: Workflow Operations
   ✅ PASS: Enhanced Models
   ✅ PASS: Celery Configuration
   ✅ PASS: Workflow Tasks

======================================================================
  🎉 ALL TESTS PASSED!
======================================================================
```

## What Gets Tested

### 1. Pipeline Registry
- ✅ All pipelines registered (bids_conversion, qsiprep, qsirecon, qsiparc)
- ✅ Dependency resolution
- ✅ Topological sort (execution order)
- ✅ Circular dependency detection
- ✅ Retry policies
- ✅ Resource requirements

### 2. Database Schema
- ✅ workflow_runs table created
- ✅ New columns in sessions (needs_rerun, last_failure_reason, etc.)
- ✅ New columns in subjects (needs_qsiprep, etc.)
- ✅ workflow_run_id in pipeline_runs
- ✅ All indexes created

### 3. WorkflowRun Model
- ✅ Create workflow runs
- ✅ Update workflow status
- ✅ Track stages and metrics
- ✅ Query workflow history
- ✅ Duration calculation

### 4. StateManager Operations
- ✅ create_workflow_run()
- ✅ update_workflow_run()
- ✅ get_latest_workflow_run()
- ✅ get_workflow_run_history()
- ✅ mark_session_for_rerun()
- ✅ mark_subject_for_qsiprep()

### 5. Enhanced Models
- ✅ Session.needs_rerun flag
- ✅ Session.last_failure_reason
- ✅ Subject.needs_qsiprep flag
- ✅ PipelineRun.workflow_run_id link

### 6. Celery Configuration
- ✅ Multiple task queues with priorities
- ✅ Task routing
- ✅ Beat schedule
- ✅ Worker settings

### 7. Workflow Tasks
- ✅ run_master_workflow task
- ✅ Stage-specific tasks
- ✅ Task registration
- ✅ Proper queue routing

## Troubleshooting

### Database Errors
```bash
# Reset database if needed
rm neuroflow.db
python -c "from neuroflow.core.state import StateManager; from neuroflow.config import NeuroflowConfig; StateManager(NeuroflowConfig.find_and_load()).init_db()"
```

### Redis Not Running
If Redis is not running, Celery tests will be skipped with a warning:
```
⚠️ Could not test Celery: [Errno 111] Connection refused
   (This is expected if Redis is not running)
```

This is **OK** - the other tests will still run.

### Import Errors
Make sure neuroflow is installed in development mode:
```bash
pip install -e .
```

## Next Steps After Testing

Once all tests pass:

1. **Run the migration** (when using PostgreSQL):
   ```bash
   alembic upgrade head
   ```

2. **Test the Celery worker**:
   ```bash
   # Terminal 1: Start Redis
   docker run -d -p 6379:6379 redis:7-alpine

   # Terminal 2: Start worker
   neuroflow run worker

   # Terminal 3: Start beat scheduler
   neuroflow run beat
   ```

3. **Move to Phase 2**: Workflow Scheduler implementation

## Test Data Cleanup

The tests create sample data. To clean up:

```python
from neuroflow.core.state import StateManager
from neuroflow.config import NeuroflowConfig

state = StateManager(NeuroflowConfig.find_and_load())
state.drop_db()  # ⚠️ WARNING: This deletes ALL data!
state.init_db()  # Recreate empty database
```

## Questions or Issues?

If tests fail or you encounter issues:
1. Check the error messages carefully
2. Verify prerequisites are met
3. Check database configuration
4. Ensure all dependencies are installed
5. Review the test output for specific failures
