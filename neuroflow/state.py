"""CSV-based session and pipeline state tracking."""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import structlog

log = structlog.get_logger("state")

SESSIONS_COLUMNS = [
    "participant_id",
    "session_id",
    "dicom_path",
    "recruitment_id",
    "status",
    "validation_message",
    "scans_found",
    "last_updated",
]

PIPELINE_RUNS_COLUMNS = [
    "participant_id",
    "session_id",
    "pipeline_name",
    "status",
    "start_time",
    "end_time",
    "duration_seconds",
    "exit_code",
    "error_message",
    "output_path",
    "log_path",
]


class SessionState:
    """CSV-based session and pipeline state tracking.

    Manages two CSV files:
    - sessions.csv: discovered sessions and their validation status
    - pipeline_runs.csv: pipeline execution records
    """

    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_path = self.state_dir / "sessions.csv"
        self.pipeline_runs_path = self.state_dir / "pipeline_runs.csv"
        self._lock = threading.Lock()

    def load_sessions(self) -> pd.DataFrame:
        """Load sessions from CSV, returning empty DataFrame if file doesn't exist."""
        if self.sessions_path.exists():
            df = pd.read_csv(self.sessions_path, dtype=str)
            # Ensure all expected columns exist
            for col in SESSIONS_COLUMNS:
                if col not in df.columns:
                    df[col] = ""
            return df
        return pd.DataFrame(columns=SESSIONS_COLUMNS)

    def save_sessions(self, df: pd.DataFrame) -> None:
        """Atomically write sessions DataFrame to CSV."""
        tmp_path = self.sessions_path.with_suffix(".tmp")
        df.to_csv(tmp_path, index=False)
        os.rename(tmp_path, self.sessions_path)

    def load_pipeline_runs(self) -> pd.DataFrame:
        """Load pipeline runs from CSV."""
        if self.pipeline_runs_path.exists():
            df = pd.read_csv(self.pipeline_runs_path, dtype=str)
            for col in PIPELINE_RUNS_COLUMNS:
                if col not in df.columns:
                    df[col] = ""
            return df
        return pd.DataFrame(columns=PIPELINE_RUNS_COLUMNS)

    def save_pipeline_runs(self, df: pd.DataFrame) -> None:
        """Atomically write pipeline runs DataFrame to CSV."""
        tmp_path = self.pipeline_runs_path.with_suffix(".tmp")
        df.to_csv(tmp_path, index=False)
        os.rename(tmp_path, self.pipeline_runs_path)

    def register_sessions(self, new_df: pd.DataFrame) -> int:
        """Merge newly discovered sessions into state.

        Keyed on (participant_id, session_id). New sessions are added,
        existing ones are left unchanged.

        Returns the number of new sessions added.
        """
        with self._lock:
            existing = self.load_sessions()

            if existing.empty:
                new_df = new_df.copy()
                for col in SESSIONS_COLUMNS:
                    if col not in new_df.columns:
                        new_df[col] = ""
                new_df["status"] = new_df["status"].replace("", "discovered")
                new_df.loc[new_df["status"] == "", "status"] = "discovered"
                # Fill missing status
                mask = new_df["status"].isna() | (new_df["status"] == "")
                new_df.loc[mask, "status"] = "discovered"
                new_df["last_updated"] = _now()
                self.save_sessions(new_df[SESSIONS_COLUMNS])
                return len(new_df)

            # Find truly new sessions by merging
            merged = existing.merge(
                new_df[["participant_id", "session_id"]],
                on=["participant_id", "session_id"],
                how="right",
                indicator=True,
            )
            new_only = merged[merged["_merge"] == "right_only"].drop(columns=["_merge"])

            if new_only.empty:
                return 0

            # Build rows for new sessions
            new_rows = new_df.merge(
                new_only[["participant_id", "session_id"]],
                on=["participant_id", "session_id"],
            )
            for col in SESSIONS_COLUMNS:
                if col not in new_rows.columns:
                    new_rows[col] = ""

            mask = new_rows["status"].isna() | (new_rows["status"] == "")
            new_rows.loc[mask, "status"] = "discovered"
            new_rows["last_updated"] = _now()

            combined = pd.concat(
                [existing, new_rows[SESSIONS_COLUMNS]], ignore_index=True
            )
            self.save_sessions(combined)

            added = len(new_rows)
            log.info("state.sessions_registered", new_sessions=added)
            return added

    def update_session_status(
        self,
        participant_id: str,
        session_id: str,
        status: str,
        validation_message: str = "",
        scans_found: dict | None = None,
    ) -> None:
        """Update a session's status and validation info."""
        with self._lock:
            df = self.load_sessions()
            mask = (df["participant_id"] == participant_id) & (
                df["session_id"] == session_id
            )

            if not mask.any():
                log.warning(
                    "state.session_not_found",
                    participant_id=participant_id,
                    session_id=session_id,
                )
                return

            df.loc[mask, "status"] = status
            df.loc[mask, "validation_message"] = validation_message
            if scans_found is not None:
                df.loc[mask, "scans_found"] = json.dumps(scans_found)
            df.loc[mask, "last_updated"] = _now()

            self.save_sessions(df)

    def record_pipeline_run(
        self,
        participant_id: str,
        session_id: str,
        pipeline_name: str,
        status: str,
        start_time: str = "",
        end_time: str = "",
        duration_seconds: str = "",
        exit_code: str = "",
        error_message: str = "",
        output_path: str = "",
        log_path: str = "",
    ) -> None:
        """Append a pipeline run record."""
        with self._lock:
            df = self.load_pipeline_runs()
            new_row = pd.DataFrame(
                [
                    {
                        "participant_id": participant_id,
                        "session_id": session_id,
                        "pipeline_name": pipeline_name,
                        "status": status,
                        "start_time": start_time,
                        "end_time": end_time,
                        "duration_seconds": duration_seconds,
                        "exit_code": exit_code,
                        "error_message": error_message,
                        "output_path": output_path,
                        "log_path": log_path,
                    }
                ]
            )
            df = pd.concat([df, new_row], ignore_index=True)
            self.save_pipeline_runs(df)

    def get_pending_sessions(
        self, for_pipeline: str, force: bool = False
    ) -> pd.DataFrame:
        """Get validated sessions that don't have a completed run for the given pipeline.

        If force=True, return all validated sessions regardless of prior runs.
        """
        sessions = self.load_sessions()

        # Only consider validated sessions
        validated = sessions[sessions["status"] == "validated"]

        if validated.empty or force:
            return validated

        runs = self.load_pipeline_runs()

        if runs.empty:
            return validated

        # Find sessions with completed runs for this pipeline
        completed = runs[
            (runs["pipeline_name"] == for_pipeline) & (runs["status"] == "completed")
        ][["participant_id", "session_id"]]

        if completed.empty:
            return validated

        # Return validated sessions that don't have a completed run
        merged = validated.merge(
            completed,
            on=["participant_id", "session_id"],
            how="left",
            indicator=True,
        )
        pending = merged[merged["_merge"] == "left_only"].drop(columns=["_merge"])
        return pending

    def get_session_table(self) -> pd.DataFrame:
        """Get the full sessions table for display."""
        return self.load_sessions()

    def get_pipeline_summary(self) -> pd.DataFrame:
        """Get summary of pipeline runs grouped by pipeline and status."""
        runs = self.load_pipeline_runs()
        if runs.empty:
            return pd.DataFrame(columns=["pipeline_name", "status", "count"])

        summary = (
            runs.groupby(["pipeline_name", "status"])
            .size()
            .reset_index(name="count")
        )
        return summary


def _now() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(timezone.utc).isoformat()
