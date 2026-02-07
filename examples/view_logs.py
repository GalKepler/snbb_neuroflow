#!/usr/bin/env python3
"""View logs for failed pipeline runs."""

import sys
from pathlib import Path

from neuroflow.config import NeuroflowConfig
from neuroflow.core.state import StateManager
from neuroflow.models import PipelineRun, PipelineRunStatus
from sqlalchemy import select


def main():
    """Main entry point."""
    config = NeuroflowConfig.find_and_load()
    state = StateManager(config)

    # Get recent failed runs
    with state.get_session() as db:
        failed_runs = db.execute(
            select(PipelineRun)
            .where(PipelineRun.status == PipelineRunStatus.FAILED)
            .order_by(PipelineRun.created_at.desc())
            .limit(10)
        ).scalars().all()

        if not failed_runs:
            print("✅ No failed runs found!")
            return

        print(f"\n❌ Found {len(failed_runs)} recent failed runs:\n")

        for i, run in enumerate(failed_runs, 1):
            print(f"{i}. Run #{run.id} - {run.pipeline_name}")
            if run.session_id:
                print(f"   Session ID: {run.session_id}")
            if run.subject_id:
                print(f"   Subject ID: {run.subject_id}")
            if run.completed_at:
                print(f"   Failed: {run.completed_at.strftime('%Y-%m-%d %H:%M:%S')}")
            print()

    # Let user select which to view
    choice = input("Enter number to view details (or 'q' to quit): ")

    if choice.lower() == 'q':
        return

    try:
        idx = int(choice) - 1
        run = failed_runs[idx]
    except (ValueError, IndexError):
        print("❌ Invalid choice")
        return

    # Show detailed info
    print(f"\n{'='*70}")
    print(f"Pipeline Run #{run.id}")
    print(f"{'='*70}")
    print(f"Pipeline: {run.pipeline_name}")
    print(f"Level: {run.pipeline_level}")
    print(f"Session ID: {run.session_id}")
    print(f"Subject ID: {run.subject_id}")
    print(f"Status: {run.status.value}")
    print(f"Exit Code: {run.exit_code}")
    print(f"Attempt: {run.attempt_number}")

    if run.started_at:
        print(f"Started: {run.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if run.completed_at:
        print(f"Completed: {run.completed_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if run.duration_seconds:
        print(f"Duration: {run.duration_seconds:.1f}s ({run.duration_seconds/60:.1f} min)")

    print(f"\n{'-'*70}")
    print("ERROR MESSAGE:")
    print(f"{'-'*70}")
    print(run.error_message or "No error message recorded")

    if run.error_traceback:
        print(f"\n{'-'*70}")
        print("TRACEBACK:")
        print(f"{'-'*70}")
        print(run.error_traceback)

    if run.log_path:
        log_path = Path(run.log_path)
        if log_path.exists():
            print(f"\n{'-'*70}")
            print(f"LOG FILE: {run.log_path}")
            print(f"{'-'*70}")

            view = input("\nView full log file? [y/N]: ")
            if view.lower() == 'y':
                with open(run.log_path) as f:
                    print(f.read())
            else:
                # Show last 50 lines
                with open(run.log_path) as f:
                    lines = f.readlines()
                    print("\nLast 50 lines:")
                    print('-'*70)
                    for line in lines[-50:]:
                        print(line.rstrip())
        else:
            print(f"\n⚠️  Log file not found: {run.log_path}")
    else:
        print("\n⚠️  No log file path recorded")

        # Try to find log in work directory
        work_dir = config.paths.work_dir
        possible_log = work_dir / run.pipeline_name / f"run_{run.id}" / "log"
        if possible_log.exists():
            print(f"\n💡 Found logs in work directory: {possible_log}")
            view = input("View? [y/N]: ")
            if view.lower() == 'y':
                for log_file in possible_log.glob("*.log"):
                    print(f"\n{'='*70}")
                    print(f"File: {log_file.name}")
                    print(f"{'='*70}")
                    with open(log_file) as f:
                        print(f.read())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
