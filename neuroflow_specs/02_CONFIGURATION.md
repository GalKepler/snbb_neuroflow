# Neuroflow - Configuration Specification

## Overview

Neuroflow uses YAML configuration with Pydantic validation. Configuration can be overridden via environment variables with the `NEUROFLOW_` prefix.

---

## Configuration File Location

Default search order:
1. `--config` CLI argument
2. `NEUROFLOW_CONFIG` environment variable
3. `./neuroflow.yaml`
4. `~/.config/neuroflow/neuroflow.yaml`
5. `/etc/neuroflow/neuroflow.yaml`

---

## Complete Configuration Schema

```yaml
# neuroflow.yaml

# =============================================================================
# PATH CONFIGURATION
# =============================================================================
paths:
  # Where to look for incoming DICOM data
  dicom_incoming: /mnt/62/Raw_Data
  
  # BIDS dataset root (output of conversion)
  bids_root: /data/brainbank/bids
  
  # Derivatives directory (pipeline outputs)
  derivatives: /data/brainbank/derivatives
  
  # Neuroflow working directory (logs, temp files)
  work_dir: /data/brainbank/.neuroflow
  
  # Log directory
  log_dir: /var/log/neuroflow

# =============================================================================
# DATABASE CONFIGURATION  
# =============================================================================
database:
  # SQLite (development/small deployments)
  url: "sqlite:////data/brainbank/.neuroflow/neuroflow.db"
  
  # PostgreSQL (production)
  # url: "postgresql://user:password@localhost:5432/neuroflow"
  
  # Connection pool settings (PostgreSQL only)
  pool_size: 5
  max_overflow: 10

# =============================================================================
# REDIS CONFIGURATION (Celery backend)
# =============================================================================
redis:
  url: "redis://localhost:6379/0"
  
  # Alternative: separate broker and result backend
  # broker_url: "redis://localhost:6379/0"
  # result_backend: "redis://localhost:6379/1"

# =============================================================================
# DATASET CONFIGURATION
# =============================================================================
dataset:
  # Dataset name (used in BIDS dataset_description.json)
  name: "brainbank"
  
  # Expected session IDs (for validation)
  session_ids:
    - "baseline"
    - "followup"
  
  # DICOM directory structure
  # true: /Raw_Data/SUBJECT/SESSION/
  # false: /Raw_Data/SESSION/SUBJECT/
  dicom_participant_first: true
  
  # Pattern for extracting subject ID from path
  # Uses Python regex with named group (?P<subject>...)
  subject_pattern: "(?P<subject>sub-[A-Za-z0-9]+)"
  
  # Pattern for extracting session ID from path
  session_pattern: "(?P<session>ses-[A-Za-z0-9]+)"

# =============================================================================
# PROTOCOL CONFIGURATION (Session Validation)
# =============================================================================
protocol:
  # How long to wait (minutes) after last DICOM modification before processing
  # This ensures the scan session has fully completed
  stability_wait_minutes: 180
  
  # Minimum requirement to trigger BIDS conversion
  bids_conversion:
    min_dicom_files: 10
  
  # OPTIONAL: Pre-BIDS validation (reject sessions missing required scans)
  # If omitted, all sessions with min_dicom_files are accepted
  required_scans:
    - name: "T1w"
      series_description_pattern: ".*T1.*MPRAGE.*|.*MPRAGE.*T1.*"
      min_files: 170
      max_files: 220
    - name: "FLAIR"
      series_description_pattern: ".*FLAIR.*"
      min_files: 40
  
  optional_scans:
    - name: "T2w"
      series_description_pattern: ".*T2w.*|.*T2_.*"
      min_files: 170
    - name: "DWI"
      series_description_pattern: ".*DTI.*|.*DWI.*|.*diffusion.*"
      min_files: 60

# =============================================================================
# PIPELINE CONFIGURATION
# =============================================================================
pipelines:
  # ----- BIDS Conversion (always runs first) -----
  bids_conversion:
    enabled: true
    tool: "heudiconv"  # or "dcm2bids"
    version: "1.3.4"
    container: "nipy/heudiconv:1.3.4"
    heuristic_file: /data/brainbank/code/heuristic.py
    timeout_minutes: 60
    retries: 2
  
  # ----- Session-Level Pipelines -----
  session_level:
    - name: "mriqc"
      enabled: true
      runner: "voxelops.runners.mriqc"
      container: "nipreps/mriqc:24.0.0"
      timeout_minutes: 120
      retries: 1
      # Gate: only run if these BIDS suffixes exist
      requirements:
        bids_suffixes:
          - "T1w"
      # Resources
      resources:
        cpus: 4
        memory_gb: 16
    
    - name: "fmriprep"
      enabled: true
      runner: "voxelops.runners.fmriprep"
      container: "nipreps/fmriprep:24.0.0"
      timeout_minutes: 480
      retries: 1
      requirements:
        bids_suffixes:
          - "T1w"
          - "bold"  # Optional: only if functional data exists
      resources:
        cpus: 8
        memory_gb: 32
    
    - name: "qsiprep"
      enabled: true
      runner: "voxelops.runners.qsiprep"
      container: "pennbbl/qsiprep:1.0.0"
      timeout_minutes: 360
      retries: 1
      requirements:
        bids_suffixes:
          - "dwi"
      resources:
        cpus: 8
        memory_gb: 24
    
    - name: "freesurfer"
      enabled: true
      runner: "voxelops.runners.freesurfer"
      container: "freesurfer/freesurfer:7.4.1"
      timeout_minutes: 720  # 12 hours
      retries: 1
      requirements:
        bids_suffixes:
          - "T1w"
      resources:
        cpus: 4
        memory_gb: 8

  # ----- Subject-Level Pipelines (run across sessions) -----
  subject_level:
    - name: "longitudinal_freesurfer"
      enabled: true
      runner: "voxelops.runners.freesurfer_long"
      container: "freesurfer/freesurfer:7.4.1"
      timeout_minutes: 1440  # 24 hours
      retries: 1
      # Trigger when a new session is added for an existing subject
      trigger_on_new_session: true
      # Minimum sessions required to run
      min_sessions: 2
      requirements:
        # Requires freesurfer to have completed on all sessions
        depends_on:
          - "freesurfer"
      resources:
        cpus: 4
        memory_gb: 16

# =============================================================================
# CELERY WORKER CONFIGURATION
# =============================================================================
celery:
  # Worker concurrency
  worker_concurrency: 2
  
  # Task time limits
  task_soft_time_limit: 43200   # 12 hours soft limit
  task_time_limit: 86400        # 24 hours hard limit
  
  # Retry settings
  default_retry_delay: 300      # 5 minutes
  max_retries: 3
  
  # Task routing (optional, for multi-queue setups)
  task_routes:
    "neuroflow.workers.tasks.run_bids_conversion": "bids"
    "neuroflow.workers.tasks.run_pipeline": "processing"

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================
logging:
  level: INFO  # DEBUG, INFO, WARNING, ERROR
  format: json  # json or console
  
  # File logging
  file:
    enabled: true
    path: /var/log/neuroflow/neuroflow.log
    rotation: "daily"
    retention_days: 30
  
  # Per-task logs (stored with output)
  task_logs:
    enabled: true
    # Logs stored at: {work_dir}/logs/{subject}/{session}/{pipeline}.log

# =============================================================================
# NOTIFICATION CONFIGURATION (Optional)
# =============================================================================
notifications:
  # Slack webhook for alerts
  slack:
    enabled: false
    webhook_url: "https://hooks.slack.com/services/..."
    on_failure: true
    on_completion: false  # Too noisy for large datasets
  
  # Email notifications
  email:
    enabled: false
    smtp_server: "smtp.example.com"
    smtp_port: 587
    from_address: "neuroflow@example.com"
    to_addresses:
      - "admin@example.com"
    on_failure: true

# =============================================================================
# CONTAINER RUNTIME
# =============================================================================
container:
  # Runtime: apptainer, docker, or singularity
  runtime: apptainer
  
  # Image cache directory
  cache_dir: /data/containers
  
  # Bind mounts (added to all containers)
  bind_mounts:
    - "/data/brainbank:/data/brainbank"
    - "/mnt/62:/mnt/62:ro"
    - "/data/freesurfer_license:/opt/freesurfer/license.txt:ro"

# =============================================================================
# COMPUTE ENVIRONMENT
# =============================================================================
compute:
  # Environment: local, slurm, sge
  environment: local
  
  # SLURM settings (if environment: slurm)
  slurm:
    partition: "normal"
    account: "brainbank"
    time_limit: "24:00:00"
    mem_per_cpu: "4G"
```

---

## Environment Variable Overrides

Any configuration value can be overridden via environment variables using the `NEUROFLOW_` prefix and double underscores for nesting:

```bash
# Override database URL
export NEUROFLOW_DATABASE__URL="postgresql://user:pass@host:5432/neuroflow"

# Override Redis URL
export NEUROFLOW_REDIS__URL="redis://redis-server:6379/0"

# Override log level
export NEUROFLOW_LOGGING__LEVEL="DEBUG"

# Override paths
export NEUROFLOW_PATHS__DICOM_INCOMING="/mnt/scanner/incoming"
```

---

## Pydantic Configuration Classes

```python
# neuroflow/config.py

from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScanRequirement(BaseModel):
    """Defines a required or optional scan type."""
    name: str
    series_description_pattern: str
    min_files: int = 1
    max_files: int | None = None


class PathConfig(BaseModel):
    """Path configuration."""
    dicom_incoming: Path
    bids_root: Path
    derivatives: Path
    work_dir: Path = Path("/tmp/neuroflow")
    log_dir: Path = Path("/var/log/neuroflow")


class DatabaseConfig(BaseModel):
    """Database configuration."""
    url: str = "sqlite:///neuroflow.db"
    pool_size: int = 5
    max_overflow: int = 10


class RedisConfig(BaseModel):
    """Redis configuration."""
    url: str = "redis://localhost:6379/0"


class DatasetConfig(BaseModel):
    """Dataset metadata configuration."""
    name: str = "brainbank"
    session_ids: list[str] = Field(default_factory=lambda: ["baseline"])
    dicom_participant_first: bool = True
    subject_pattern: str = r"(?P<subject>sub-[A-Za-z0-9]+)"
    session_pattern: str = r"(?P<session>ses-[A-Za-z0-9]+)"


class ProtocolConfig(BaseModel):
    """Protocol validation configuration."""
    stability_wait_minutes: int = 180
    bids_conversion_min_files: int = 10
    required_scans: list[ScanRequirement] = Field(default_factory=list)
    optional_scans: list[ScanRequirement] = Field(default_factory=list)


class PipelineConfig(BaseModel):
    """Single pipeline configuration."""
    name: str
    enabled: bool = True
    runner: str
    container: str | None = None
    timeout_minutes: int = 60
    retries: int = 2
    requirements: dict = Field(default_factory=dict)
    resources: dict = Field(default_factory=dict)


class PipelinesConfig(BaseModel):
    """All pipelines configuration."""
    bids_conversion: dict = Field(default_factory=dict)
    session_level: list[PipelineConfig] = Field(default_factory=list)
    subject_level: list[PipelineConfig] = Field(default_factory=list)


class CeleryConfig(BaseModel):
    """Celery worker configuration."""
    worker_concurrency: int = 2
    task_soft_time_limit: int = 43200
    task_time_limit: int = 86400
    default_retry_delay: int = 300
    max_retries: int = 3


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: str = "INFO"
    format: Literal["json", "console"] = "json"


class NotificationConfig(BaseModel):
    """Notification configuration."""
    slack_webhook_url: str | None = None
    email_on_failure: str | None = None


class NeuroflowConfig(BaseSettings):
    """Main configuration class."""
    
    model_config = SettingsConfigDict(
        env_prefix="NEUROFLOW_",
        env_nested_delimiter="__",
    )
    
    paths: PathConfig
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    dataset: DatasetConfig = Field(default_factory=DatasetConfig)
    protocol: ProtocolConfig = Field(default_factory=ProtocolConfig)
    pipelines: PipelinesConfig = Field(default_factory=PipelinesConfig)
    celery: CeleryConfig = Field(default_factory=CeleryConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    
    container_runtime: Literal["apptainer", "docker", "singularity"] = "apptainer"
    compute_environment: Literal["local", "slurm", "sge"] = "local"
    
    @classmethod
    def from_yaml(cls, path: Path) -> "NeuroflowConfig":
        """Load configuration from YAML file."""
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)
```

---

## Configuration Validation

On startup, neuroflow validates:

1. **Paths exist** (or creates them with appropriate permissions)
2. **Database is accessible** (creates SQLite file if needed)
3. **Redis is reachable** (with retry on startup)
4. **Required containers are available** (pulls if missing, configurable)
5. **DICOM incoming directory is readable**
6. **Output directories are writable**

Invalid configuration results in a clear error message with the specific validation failure.
