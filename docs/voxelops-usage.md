# VoxelOps Usage Guide

This guide provides comprehensive instructions for using VoxelOps neuroimaging pipelines within neuroflow.

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Configuration](#configuration)
- [BIDS Conversion with HeudiConv](#bids-conversion-with-heudiconv)
- [Diffusion Preprocessing with QSIPrep](#diffusion-preprocessing-with-qsiprep)
- [Diffusion Reconstruction with QSIRecon](#diffusion-reconstruction-with-qsirecon)
- [Parcellation with QSIParc](#parcellation-with-qsiparc)
- [Advanced Usage](#advanced-usage)
- [Troubleshooting](#troubleshooting)
- [Best Practices](#best-practices)

## Overview

VoxelOps is a neuroimaging pipeline framework that provides standardized interfaces for common neuroimaging tools. Neuroflow integrates with VoxelOps to provide:

- **Schema-based configuration** - Type-safe, validated pipeline parameters
- **Automated container management** - VoxelOps handles Docker/Singularity internally
- **Graceful fallback** - Falls back to container mode if VoxelOps unavailable
- **Database integration** - Automatic session/subject tracking

### Supported Pipelines

| Pipeline | Tool | Purpose | Level |
|----------|------|---------|-------|
| BIDS Conversion | HeudiConv | Convert DICOM to BIDS | Session |
| Diffusion Preprocessing | QSIPrep | Preprocess diffusion MRI | Session |
| Diffusion Reconstruction | QSIRecon | Reconstruct diffusion models | Subject |
| Parcellation | QSIParc | Extract connectivity matrices | Subject |

## Installation

### Install VoxelOps

```bash
# Install from GitHub
pip install git+https://github.com/yalab-dev/VoxelOps.git

# Or clone and install in development mode
git clone https://github.com/yalab-dev/VoxelOps.git
cd VoxelOps
pip install -e .
```

### Verify Installation

```bash
python -c "import voxelops; print('VoxelOps installed successfully')"
```

### Container Runtime

VoxelOps requires a container runtime (Docker, Singularity, or Apptainer):

```bash
# Check Docker
docker --version

# Check Apptainer
apptainer --version

# Check Singularity
singularity --version
```

Configure your preferred runtime in `neuroflow.yaml`:

```yaml
container_runtime: "apptainer"  # or "docker" or "singularity"
```

## Configuration

### Basic Structure

VoxelOps configuration is specified in the `voxelops_config` section of each pipeline:

```yaml
pipelines:
  bids_conversion:
    enabled: true
    tool: "heudiconv"
    timeout_minutes: 60
    voxelops_config:
      # VoxelOps-specific parameters here
      heuristic: "/path/to/heuristic.py"
      bids_validator: true
```

### Configuration Principles

1. **Isolation** - All VoxelOps parameters are in `voxelops_config`
2. **Validation** - Required parameters are validated before execution
3. **Defaults** - Sensible defaults are provided for optional parameters
4. **Overrides** - Runtime kwargs can override config values

## BIDS Conversion with HeudiConv

HeudiConv converts DICOM files to BIDS format using a heuristic file.

### Configuration

```yaml
pipelines:
  bids_conversion:
    enabled: true
    tool: "heudiconv"
    timeout_minutes: 60
    retries: 2
    voxelops_config:
      # REQUIRED: Path to heuristic file
      heuristic: "/etc/neuroflow/heuristics/my_heuristic.py"

      # OPTIONAL: Run BIDS validator after conversion
      bids_validator: true

      # OPTIONAL: Overwrite existing BIDS data
      overwrite: false

      # OPTIONAL: DICOM to NIfTI converter
      converter: "dcm2niix"

      # OPTIONAL: Docker image to use
      docker_image: "nipy/heudiconv:1.3.4"

      # OPTIONAL: Run post-processing steps
      post_process: true
```

### Heuristic File

The heuristic file defines how DICOM series map to BIDS filenames. Example:

```python
# /etc/neuroflow/heuristics/my_heuristic.py

def create_key(template, outtype=('nii.gz',), annotation_classes=None):
    if template is None or not template:
        raise ValueError('Template must be a valid format string')
    return template, outtype, annotation_classes


def infotodict(seqinfo):
    """Heuristic evaluator for determining which runs belong where."""

    # Define BIDS output templates
    t1w = create_key('sub-{subject}/ses-{session}/anat/sub-{subject}_ses-{session}_T1w')
    dwi = create_key('sub-{subject}/ses-{session}/dwi/sub-{subject}_ses-{session}_dir-{dir}_dwi')

    info = {t1w: [], dwi: []}

    for s in seqinfo:
        # Map T1-weighted scans
        if 'MPRAGE' in s.protocol_name:
            info[t1w].append(s.series_id)

        # Map diffusion scans
        elif 'DTI' in s.protocol_name or 'DWI' in s.protocol_name:
            # Determine phase encoding direction
            if 'AP' in s.protocol_name:
                direction = 'AP'
            elif 'PA' in s.protocol_name:
                direction = 'PA'
            else:
                direction = 'unknown'

            dwi_key = create_key(
                f'sub-{{subject}}/ses-{{session}}/dwi/sub-{{subject}}_ses-{{session}}_dir-{direction}_dwi'
            )
            if dwi_key not in info:
                info[dwi_key] = []
            info[dwi_key].append(s.series_id)

    return info
```

### Running BIDS Conversion

#### Via CLI

```bash
# Convert a specific session
neuroflow process session sub-001 baseline --pipeline bids_conversion

# Convert all pending sessions
neuroflow process pending --pipeline bids_conversion
```

#### Via Python API

```python
from neuroflow.adapters.voxelops import VoxelopsAdapter
from neuroflow.config import NeuroflowConfig

# Load configuration
config = NeuroflowConfig.from_yaml("neuroflow.yaml")

# Create adapter
adapter = VoxelopsAdapter(config)

# Run BIDS conversion for a session
result = adapter.run(
    "bids_conversion",
    session_id=1,  # Database session ID
)

# Check result
if result.success:
    print(f"BIDS conversion successful!")
    print(f"Output: {result.output_path}")
    print(f"Duration: {result.duration_seconds}s")
else:
    print(f"BIDS conversion failed: {result.error_message}")
```

### Output Structure

```
bids_root/
├── sub-001/
│   ├── ses-baseline/
│   │   ├── anat/
│   │   │   ├── sub-001_ses-baseline_T1w.nii.gz
│   │   │   └── sub-001_ses-baseline_T1w.json
│   │   └── dwi/
│   │       ├── sub-001_ses-baseline_dir-AP_dwi.nii.gz
│   │       ├── sub-001_ses-baseline_dir-AP_dwi.bval
│   │       ├── sub-001_ses-baseline_dir-AP_dwi.bvec
│   │       └── sub-001_ses-baseline_dir-AP_dwi.json
├── dataset_description.json
└── participants.tsv
```

## Diffusion Preprocessing with QSIPrep

QSIPrep preprocesses diffusion MRI data, including distortion correction, denoising, and registration.

### Configuration

```yaml
pipelines:
  session_level:
    - name: "qsiprep"
      enabled: true
      runner: "voxelops.runners.qsiprep.run_qsiprep"
      timeout_minutes: 720  # 12 hours
      voxelops_config:
        # REQUIRED: FreeSurfer license
        fs_license: "/opt/freesurfer/license.txt"

        # OPTIONAL: Number of CPUs
        nprocs: 8

        # OPTIONAL: Memory limit in MB
        mem_mb: 16000

        # OPTIONAL: Output resolution in mm
        output_resolution: 1.6

        # OPTIONAL: Anatomical template for registration
        anatomical_template: ["MNI152NLin2009cAsym"]

        # OPTIONAL: Docker image
        docker_image: "pennlinc/qsiprep:latest"

        # OPTIONAL: Force reprocessing even if outputs exist
        force: false

      requirements:
        # Only run on sessions with DWI data
        bids_suffixes: ["dwi"]
```

### Prerequisites

1. **BIDS-formatted data** with diffusion images
2. **FreeSurfer license** at specified path
3. **Sufficient compute resources** (8+ CPUs, 16+ GB RAM recommended)

### Running QSIPrep

#### Via CLI

```bash
# Process a specific session
neuroflow process session sub-001 baseline --pipeline qsiprep

# Process all sessions with DWI data
neuroflow process pending --pipeline qsiprep
```

#### Via Python API

```python
from neuroflow.adapters.voxelops import VoxelopsAdapter
from neuroflow.config import NeuroflowConfig

config = NeuroflowConfig.from_yaml("neuroflow.yaml")
adapter = VoxelopsAdapter(config)

# Run QSIPrep for a session
result = adapter.run(
    "qsiprep",
    session_id=1,
    nprocs=16,  # Override default
    mem_mb=32000,  # Override default
)

if result.success:
    print(f"QSIPrep completed in {result.duration_seconds / 60:.1f} minutes")
    print(f"Outputs: {result.output_path}")
else:
    print(f"QSIPrep failed: {result.error_message}")
```

### Output Structure

```
derivatives/qsiprep/
├── sub-001/
│   ├── ses-baseline/
│   │   ├── anat/
│   │   │   ├── sub-001_ses-baseline_space-T1w_desc-preproc_T1w.nii.gz
│   │   │   └── sub-001_ses-baseline_space-T1w_desc-brain_mask.nii.gz
│   │   └── dwi/
│   │       ├── sub-001_ses-baseline_space-T1w_desc-preproc_dwi.nii.gz
│   │       ├── sub-001_ses-baseline_space-T1w_desc-preproc_dwi.bval
│   │       ├── sub-001_ses-baseline_space-T1w_desc-preproc_dwi.bvec
│   │       └── sub-001_ses-baseline_space-T1w_confounds.tsv
├── dataset_description.json
└── logs/
```

## Diffusion Reconstruction with QSIRecon

QSIRecon reconstructs diffusion models and computes tractography from QSIPrep outputs.

### Configuration

```yaml
pipelines:
  subject_level:
    - name: "qsirecon"
      enabled: true
      runner: "voxelops.runners.qsirecon.run_qsirecon"
      timeout_minutes: 480  # 8 hours
      voxelops_config:
        # REQUIRED: FreeSurfer license
        fs_license: "/opt/freesurfer/license.txt"

        # OPTIONAL: Reconstruction specification
        # If not provided, uses QSIPrep defaults
        recon_spec: "/etc/neuroflow/specs/dsi_studio_gqi.yaml"

        # OPTIONAL: Number of CPUs
        nprocs: 8

        # OPTIONAL: Memory limit in MB
        mem_mb: 16000

        # OPTIONAL: Atlases for connectivity matrices
        atlases: ["Brainnetome246Ext", "AAL116", "Schaefer400"]

        # OPTIONAL: Docker image
        docker_image: "pennlinc/qsirecon:latest"

        # OPTIONAL: Force reprocessing
        force: false
```

### Reconstruction Specifications

QSIRecon uses YAML specifications to define reconstruction workflows. Example:

```yaml
# /etc/neuroflow/specs/dsi_studio_gqi.yaml
name: dsi_studio_gqi
space: T1w
atlases:
  - Brainnetome246Ext
  - AAL116

nodes:
  - name: dsi_studio_gqi
    software: DSI Studio
    action: reconstruction
    parameters:
      method: gqi
      scheme_balance: true
      check_btable: true
```

For more examples, see [QSIRecon documentation](https://qsirecon.readthedocs.io/).

### Running QSIRecon

#### Via CLI

```bash
# Reconstruct for a specific subject
neuroflow process subject sub-001 --pipeline qsirecon

# Reconstruct for all subjects with QSIPrep outputs
neuroflow process pending --pipeline qsirecon
```

#### Via Python API

```python
from neuroflow.adapters.voxelops import VoxelopsAdapter
from neuroflow.config import NeuroflowConfig

config = NeuroflowConfig.from_yaml("neuroflow.yaml")
adapter = VoxelopsAdapter(config)

# Run QSIRecon for a subject
result = adapter.run(
    "qsirecon",
    subject_id=1,
)

if result.success:
    print(f"QSIRecon completed!")
    print(f"Connectivity matrices: {result.output_path}")
```

### Output Structure

```
derivatives/qsirecon/
├── sub-001/
│   ├── ses-baseline/
│   │   └── dwi/
│   │       ├── sub-001_ses-baseline_space-T1w_desc-gqi_odf.nii.gz
│   │       ├── sub-001_ses-baseline_space-T1w_atlas-Brainnetome246_conndata-gqi.csv
│   │       └── sub-001_ses-baseline_space-T1w_atlas-AAL116_conndata-gqi.csv
```

## Parcellation with QSIParc

QSIParc extracts parcellated connectivity matrices from QSIRecon outputs.

### Configuration

```yaml
pipelines:
  subject_level:
    - name: "qsiparc"
      enabled: true
      runner: "voxelops.runners.qsiparc.run_qsiparc"
      timeout_minutes: 120
      voxelops_config:
        # OPTIONAL: Tissue mask to use
        mask: "gm"  # 'gm' (gray matter) or 'wm' (white matter)

        # OPTIONAL: Force reprocessing
        force: false

        # OPTIONAL: Number of parallel jobs
        n_jobs: 1

        # OPTIONAL: Number of processors per job
        n_procs: 1
```

### Running QSIParc

```bash
# Via CLI
neuroflow process subject sub-001 --pipeline qsiparc
```

```python
# Via Python
result = adapter.run("qsiparc", subject_id=1)
```

## Advanced Usage

### Chaining Pipelines

Process a complete diffusion workflow:

```python
from neuroflow.adapters.voxelops import VoxelopsAdapter
from neuroflow.config import NeuroflowConfig

config = NeuroflowConfig.from_yaml("neuroflow.yaml")
adapter = VoxelopsAdapter(config)

session_id = 1
subject_id = 1

# Step 1: BIDS conversion
print("Step 1: Converting DICOM to BIDS...")
result = adapter.run("bids_conversion", session_id=session_id)
if not result.success:
    raise RuntimeError(f"BIDS conversion failed: {result.error_message}")

# Step 2: QSIPrep preprocessing
print("Step 2: Running QSIPrep...")
result = adapter.run("qsiprep", session_id=session_id)
if not result.success:
    raise RuntimeError(f"QSIPrep failed: {result.error_message}")

# Step 3: QSIRecon reconstruction
print("Step 3: Running QSIRecon...")
result = adapter.run("qsirecon", subject_id=subject_id)
if not result.success:
    raise RuntimeError(f"QSIRecon failed: {result.error_message}")

# Step 4: QSIParc parcellation
print("Step 4: Running QSIParc...")
result = adapter.run("qsiparc", subject_id=subject_id)
if not result.success:
    raise RuntimeError(f"QSIParc failed: {result.error_message}")

print("Complete diffusion workflow finished successfully!")
```

### Runtime Parameter Overrides

Override configuration at runtime:

```python
# Override QSIPrep parameters
result = adapter.run(
    "qsiprep",
    session_id=1,
    nprocs=32,  # Use more CPUs
    mem_mb=64000,  # Use more memory
    output_resolution=1.0,  # Higher resolution
    force=True,  # Force reprocessing
)
```

### Handling Skipped Runs

VoxelOps skips processing if outputs already exist (unless `force=True`):

```python
result = adapter.run("qsiprep", session_id=1)

if result.success and result.metrics.get("skipped"):
    print(f"QSIPrep outputs already exist")
    print(f"Reason: {result.metrics['reason']}")
    print(f"Output path: {result.output_path}")
else:
    print(f"QSIPrep processing completed")
```

### Custom Heuristics for Different Scanners

Organize heuristics by scanner or protocol:

```yaml
pipelines:
  bids_conversion:
    voxelops_config:
      # Use scanner-specific heuristic
      heuristic: "/etc/neuroflow/heuristics/siemens_prisma.py"
```

```python
# Dynamically select heuristic
def get_heuristic_for_session(session):
    scanner_model = session.metadata_.get("scanner_model")

    if "Prisma" in scanner_model:
        return "/etc/neuroflow/heuristics/siemens_prisma.py"
    elif "Skyra" in scanner_model:
        return "/etc/neuroflow/heuristics/siemens_skyra.py"
    else:
        return "/etc/neuroflow/heuristics/default.py"

# Use in adapter call
result = adapter.run(
    "bids_conversion",
    session_id=session_id,
    heuristic=get_heuristic_for_session(session),
)
```

## Troubleshooting

### VoxelOps Not Found

**Problem**: `voxelops.not_available` warning in logs

**Solution**:
```bash
# Install VoxelOps
pip install git+https://github.com/yalab-dev/VoxelOps.git

# Verify installation
python -c "import voxelops; print('OK')"
```

### Missing Heuristic File

**Problem**: `SchemaValidationError: Heuristic file not found`

**Solution**:
```bash
# Check heuristic path
ls -l /etc/neuroflow/heuristics/my_heuristic.py

# Update configuration with correct path
vim neuroflow.yaml
```

### FreeSurfer License Missing

**Problem**: QSIPrep/QSIRecon fails with license error

**Solution**:
```bash
# Obtain FreeSurfer license from https://surfer.nmr.mgh.harvard.edu/registration.html
# Place license file at configured path
sudo cp license.txt /opt/freesurfer/license.txt

# Verify
cat /opt/freesurfer/license.txt
```

### Container Runtime Issues

**Problem**: Docker/Singularity/Apptainer errors

**Solution**:
```bash
# Test container runtime
apptainer run docker://nipy/heudiconv:1.3.4 --version

# Check permissions
groups  # Should include docker or apptainer group

# Configure runtime in neuroflow.yaml
container_runtime: "apptainer"
```

### Insufficient Resources

**Problem**: Pipeline fails with memory/CPU errors

**Solution**:
```yaml
# Increase resources in configuration
voxelops_config:
  nprocs: 16  # Increase CPUs
  mem_mb: 32000  # Increase memory

# Or override at runtime
result = adapter.run("qsiprep", session_id=1, mem_mb=64000)
```

### Pipeline Outputs Already Exist

**Problem**: VoxelOps skips processing

**Solution**:
```yaml
# Force reprocessing in configuration
voxelops_config:
  force: true

# Or override at runtime
result = adapter.run("qsiprep", session_id=1, force=True)
```

## Best Practices

### Resource Management

1. **Scale appropriately**: Match `nprocs` and `mem_mb` to your hardware
2. **Monitor usage**: Use `htop` or similar to watch resource consumption
3. **Set timeouts**: Configure realistic `timeout_minutes` for each pipeline

### Data Organization

1. **Use BIDS**: Follow BIDS conventions strictly for maximum compatibility
2. **Validate early**: Run BIDS validator after conversion
3. **Track versions**: Document tool versions in `dataset_description.json`

### Error Handling

1. **Check results**: Always verify `result.success` before proceeding
2. **Log errors**: Capture `result.error_message` and `result.logs`
3. **Implement retries**: Use `retries` configuration for transient failures

### Testing

1. **Test heuristics**: Convert a single session before batch processing
2. **Dry runs**: Use `force=False` to avoid reprocessing
3. **Incremental processing**: Process one subject end-to-end before scaling

### Performance Optimization

1. **Parallel processing**: Use Celery for parallel session processing
2. **Batch subjects**: Process multiple sessions concurrently
3. **Resource allocation**: Balance `nprocs` across concurrent jobs

### Configuration Management

1. **Version control**: Keep `neuroflow.yaml` in git
2. **Environment-specific**: Use separate configs for dev/prod
3. **Document changes**: Comment configuration choices

## Additional Resources

- [VoxelOps Documentation](https://github.com/yalab-dev/VoxelOps)
- [QSIPrep Documentation](https://qsiprep.readthedocs.io/)
- [HeudiConv Tutorial](https://heudiconv.readthedocs.io/)
- [BIDS Specification](https://bids-specification.readthedocs.io/)
- [Neuroflow API Reference](./api/voxelops-api.md)

## Getting Help

If you encounter issues not covered in this guide:

1. Check [GitHub Issues](https://github.com/anthropics/neuroflow/issues)
2. Review VoxelOps logs in `/var/log/neuroflow/`
3. Enable debug logging: `logging.level: DEBUG` in config
4. Post detailed error reports with logs and configuration
