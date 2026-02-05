# VoxelOps API Reference

Complete API reference for neuroflow's VoxelOps integration.

## Table of Contents

- [VoxelopsAdapter](#voxelopsadapter)
- [Schema Builders](#schema-builders)
- [Configuration](#configuration)
- [Models](#models)
- [Utilities](#utilities)

---

## VoxelopsAdapter

The main adapter class for running VoxelOps pipelines.

### Class: `VoxelopsAdapter`

**Module**: `neuroflow.adapters.voxelops`

Main adapter for executing VoxelOps neuroimaging pipelines.

#### Constructor

```python
VoxelopsAdapter(config: NeuroflowConfig)
```

**Parameters**:
- `config` (NeuroflowConfig): Neuroflow configuration object

**Example**:
```python
from neuroflow.config import NeuroflowConfig
from neuroflow.adapters.voxelops import VoxelopsAdapter

config = NeuroflowConfig.from_yaml("neuroflow.yaml")
adapter = VoxelopsAdapter(config)
```

#### Methods

##### `run()`

Execute a pipeline via VoxelOps.

```python
def run(
    pipeline_name: str,
    session_id: int | None = None,
    subject_id: int | None = None,
    **kwargs: Any,
) -> PipelineResult
```

**Parameters**:
- `pipeline_name` (str): Name of pipeline to run (e.g., "bids_conversion", "qsiprep")
- `session_id` (int | None): Database ID of session (for session-level pipelines)
- `subject_id` (int | None): Database ID of subject (for subject-level pipelines)
- `**kwargs`: Additional parameters to override configuration defaults

**Returns**:
- `PipelineResult`: Result object containing execution status and outputs

**Raises**:
- `ValueError`: If pipeline not found or invalid parameters
- `SchemaValidationError`: If required configuration missing

**Example**:
```python
# Run BIDS conversion for a session
result = adapter.run("bids_conversion", session_id=1)

# Run QSIPrep with custom resources
result = adapter.run(
    "qsiprep",
    session_id=1,
    nprocs=16,
    mem_mb=32000,
)

# Check result
if result.success:
    print(f"Success! Output: {result.output_path}")
else:
    print(f"Failed: {result.error_message}")
```

##### `_check_voxelops_available()`

Check if VoxelOps is installed and importable.

```python
def _check_voxelops_available() -> bool
```

**Returns**:
- `bool`: True if VoxelOps is available

**Internal**: This method is called automatically during initialization.

##### `_get_pipeline_config()`

Get configuration for a specific pipeline.

```python
def _get_pipeline_config(pipeline_name: str) -> PipelineConfig | None
```

**Parameters**:
- `pipeline_name` (str): Name of pipeline

**Returns**:
- `PipelineConfig | None`: Pipeline configuration or None if not found

**Example**:
```python
config = adapter._get_pipeline_config("qsiprep")
if config:
    print(f"Runner: {config.runner}")
    print(f"Timeout: {config.timeout_minutes} minutes")
```

#### Attributes

- `config` (NeuroflowConfig): Neuroflow configuration
- `_voxelops_available` (bool): Whether VoxelOps is installed

---

## PipelineResult

Result object returned by pipeline execution.

### Class: `PipelineResult`

**Module**: `neuroflow.adapters.voxelops`

Dataclass containing pipeline execution results.

#### Attributes

- `success` (bool): Whether pipeline executed successfully
- `exit_code` (int): Exit code from pipeline (0 = success)
- `output_path` (Path | None): Path to pipeline outputs
- `error_message` (str | None): Error message if failed
- `duration_seconds` (float | None): Execution duration in seconds
- `metrics` (dict | None): Additional metrics from pipeline
- `logs` (str | None): stdout/stderr logs

#### Example

```python
result = adapter.run("qsiprep", session_id=1)

# Check success
if result.success:
    print("Pipeline succeeded!")

    # Access outputs
    print(f"Output directory: {result.output_path}")
    print(f"Execution time: {result.duration_seconds / 60:.1f} minutes")

    # Check if skipped
    if result.metrics and result.metrics.get("skipped"):
        print(f"Skipped: {result.metrics['reason']}")

else:
    print(f"Pipeline failed with exit code {result.exit_code}")
    print(f"Error: {result.error_message}")

    # Inspect logs
    if result.logs:
        print("Last 20 lines of logs:")
        for line in result.logs.split('\n')[-20:]:
            print(f"  {line}")
```

---

## Schema Builders

Schema builders convert neuroflow configuration and database models to VoxelOps schemas.

### BuilderContext

Context object passed to schema builders.

**Module**: `neuroflow.adapters.voxelops_schemas`

```python
@dataclass
class BuilderContext:
    config: NeuroflowConfig
    pipeline_config: PipelineConfig
    session: Session | None = None
    subject: Subject | None = None
```

#### Properties

##### `participant_id`

Extract participant ID without 'sub-' prefix.

```python
@property
def participant_id(self) -> str
```

**Returns**: Participant ID (e.g., "001" from "sub-001")

**Raises**: `ValueError` if subject not provided

##### `session_id`

Extract session ID without 'ses-' prefix.

```python
@property
def session_id(self) -> str | None
```

**Returns**: Session ID (e.g., "baseline" from "ses-baseline") or None

##### `voxelops_config`

Shortcut to pipeline's voxelops_config dictionary.

```python
@property
def voxelops_config(self) -> dict
```

**Returns**: Dictionary of VoxelOps configuration parameters

### SchemaBuilder

Abstract base class for schema builders.

**Module**: `neuroflow.adapters.voxelops_schemas`

```python
class SchemaBuilder(ABC):
    @abstractmethod
    def build_inputs(self, ctx: BuilderContext) -> Any:
        pass

    @abstractmethod
    def build_defaults(self, ctx: BuilderContext) -> Any:
        pass

    def validate_config(self, ctx: BuilderContext) -> None:
        pass
```

### HeudiconvSchemaBuilder

Schema builder for HeudiConv BIDS conversion.

**Module**: `neuroflow.adapters.voxelops_schemas`

```python
class HeudiconvSchemaBuilder(SchemaBuilder):
    def validate_config(self, ctx: BuilderContext) -> None:
        """Validates that heuristic file exists."""

    def build_inputs(self, ctx: BuilderContext) -> HeudiconvInputs:
        """Build HeudiconvInputs schema."""

    def build_defaults(self, ctx: BuilderContext) -> HeudiconvDefaults:
        """Build HeudiconvDefaults schema."""
```

#### Configuration

Required in `voxelops_config`:
- `heuristic` (str): Path to heuristic file

Optional in `voxelops_config`:
- `bids_validator` (bool): Run BIDS validator (default: True)
- `overwrite` (bool): Overwrite existing outputs (default: False)
- `converter` (str): DICOM converter (default: "dcm2niix")
- `docker_image` (str): Docker image (default: "nipy/heudiconv:1.3.4")
- `post_process` (bool): Run post-processing (default: True)

### QSIPrepSchemaBuilder

Schema builder for QSIPrep diffusion preprocessing.

**Module**: `neuroflow.adapters.voxelops_schemas`

```python
class QSIPrepSchemaBuilder(SchemaBuilder):
    def build_inputs(self, ctx: BuilderContext) -> QSIPrepInputs:
        """Build QSIPrepInputs schema."""

    def build_defaults(self, ctx: BuilderContext) -> QSIPrepDefaults:
        """Build QSIPrepDefaults schema."""
```

#### Configuration

Required in `voxelops_config`:
- `fs_license` (str): Path to FreeSurfer license

Optional in `voxelops_config`:
- `nprocs` (int): Number of CPUs (default: 8)
- `mem_mb` (int): Memory limit in MB (default: 16000)
- `output_resolution` (float): Output resolution in mm (default: 1.6)
- `anatomical_template` (list[str]): Templates (default: ["MNI152NLin2009cAsym"])
- `docker_image` (str): Docker image (default: "pennlinc/qsiprep:latest")
- `force` (bool): Force reprocessing (default: False)

### QSIReconSchemaBuilder

Schema builder for QSIRecon reconstruction.

**Module**: `neuroflow.adapters.voxelops_schemas`

```python
class QSIReconSchemaBuilder(SchemaBuilder):
    def validate_config(self, ctx: BuilderContext) -> None:
        """Validates recon_spec if provided."""

    def build_inputs(self, ctx: BuilderContext) -> QSIReconInputs:
        """Build QSIReconInputs schema."""

    def build_defaults(self, ctx: BuilderContext) -> QSIReconDefaults:
        """Build QSIReconDefaults schema."""
```

#### Configuration

Required in `voxelops_config`:
- `fs_license` (str): Path to FreeSurfer license

Optional in `voxelops_config`:
- `recon_spec` (str): Path to reconstruction specification YAML
- `nprocs` (int): Number of CPUs (default: 8)
- `mem_mb` (int): Memory limit in MB (default: 16000)
- `atlases` (list[str]): Atlases for connectivity (default: ["Brainnetome246Ext", "AAL116"])
- `docker_image` (str): Docker image (default: "pennlinc/qsirecon:latest")
- `force` (bool): Force reprocessing (default: False)

### QSIParcSchemaBuilder

Schema builder for QSIParc parcellation.

**Module**: `neuroflow.adapters.voxelops_schemas`

```python
class QSIParcSchemaBuilder(SchemaBuilder):
    def build_inputs(self, ctx: BuilderContext) -> QSIParcInputs:
        """Build QSIParcInputs schema."""

    def build_defaults(self, ctx: BuilderContext) -> QSIParcDefaults:
        """Build QSIParcDefaults schema."""
```

#### Configuration

Optional in `voxelops_config`:
- `mask` (str): Tissue mask to use (default: "gm")
- `force` (bool): Force reprocessing (default: False)
- `n_jobs` (int): Number of parallel jobs (default: 1)
- `n_procs` (int): Processors per job (default: 1)

### Factory Functions

#### `get_schema_builder()`

Get appropriate schema builder for a runner.

```python
def get_schema_builder(runner_name: str) -> SchemaBuilder
```

**Parameters**:
- `runner_name` (str): Full module path to runner (e.g., "voxelops.runners.heudiconv.run_heudiconv")

**Returns**:
- `SchemaBuilder`: Instance of appropriate builder class

**Raises**:
- `ValueError`: If runner not supported

**Example**:
```python
from neuroflow.adapters.voxelops_schemas import get_schema_builder

builder = get_schema_builder("voxelops.runners.qsiprep.run_qsiprep")
# Returns QSIPrepSchemaBuilder instance
```

#### `parse_voxelops_result()`

Convert VoxelOps result dict to PipelineResult.

```python
def parse_voxelops_result(result: dict[str, Any]) -> PipelineResult
```

**Parameters**:
- `result` (dict): Result dictionary returned by VoxelOps runner

**Returns**:
- `PipelineResult`: Normalized result object

**Example**:
```python
from neuroflow.adapters.voxelops_schemas import parse_voxelops_result

voxelops_result = {
    "success": True,
    "exit_code": 0,
    "output_dir": "/data/output",
    "duration_seconds": 120.5,
    "tool": "heudiconv",
}

pipeline_result = parse_voxelops_result(voxelops_result)
print(f"Success: {pipeline_result.success}")
print(f"Output: {pipeline_result.output_path}")
```

---

## Configuration

Configuration classes for VoxelOps pipelines.

### PipelineConfig

**Module**: `neuroflow.config`

Configuration for a single pipeline.

```python
class PipelineConfig(BaseModel):
    name: str
    enabled: bool = True
    runner: str = ""
    container: str | None = None
    timeout_minutes: int = 60
    retries: int = 2
    requirements: dict = Field(default_factory=dict)
    resources: dict = Field(default_factory=dict)
    trigger_on_new_session: bool = False
    min_sessions: int = 2
    voxelops_config: dict = Field(default_factory=dict)
```

#### Fields

- `name`: Pipeline identifier
- `enabled`: Whether pipeline is enabled
- `runner`: Python module path to runner function
- `container`: Container image (fallback if VoxelOps unavailable)
- `timeout_minutes`: Maximum execution time
- `retries`: Number of retries on failure
- `requirements`: Pipeline requirements (e.g., `{"bids_suffixes": ["dwi"]}`)
- `resources`: Resource requirements
- `trigger_on_new_session`: Auto-trigger on new sessions
- `min_sessions`: Minimum sessions required for subject-level pipelines
- **`voxelops_config`**: VoxelOps-specific configuration parameters

#### Example

```yaml
session_level:
  - name: "qsiprep"
    enabled: true
    runner: "voxelops.runners.qsiprep.run_qsiprep"
    timeout_minutes: 720
    requirements:
      bids_suffixes: ["dwi"]
    voxelops_config:
      nprocs: 8
      mem_mb: 16000
      fs_license: "/opt/freesurfer/license.txt"
```

### BidsConversionConfig

**Module**: `neuroflow.config`

Configuration for BIDS conversion pipeline.

```python
class BidsConversionConfig(BaseModel):
    enabled: bool = True
    tool: str = "heudiconv"
    version: str = "1.3.4"
    container: str | None = None
    heuristic_file: str | None = None
    timeout_minutes: int = 60
    retries: int = 2
    voxelops_config: dict = Field(default_factory=dict)
```

#### Fields

- `enabled`: Whether BIDS conversion is enabled
- `tool`: Conversion tool name
- `version`: Tool version
- `container`: Container image (fallback)
- `heuristic_file`: Path to heuristic file (legacy)
- `timeout_minutes`: Maximum execution time
- `retries`: Number of retries on failure
- **`voxelops_config`**: VoxelOps-specific configuration

#### Example

```yaml
bids_conversion:
  enabled: true
  tool: "heudiconv"
  timeout_minutes: 60
  voxelops_config:
    heuristic: "/etc/neuroflow/heuristics/my_heuristic.py"
    bids_validator: true
    overwrite: false
```

---

## Models

Database models used by VoxelOps adapter.

### Session

**Module**: `neuroflow.models.session`

Represents a scanning session.

#### Attributes

- `id` (int): Primary key
- `subject_id` (int): Foreign key to Subject
- `session_id` (str): Session identifier (e.g., "ses-baseline")
- `dicom_path` (str): Path to DICOM files
- `bids_path` (str | None): Path to BIDS outputs
- `status` (SessionStatus): Processing status
- `is_valid` (bool | None): Whether session passed validation
- `subject` (Subject): Related subject object

### Subject

**Module**: `neuroflow.models.subject`

Represents a study participant.

#### Attributes

- `id` (int): Primary key
- `participant_id` (str): Participant identifier (e.g., "sub-001")
- `recruitment_id` (str | None): External recruitment ID
- `status` (SubjectStatus): Processing status
- `sessions` (list[Session]): Related session objects

---

## Utilities

### SchemaValidationError

**Module**: `neuroflow.adapters.voxelops_schemas`

Exception raised when VoxelOps configuration is invalid.

```python
class SchemaValidationError(Exception):
    pass
```

**Example**:
```python
from neuroflow.adapters.voxelops_schemas import SchemaValidationError

try:
    result = adapter.run("bids_conversion", session_id=1)
except SchemaValidationError as e:
    print(f"Configuration error: {e}")
```

### Supported Runners

Registry of supported VoxelOps runners:

```python
SCHEMA_BUILDERS = {
    "voxelops.runners.heudiconv.run_heudiconv": HeudiconvSchemaBuilder,
    "voxelops.runners.qsiprep.run_qsiprep": QSIPrepSchemaBuilder,
    "voxelops.runners.qsirecon.run_qsirecon": QSIReconSchemaBuilder,
    "voxelops.runners.qsiparc.run_qsiparc": QSIParcSchemaBuilder,
}
```

---

## Complete Example

Here's a complete example using the API:

```python
from pathlib import Path
from neuroflow.adapters.voxelops import VoxelopsAdapter
from neuroflow.config import NeuroflowConfig
from neuroflow.core.state import StateManager
from neuroflow.models.session import Session

# Load configuration
config = NeuroflowConfig.from_yaml("neuroflow.yaml")

# Initialize adapter
adapter = VoxelopsAdapter(config)

# Check VoxelOps availability
if not adapter._voxelops_available:
    print("WARNING: VoxelOps not installed, will use container mode")

# Get session from database
state = StateManager(config)
with state.get_session() as db:
    session = db.query(Session).filter(Session.id == 1).first()
    print(f"Processing: {session.subject.participant_id}/{session.session_id}")

# Run BIDS conversion
print("Running BIDS conversion...")
result = adapter.run("bids_conversion", session_id=session.id)

if result.success:
    print(f"✓ BIDS conversion successful!")
    print(f"  Output: {result.output_path}")
    print(f"  Duration: {result.duration_seconds:.1f}s")

    # Run QSIPrep
    print("Running QSIPrep...")
    result = adapter.run(
        "qsiprep",
        session_id=session.id,
        nprocs=16,  # Override default
        force=False,  # Skip if outputs exist
    )

    if result.success:
        print(f"✓ QSIPrep successful!")
        print(f"  Output: {result.output_path}")
        print(f"  Duration: {result.duration_seconds / 60:.1f} minutes")

        # Run QSIRecon
        print("Running QSIRecon...")
        result = adapter.run("qsirecon", subject_id=session.subject_id)

        if result.success:
            print(f"✓ Complete workflow successful!")

            # Find connectivity matrices
            conn_files = list(result.output_path.rglob("*_conndata-*.csv"))
            print(f"  Generated {len(conn_files)} connectivity matrices")
        else:
            print(f"✗ QSIRecon failed: {result.error_message}")
    else:
        print(f"✗ QSIPrep failed: {result.error_message}")
else:
    print(f"✗ BIDS conversion failed: {result.error_message}")
```

---

## Additional Resources

- [VoxelOps Usage Guide](../voxelops-usage.md)
- [VoxelOps Documentation](https://github.com/yalab-dev/VoxelOps)
- [Example Scripts](../../examples/voxelops/)
- [Tutorial Notebook](../../examples/voxelops/voxelops_tutorial.ipynb)
