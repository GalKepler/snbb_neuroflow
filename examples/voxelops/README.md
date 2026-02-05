# VoxelOps Examples

This directory contains example scripts demonstrating how to use VoxelOps neuroimaging pipelines with neuroflow.

## Prerequisites

1. **Install VoxelOps**:
   ```bash
   pip install git+https://github.com/yalab-dev/VoxelOps.git
   ```

2. **Configure neuroflow**: Set up `neuroflow.yaml` with VoxelOps pipeline configurations (see `../../configs/neuroflow.example.yaml`)

3. **Prepare data**: Ensure DICOM data is discovered and validated in neuroflow database

4. **FreeSurfer license**: Obtain and configure license for QSIPrep/QSIRecon

## Example Scripts

### 01_bids_conversion.py

Convert DICOM files to BIDS format using HeudiConv.

**Single session**:
```bash
python 01_bids_conversion.py --session-id 1
```

**All validated sessions**:
```bash
python 01_bids_conversion.py --all
```

**Requirements**:
- Heuristic file configured in `neuroflow.yaml`
- DICOM data in neuroflow database

### 02_qsiprep_pipeline.py

Preprocess diffusion MRI data with QSIPrep.

**Single session**:
```bash
python 02_qsiprep_pipeline.py --session-id 1
```

**All sessions with DWI data**:
```bash
python 02_qsiprep_pipeline.py --all
```

**With custom resources**:
```bash
python 02_qsiprep_pipeline.py --session-id 1 --nprocs 16 --mem-mb 32000
```

**Force reprocessing**:
```bash
python 02_qsiprep_pipeline.py --session-id 1 --force
```

**Requirements**:
- BIDS-formatted data with DWI sequences
- FreeSurfer license configured

### 03_complete_workflow.py

Run the complete diffusion MRI workflow end-to-end:
1. BIDS conversion
2. QSIPrep preprocessing
3. QSIRecon reconstruction
4. QSIParc parcellation

**Basic usage**:
```bash
python 03_complete_workflow.py --session-id 1
```

**Force reprocessing all steps**:
```bash
python 03_complete_workflow.py --session-id 1 --force
```

**Without saving report**:
```bash
python 03_complete_workflow.py --session-id 1 --no-report
```

**Features**:
- Automatic progression through all pipeline stages
- Skips steps with existing outputs (unless `--force`)
- Saves detailed workflow report
- Comprehensive error handling

## Jupyter Notebook

### voxelops_tutorial.ipynb

Interactive tutorial demonstrating:
- Configuration and setup
- Running individual pipelines
- Monitoring progress
- Inspecting results
- Visualization of outputs

**Launch notebook**:
```bash
jupyter notebook voxelops_tutorial.ipynb
```

## Configuration Example

Minimal `neuroflow.yaml` configuration for VoxelOps:

```yaml
paths:
  dicom_incoming: /data/dicom
  bids_root: /data/bids
  derivatives: /data/derivatives
  work_dir: /data/work

pipelines:
  bids_conversion:
    enabled: true
    tool: "heudiconv"
    voxelops_config:
      heuristic: "/etc/neuroflow/heuristics/my_heuristic.py"
      bids_validator: true

  session_level:
    - name: "qsiprep"
      enabled: true
      runner: "voxelops.runners.qsiprep.run_qsiprep"
      timeout_minutes: 720
      voxelops_config:
        nprocs: 8
        mem_mb: 16000
        fs_license: "/opt/freesurfer/license.txt"
      requirements:
        bids_suffixes: ["dwi"]

  subject_level:
    - name: "qsirecon"
      enabled: true
      runner: "voxelops.runners.qsirecon.run_qsirecon"
      timeout_minutes: 480
      voxelops_config:
        nprocs: 8
        mem_mb: 16000
        fs_license: "/opt/freesurfer/license.txt"
```

## Common Issues

### VoxelOps Not Found
```
ModuleNotFoundError: No module named 'voxelops'
```
**Solution**: Install VoxelOps
```bash
pip install git+https://github.com/yalab-dev/VoxelOps.git
```

### Missing Heuristic
```
SchemaValidationError: Heuristic file not found
```
**Solution**: Create heuristic file and update `neuroflow.yaml`

### FreeSurfer License Missing
```
Error: No FreeSurfer license found
```
**Solution**:
1. Get license from https://surfer.nmr.mgh.harvard.edu/registration.html
2. Place at path specified in config

### Insufficient Resources
```
MemoryError or process killed
```
**Solution**: Increase resources
```bash
python 02_qsiprep_pipeline.py --session-id 1 --nprocs 16 --mem-mb 64000
```

## Additional Resources

- [VoxelOps Usage Guide](../../docs/voxelops-usage.md)
- [VoxelOps API Reference](../../docs/api/voxelops-api.md)
- [VoxelOps Integration Plan](../../docs/voxelops-integration-plan.md)

## Getting Help

1. Check the [usage guide](../../docs/voxelops-usage.md) for detailed documentation
2. Review logs in `/var/log/neuroflow/`
3. Enable debug logging: `logging.level: DEBUG` in config
4. Report issues with full error messages and configuration
