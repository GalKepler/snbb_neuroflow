"""Pydantic configuration models for Neuroflow."""

from pathlib import Path
from typing import Literal

import yaml
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


class ExecutionConfig(BaseModel):
    """Execution configuration for parallel processing."""

    max_workers: int = 2
    log_per_session: bool = True
    state_dir: Path = Path(".neuroflow")


class GoogleSheetConfig(BaseModel):
    """Google Sheet mapping configuration."""

    enabled: bool = False
    spreadsheet_key: str = ""
    worksheet_name: str = "Sheet1"
    service_account_file: str = ""
    scan_id_column: str = "ScanID"
    subject_code_column: str = "SubjectCode"
    csv_file: str = ""
    unknown_subject_id: str = "unknown"


class DatasetConfig(BaseModel):
    """Dataset metadata configuration."""

    name: str = "brainbank"
    session_ids: list[str] = Field(default_factory=lambda: ["baseline"])
    dicom_participant_first: bool = True
    subject_pattern: str = r"(?P<subject>sub-[A-Za-z0-9]+)"
    session_pattern: str = r"(?P<session>ses-[A-Za-z0-9]+)"
    google_sheet: GoogleSheetConfig = Field(default_factory=GoogleSheetConfig)


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
    runner: str = ""
    timeout_minutes: int = 60
    retries: int = 2
    requirements: dict = Field(default_factory=dict)
    resources: dict = Field(default_factory=dict)
    trigger_on_new_session: bool = False
    min_sessions: int = 2
    voxelops_config: dict = Field(default_factory=dict)


class BidsConversionConfig(BaseModel):
    """BIDS conversion pipeline configuration."""

    enabled: bool = True
    tool: str = "heudiconv"
    version: str = "1.3.4"
    heuristic_file: str | None = None
    timeout_minutes: int = 60
    retries: int = 2
    voxelops_config: dict = Field(default_factory=dict)


class PipelinesConfig(BaseModel):
    """All pipelines configuration."""

    bids_conversion: BidsConversionConfig | dict = Field(default_factory=dict)
    session_level: list[PipelineConfig] = Field(default_factory=list)
    subject_level: list[PipelineConfig] = Field(default_factory=list)


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = "INFO"
    format: Literal["json", "console"] = "console"


class NeuroflowConfig(BaseSettings):
    """Main configuration class."""

    model_config = SettingsConfigDict(
        env_prefix="NEUROFLOW_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    paths: PathConfig
    dataset: DatasetConfig = Field(default_factory=DatasetConfig)
    protocol: ProtocolConfig = Field(default_factory=ProtocolConfig)
    pipelines: PipelinesConfig = Field(default_factory=PipelinesConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "NeuroflowConfig":
        """Load configuration from YAML file."""
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)

    @classmethod
    def find_and_load(cls, config_path: str | None = None) -> "NeuroflowConfig":
        """Find and load configuration from default locations."""
        import os

        search_paths = [
            config_path,
            os.environ.get("NEUROFLOW_CONFIG"),
            "./neuroflow.yaml",
            str(Path.home() / ".config" / "neuroflow" / "neuroflow.yaml"),
            "/etc/neuroflow/neuroflow.yaml",
        ]

        for p in search_paths:
            if p and Path(p).exists():
                return cls.from_yaml(p)

        raise FileNotFoundError(
            "No configuration file found. Searched:\n"
            + "\n".join(f"  - {p}" for p in search_paths if p)
        )
