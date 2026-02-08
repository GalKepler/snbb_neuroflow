"""Tests for CSV-based session state tracking."""

import json

import pandas as pd
import pytest

from neuroflow.state import SessionState


@pytest.fixture
def state(tmp_path):
    """Create a SessionState with a temp directory."""
    return SessionState(tmp_path / "state")


class TestLoadSave:
    def test_load_empty(self, state):
        """Loading when no CSV exists returns empty DataFrame."""
        df = state.load_sessions()
        assert df.empty
        assert "participant_id" in df.columns
        assert "status" in df.columns

    def test_save_and_load_roundtrip(self, state):
        """Save then load preserves data."""
        df = pd.DataFrame(
            [
                {
                    "participant_id": "sub-001",
                    "session_id": "ses-baseline",
                    "dicom_path": "/data/sub-001/ses-baseline",
                    "recruitment_id": "",
                    "status": "discovered",
                    "validation_message": "",
                    "scans_found": "",
                    "last_updated": "2024-01-01T00:00:00",
                }
            ]
        )
        state.save_sessions(df)
        loaded = state.load_sessions()
        assert len(loaded) == 1
        assert loaded.iloc[0]["participant_id"] == "sub-001"


class TestRegisterSessions:
    def test_register_new_sessions(self, state):
        """Register new sessions into empty state."""
        new_df = pd.DataFrame(
            [
                {
                    "participant_id": "sub-001",
                    "session_id": "ses-baseline",
                    "dicom_path": "/data/001/baseline",
                    "recruitment_id": "REC001",
                },
                {
                    "participant_id": "sub-002",
                    "session_id": "ses-baseline",
                    "dicom_path": "/data/002/baseline",
                    "recruitment_id": "REC002",
                },
            ]
        )
        added = state.register_sessions(new_df)
        assert added == 2

        loaded = state.load_sessions()
        assert len(loaded) == 2
        assert set(loaded["status"]) == {"discovered"}

    def test_register_duplicate_sessions_ignored(self, state):
        """Duplicate sessions are not re-added."""
        new_df = pd.DataFrame(
            [
                {
                    "participant_id": "sub-001",
                    "session_id": "ses-baseline",
                    "dicom_path": "/data/001/baseline",
                    "recruitment_id": "",
                },
            ]
        )
        state.register_sessions(new_df)
        added = state.register_sessions(new_df)
        assert added == 0

        loaded = state.load_sessions()
        assert len(loaded) == 1

    def test_register_mix_new_and_existing(self, state):
        """Only new sessions are added when some already exist."""
        first = pd.DataFrame(
            [
                {
                    "participant_id": "sub-001",
                    "session_id": "ses-baseline",
                    "dicom_path": "/data/001/baseline",
                    "recruitment_id": "",
                },
            ]
        )
        state.register_sessions(first)

        second = pd.DataFrame(
            [
                {
                    "participant_id": "sub-001",
                    "session_id": "ses-baseline",
                    "dicom_path": "/data/001/baseline",
                    "recruitment_id": "",
                },
                {
                    "participant_id": "sub-002",
                    "session_id": "ses-baseline",
                    "dicom_path": "/data/002/baseline",
                    "recruitment_id": "",
                },
            ]
        )
        added = state.register_sessions(second)
        assert added == 1

        loaded = state.load_sessions()
        assert len(loaded) == 2


class TestUpdateSessionStatus:
    def test_update_status(self, state):
        """Update a session's status."""
        new_df = pd.DataFrame(
            [
                {
                    "participant_id": "sub-001",
                    "session_id": "ses-baseline",
                    "dicom_path": "/data/001",
                    "recruitment_id": "",
                },
            ]
        )
        state.register_sessions(new_df)

        state.update_session_status(
            "sub-001",
            "ses-baseline",
            status="validated",
            validation_message="Valid: 3 scan types",
            scans_found={"T1w": 176, "DWI": 60},
        )

        loaded = state.load_sessions()
        row = loaded.iloc[0]
        assert row["status"] == "validated"
        assert row["validation_message"] == "Valid: 3 scan types"
        assert json.loads(row["scans_found"]) == {"T1w": 176, "DWI": 60}

    def test_update_nonexistent_session(self, state):
        """Updating a nonexistent session does nothing (no error)."""
        state.update_session_status("nonexistent", "ses-01", status="validated")


class TestPipelineRuns:
    def test_record_pipeline_run(self, state):
        """Record a pipeline run."""
        state.record_pipeline_run(
            participant_id="sub-001",
            session_id="ses-baseline",
            pipeline_name="bids_conversion",
            status="completed",
            exit_code="0",
            duration_seconds="120.5",
        )

        df = state.load_pipeline_runs()
        assert len(df) == 1
        assert df.iloc[0]["pipeline_name"] == "bids_conversion"
        assert df.iloc[0]["status"] == "completed"

    def test_get_pipeline_summary(self, state):
        """Get grouped summary of pipeline runs."""
        state.record_pipeline_run(
            participant_id="sub-001",
            session_id="ses-baseline",
            pipeline_name="bids_conversion",
            status="completed",
        )
        state.record_pipeline_run(
            participant_id="sub-002",
            session_id="ses-baseline",
            pipeline_name="bids_conversion",
            status="completed",
        )
        state.record_pipeline_run(
            participant_id="sub-003",
            session_id="ses-baseline",
            pipeline_name="bids_conversion",
            status="failed",
        )

        summary = state.get_pipeline_summary()
        assert len(summary) == 2  # 2 groups: completed, failed


class TestGetPendingSessions:
    def test_no_validated_sessions(self, state):
        """No pending sessions when none are validated."""
        new_df = pd.DataFrame(
            [
                {
                    "participant_id": "sub-001",
                    "session_id": "ses-baseline",
                    "dicom_path": "/data/001",
                    "recruitment_id": "",
                },
            ]
        )
        state.register_sessions(new_df)

        pending = state.get_pending_sessions("bids_conversion")
        assert pending.empty

    def test_validated_sessions_are_pending(self, state):
        """Validated sessions without runs are pending."""
        new_df = pd.DataFrame(
            [
                {
                    "participant_id": "sub-001",
                    "session_id": "ses-baseline",
                    "dicom_path": "/data/001",
                    "recruitment_id": "",
                },
            ]
        )
        state.register_sessions(new_df)
        state.update_session_status("sub-001", "ses-baseline", status="validated")

        pending = state.get_pending_sessions("bids_conversion")
        assert len(pending) == 1

    def test_completed_sessions_not_pending(self, state):
        """Sessions with completed pipeline runs are not pending."""
        new_df = pd.DataFrame(
            [
                {
                    "participant_id": "sub-001",
                    "session_id": "ses-baseline",
                    "dicom_path": "/data/001",
                    "recruitment_id": "",
                },
            ]
        )
        state.register_sessions(new_df)
        state.update_session_status("sub-001", "ses-baseline", status="validated")
        state.record_pipeline_run(
            participant_id="sub-001",
            session_id="ses-baseline",
            pipeline_name="bids_conversion",
            status="completed",
        )

        pending = state.get_pending_sessions("bids_conversion")
        assert pending.empty

    def test_failed_runs_still_pending(self, state):
        """Sessions with only failed runs are still pending."""
        new_df = pd.DataFrame(
            [
                {
                    "participant_id": "sub-001",
                    "session_id": "ses-baseline",
                    "dicom_path": "/data/001",
                    "recruitment_id": "",
                },
            ]
        )
        state.register_sessions(new_df)
        state.update_session_status("sub-001", "ses-baseline", status="validated")
        state.record_pipeline_run(
            participant_id="sub-001",
            session_id="ses-baseline",
            pipeline_name="bids_conversion",
            status="failed",
        )

        pending = state.get_pending_sessions("bids_conversion")
        assert len(pending) == 1
