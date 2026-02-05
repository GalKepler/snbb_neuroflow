# VoxelOps Integration Plan

## Overview

Integrate VoxelOps neuroimaging pipeline framework into neuroflow's adapter to properly map neuroflow's workflow context to VoxelOps' schema-based runners (HeudiConv, QSIPrep, QSIRecon, QSIParc).

**Current Gap**: Adapter passes raw kwargs to runners, but VoxelOps expects structured Input and Defaults schemas.

**Solution**: Create a schema mapping layer that converts:
- Database models (Session/Subject) → VoxelOps Input schemas
- YAML config → VoxelOps Defaults schemas
- VoxelOps result dicts → neuroflow PipelineResult

## Key Design Decisions

1. **Use direct runners** (`run_heudiconv()`) not `run_procedure()` - neuroflow has its own validation/audit
2. **Add `voxelops_config: dict`** field to PipelineConfig - keeps VoxelOps params isolated and flexible
3. **Registry pattern** for schema builders - easy to add new runners without modifying adapter
4. **Graceful VoxelOps import check** - log warning and fall back to container mode if missing

## Implementation Steps

### Step 1: Add Configuration Fields

**File**: `neuroflow/config.py`

Add `voxelops_config` field to both PipelineConfig and BidsConversionConfig:

```python
class PipelineConfig(BaseModel):
    # ... existing fields ...
    voxelops_config: dict = Field(default_factory=dict)

class BidsConversionConfig(BaseModel):
    # ... existing fields ...
    voxelops_config: dict = Field(default_factory=dict)
```

### Step 2: Create Schema Mapping System

**New File**: `neuroflow/adapters/voxelops_schemas.py`

Core components:
1. **BuilderContext** - dataclass encapsulating config, session, subject
2. **SchemaBuilder** - abstract base with `build_inputs()` and `build_defaults()` methods
3. **Concrete builders** - HeudiconvSchemaBuilder, QSIPrepSchemaBuilder, QSIReconSchemaBuilder, QSIParcSchemaBuilder
4. **Registry** - `SCHEMA_BUILDERS` dict mapping runner name → builder class
5. **Factory** - `get_schema_builder(runner_name)` returns appropriate builder
6. **Result parser** - `parse_voxelops_result(result_dict)` converts to PipelineResult

**Key implementation details**:

```python
@dataclass
class BuilderContext:
    config: NeuroflowConfig
    pipeline_config: PipelineConfig
    session: Session | None = None
    subject: Subject | None = None

    @property
    def participant_id(self) -> str:
        """Extract participant ID without 'sub-' prefix."""
        return self.subject.participant_id.replace("sub-", "")

    @property
    def session_id(self) -> str | None:
        """Extract session ID without 'ses-' prefix."""
        if self.session:
            return self.session.session_id.replace("ses-", "")
        return None
```

Each builder follows this pattern:

```python
class HeudiconvSchemaBuilder(SchemaBuilder):
    def build_inputs(self, ctx: BuilderContext):
        from voxelops.schemas.heudiconv import HeudiconvInputs

        return HeudiconvInputs(
            dicom_dir=Path(ctx.session.dicom_path),
            participant=ctx.participant_id,
            session=ctx.session_id,
            output_dir=ctx.config.paths.bids_root,
            heuristic=self._get_heuristic(ctx),
        )

    def build_defaults(self, ctx: BuilderContext):
        from voxelops.schemas.heudiconv import HeudiconvDefaults

        vox_cfg = ctx.pipeline_config.voxelops_config
        return HeudiconvDefaults(
            heuristic=Path(vox_cfg["heuristic"]) if vox_cfg.get("heuristic") else None,
            bids_validator=vox_cfg.get("bids_validator", True),
            docker_image=vox_cfg.get("docker_image", "nipy/heudiconv:1.3.4"),
            # ... other defaults from vox_cfg
        )
```

**Validation functions** for required config:
- `validate_heudiconv_config()` - check heuristic file exists
- `validate_qsirecon_config()` - check recon_spec exists if provided

**Result parser**:

```python
def parse_voxelops_result(result: dict[str, Any]) -> PipelineResult:
    """Convert VoxelOps result dict to neuroflow PipelineResult."""

    # Handle skipped runs (outputs exist, force=False)
    if result.get("skipped"):
        return PipelineResult(
            success=True,
            exit_code=0,
            output_path=_extract_output_path(result),
            metrics={"skipped": True, "reason": result.get("reason")},
        )

    # Parse execution result
    return PipelineResult(
        success=result.get("success", False),
        exit_code=result.get("exit_code", -1),
        output_path=_extract_output_path(result),
        error_message=_build_error_message(result),
        duration_seconds=result.get("duration_seconds"),
        metrics={
            "tool": result.get("tool"),
            "participant": result.get("participant"),
            "start_time": result.get("start_time"),
            "end_time": result.get("end_time"),
        },
        logs=result.get("stdout"),
    )
```

### Step 3: Refactor Adapter

**File**: `neuroflow/adapters/voxelops.py`

Changes:

1. **Add import check** at init:
```python
def __init__(self, config: NeuroflowConfig):
    self.config = config
    self._voxelops_available = self._check_voxelops_available()

def _check_voxelops_available(self) -> bool:
    try:
        importlib.import_module("voxelops")
        return True
    except (ImportError, ModuleNotFoundError):
        log.warning("voxelops.not_available")
        return False
```

2. **Replace `_run_via_import()` with `_run_via_voxelops()`**:
```python
def _run_via_voxelops(
    self,
    pipeline_config: PipelineConfig,
    session_id: int | None,
    subject_id: int | None,
    **kwargs: Any,
) -> PipelineResult:
    """Run pipeline via VoxelOps with schema mapping."""
    from neuroflow.adapters.voxelops_schemas import (
        BuilderContext,
        get_schema_builder,
        parse_voxelops_result,
    )
    from neuroflow.core.state import StateManager

    # Fetch session/subject from database
    state = StateManager(self.config)
    with state.get_session() as db:
        session = db.get(Session, session_id) if session_id else None
        subject = db.get(Subject, subject_id) if subject_id else None
        if session:
            subject = session.subject

    # Build context
    ctx = BuilderContext(
        config=self.config,
        pipeline_config=pipeline_config,
        session=session,
        subject=subject,
    )

    # Get builder and build schemas
    builder = get_schema_builder(pipeline_config.runner)
    inputs = builder.build_inputs(ctx)
    defaults = builder.build_defaults(ctx)

    # Apply kwargs overrides
    for key, value in kwargs.items():
        if hasattr(defaults, key):
            setattr(defaults, key, value)

    # Import and call runner
    module_path, _, func_name = pipeline_config.runner.rpartition(".")
    module = importlib.import_module(module_path)
    runner_func = getattr(module, func_name)

    # Call VoxelOps
    result = runner_func(inputs=inputs, config=defaults)

    # Parse and return
    return parse_voxelops_result(result)
```

3. **Update `_get_pipeline_config()`** to handle bids_conversion:
```python
def _get_pipeline_config(self, pipeline_name: str) -> PipelineConfig | None:
    # Check bids_conversion
    if pipeline_name == "bids_conversion":
        bids_cfg = self.config.pipelines.bids_conversion
        return PipelineConfig(
            name="bids_conversion",
            enabled=bids_cfg.enabled,
            runner="voxelops.runners.heudiconv.run_heudiconv",
            timeout_minutes=bids_cfg.timeout_minutes,
            voxelops_config=getattr(bids_cfg, "voxelops_config", {}),
        )

    # Check session_level and subject_level
    for p in self.config.pipelines.session_level:
        if p.name == pipeline_name:
            return p
    for p in self.config.pipelines.subject_level:
        if p.name == pipeline_name:
            return p
    return None
```

4. **Remove `_build_container_command()`** - VoxelOps handles Docker internally

### Step 4: Update Configuration Files

**Files**: `neuroflow.yaml` and `configs/neuroflow.example.yaml`

Add `voxelops_config` sections:

```yaml
pipelines:
  bids_conversion:
    enabled: true
    tool: "heudiconv"
    timeout_minutes: 60
    voxelops_config:
      heuristic: "/etc/neuroflow/heuristics/brainbank.py"
      bids_validator: true
      overwrite: false
      docker_image: "nipy/heudiconv:1.3.4"
      post_process: true

  session_level:
    - name: "qsiprep"
      enabled: true
      runner: "voxelops.runners.qsiprep.run_qsiprep"
      timeout_minutes: 720
      voxelops_config:
        nprocs: 8
        mem_mb: 16000
        output_resolution: 1.6
        anatomical_template: ["MNI152NLin2009cAsym"]
        fs_license: "/opt/freesurfer/license.txt"
        docker_image: "pennlinc/qsiprep:latest"
      requirements:
        bids_suffixes: ["dwi"]

    - name: "qsirecon"
      enabled: true
      runner: "voxelops.runners.qsirecon.run_qsirecon"
      timeout_minutes: 480
      voxelops_config:
        nprocs: 8
        mem_mb: 16000
        recon_spec: "/etc/neuroflow/specs/dsi_studio.yaml"
        atlases: ["Brainnetome246Ext", "AAL116"]
        fs_license: "/opt/freesurfer/license.txt"
        docker_image: "pennlinc/qsirecon:latest"
```

### Step 5: Create Tests

**New Files**:
- `tests/adapters/test_voxelops_schemas.py` - Unit tests for each builder
- `tests/adapters/test_voxelops_adapter.py` - Integration tests

**Test approach**:
- Mock BuilderContext with test data
- Verify correct VoxelOps schemas are produced
- Test result parsing with various result dicts
- Test error handling and validation

Example test:

```python
def test_heudiconv_builder_creates_valid_inputs(mock_config, mock_session):
    pipeline_config = PipelineConfig(
        name="bids_conversion",
        runner="voxelops.runners.heudiconv.run_heudiconv",
        voxelops_config={"heuristic": "/etc/test.py"},
    )

    ctx = BuilderContext(
        config=mock_config,
        pipeline_config=pipeline_config,
        session=mock_session,
        subject=mock_session.subject,
    )

    builder = HeudiconvSchemaBuilder()
    inputs = builder.build_inputs(ctx)

    assert inputs.participant == "001"  # without 'sub-' prefix
    assert inputs.session == "baseline"  # without 'ses-' prefix
    assert inputs.dicom_dir == Path(mock_session.dicom_path)
```

## VoxelOps Configuration Reference

### HeudiConv (BIDS Conversion)
```yaml
voxelops_config:
  heuristic: "/path/to/heuristic.py"  # REQUIRED
  bids_validator: true
  overwrite: false
  converter: "dcm2niix"
  docker_image: "nipy/heudiconv:1.3.4"
  post_process: true
```

### QSIPrep (Diffusion Preprocessing)
```yaml
voxelops_config:
  nprocs: 8
  mem_mb: 16000
  output_resolution: 1.6
  anatomical_template: ["MNI152NLin2009cAsym"]
  fs_license: "/opt/freesurfer/license.txt"
  docker_image: "pennlinc/qsiprep:latest"
  force: false
```

### QSIRecon (Diffusion Reconstruction)
```yaml
voxelops_config:
  nprocs: 8
  mem_mb: 16000
  recon_spec: "/path/to/spec.yaml"  # Required for reconstruction
  atlases: ["Brainnetome246Ext", "AAL116"]
  fs_license: "/opt/freesurfer/license.txt"
  docker_image: "pennlinc/qsirecon:latest"
```

### QSIParc (Parcellation)
```yaml
voxelops_config:
  mask: "gm"
  force: false
  n_jobs: 1
  n_procs: 1
```

## Critical Files

1. **NEW**: `neuroflow/adapters/voxelops_schemas.py` - Schema mapping layer (core of integration)
2. **MODIFY**: `neuroflow/adapters/voxelops.py` - Refactor to use schema mapping
3. **MODIFY**: `neuroflow/config.py` - Add voxelops_config fields
4. **MODIFY**: `neuroflow.yaml` - Add VoxelOps configuration
5. **NEW**: `tests/adapters/test_voxelops_schemas.py` - Unit tests

## Verification Steps

After implementation:

1. **Check VoxelOps import**:
   ```bash
   python -c "import voxelops; print('VoxelOps available')"
   ```

2. **Validate config**:
   ```bash
   neuroflow config validate
   ```

3. **Test BIDS conversion** (with a test session):
   ```bash
   neuroflow process session SUB001 baseline --pipeline bids_conversion
   ```

4. **Check logs** for "adapter.voxelops_complete":
   ```bash
   tail -f /var/log/neuroflow/neuroflow.log
   ```

5. **Verify database records**:
   ```bash
   neuroflow status --sessions
   ```

6. **Test QSIPrep** (requires BIDS data with dwi):
   ```bash
   neuroflow process session SUB001 baseline --pipeline qsiprep
   ```

## Error Handling

- **VoxelOps not installed**: Adapter logs warning, falls back to container mode if configured
- **Missing heuristic**: SchemaValidationError raised early with clear message
- **Missing session/subject**: ValueError raised with entity ID
- **VoxelOps runner fails**: Captures exit_code, stderr, returns failed PipelineResult
- **Schema build fails**: Returns PipelineResult with error_message

## Migration for Existing Deployments

1. Install VoxelOps:
   ```bash
   pip install git+https://github.com/yalab-dev/VoxelOps.git
   ```

2. Update config with voxelops_config sections

3. Test with single session before full deployment

4. Monitor logs for successful integration vs container fallback

## Notes

- VoxelOps handles all Docker command building internally - neuroflow just provides schemas
- Direct runners are used (not run_procedure) to avoid redundant validation
- Registry pattern makes it easy to add new VoxelOps runners in the future
- All VoxelOps configuration is isolated in voxelops_config dict for flexibility
