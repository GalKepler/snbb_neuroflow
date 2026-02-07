# How to Process Your DICOM Data

## Quick Answer: Use the Existing Scripts

You already have working pipeline scripts in `examples/voxelops/`. Phase 1 only added infrastructure - **it doesn't change how you run pipelines**.

## Step-by-Step: Process Your DICOM Sessions

### Prerequisites

1. **DICOM data discovered and registered**
   ```bash
   neuroflow scan discover
   ```

2. **Sessions validated**
   ```bash
   neuroflow scan list  # Check your sessions
   ```

### Option 1: Complete Workflow (Recommended)

Run all pipelines for a session automatically:

```bash
cd /home/galkepler/Projects/neuroflow

# Find your session ID
neuroflow scan list

# Run complete workflow
python examples/voxelops/03_complete_workflow.py \
  --session-id <SESSION_ID> \
  --config neuroflow.yaml
```

**What this does:**
1. BIDS conversion (HeudiConv)
2. QSIPrep preprocessing
3. QSIRecon reconstruction
4. QSIParc parcellation

**Example output:**
```
======================================================================
COMPLETE DIFFUSION MRI WORKFLOW
======================================================================
Subject: sub-001
Session: ses-01
Started: 2026-02-07 14:30:00
======================================================================

──────────────────────────────────────────────────────────────────────
Step: BIDS Conversion
──────────────────────────────────────────────────────────────────────
✓ BIDS Conversion - Success
  Duration: 2.3 minutes
  Output: /data/bids/sub-001/ses-01

──────────────────────────────────────────────────────────────────────
Step: QSIPrep Preprocessing
──────────────────────────────────────────────────────────────────────
✓ QSIPrep Preprocessing - Success
  Duration: 127.5 minutes
  Output: /data/derivatives/qsiprep/sub-001

...
```

### Option 2: Step-by-Step (Individual Pipelines)

Run each pipeline separately:

#### Step 1: BIDS Conversion
```bash
python examples/voxelops/01_bids_conversion.py \
  --session-id <SESSION_ID> \
  --config neuroflow.yaml
```

#### Step 2: QSIPrep Preprocessing
```bash
python examples/voxelops/02_qsiprep_pipeline.py \
  --session-id <SESSION_ID> \
  --config neuroflow.yaml
```

#### Step 3: Complete Remaining Steps
```bash
# After QSIPrep, run the complete workflow
# It will skip already-completed steps
python examples/voxelops/03_complete_workflow.py \
  --session-id <SESSION_ID>
```

### Option 3: Batch Processing

Process all sessions at once:

```bash
# List all sessions with DWI data
python examples/voxelops/02_qsiprep_pipeline.py --all

# Process all
python examples/voxelops/02_qsiprep_pipeline.py --all --config neuroflow.yaml
```

## Using the CLI (Simpler)

You can also use the neuroflow CLI:

```bash
# Run BIDS conversion
neuroflow run pipeline bids_conversion --session-id <ID>

# Run QSIPrep
neuroflow run pipeline qsiprep --session-id <ID>
```

## Check Progress

```bash
# See session status
neuroflow scan list

# See pipeline runs
neuroflow status pipelines

# Check specific session
neuroflow status session <SESSION_ID>
```

## What Phase 1 Added (Infrastructure Only)

Phase 1 added **background infrastructure** but doesn't change how you run pipelines:

✅ Pipeline Registry (pipeline definitions and dependencies)
✅ WorkflowRun tracking (for future automatic workflows)
✅ Enhanced state tracking (needs_rerun, etc.)
✅ Celery queues (for future task scheduling)

**You're still using the same manual scripts!**

## What's Coming in Phase 2: Automatic Workflows

Phase 2 will add the **WorkflowScheduler** that automatically:

1. **Discovers** new DICOM sessions
2. **Converts** them to BIDS
3. **Runs** QSIPrep when ready
4. **Processes** through QSIRecon and QSIParc
5. **Handles** failures and retries

**Once Phase 2 is complete:**
```bash
# Start the automated workflow system
neuroflow run worker    # Terminal 1
neuroflow run beat      # Terminal 2

# Then just drop DICOM files and everything happens automatically!
```

## Current Workflow (Manual)

```
Your DICOM Data
     ↓
neuroflow scan discover  ← Register sessions
     ↓
python 03_complete_workflow.py --session-id X  ← Manual execution
     ↓
✓ BIDS → QSIPrep → QSIRecon → QSIParc
```

## Future Workflow (Phase 2+)

```
Your DICOM Data
     ↓
Automatic Discovery (every hour)
     ↓
Automatic Workflow Scheduler (every 3 days)
     ↓
✓ BIDS → QSIPrep → QSIRecon → QSIParc
     ↑
All automatic, no manual intervention!
```

## Practical Example

Let's process your first session:

```bash
# 1. Discover your DICOM data
cd /home/galkepler/Projects/neuroflow
neuroflow scan discover

# 2. List sessions to get ID
neuroflow scan list

# Output:
# ID  Subject     Session  Status      Valid  Scans
# 1   sub-001     ses-01   discovered  True   T1w:1, dwi:2

# 3. Run complete workflow for session ID 1
python examples/voxelops/03_complete_workflow.py \
  --session-id 1 \
  --config neuroflow.yaml

# That's it! The script will run all 4 pipelines sequentially.
```

## Common Issues

### "Session not found"
```bash
# First register your DICOM data
neuroflow scan discover
```

### "No DWI data found"
```bash
# Validate your protocol configuration
neuroflow scan validate --session-id <ID>
```

### "VoxelOps not available"
```bash
# Install VoxelOps
pip install voxelops

# Or configure container mode in neuroflow.yaml
```

### "FreeSurfer license not found"
Get license from: https://surfer.nmr.mgh.harvard.edu/registration.html
Then configure in neuroflow.yaml

## Next Steps

1. **Now**: Use the existing scripts to process your data
2. **Soon**: Phase 2 will add automatic scheduling
3. **Later**: Phase 3+ will add retry logic, monitoring, etc.

## Questions?

- **"How do I see what's running?"** → `neuroflow status pipelines`
- **"Can I run multiple sessions in parallel?"** → Not yet, Phase 2 will add this
- **"What if a pipeline fails?"** → Re-run with `--force` flag
- **"Where are the outputs?"** → Check `neuroflow.yaml` paths section

## Summary

**RIGHT NOW (Current State):**
```bash
python examples/voxelops/03_complete_workflow.py --session-id <ID>
```

**SOON (After Phase 2):**
```bash
neuroflow workflow run    # Automatic processing of all pending work
```

**The Phase 1 testing notebook was for developers to verify infrastructure, not for processing your data!**
