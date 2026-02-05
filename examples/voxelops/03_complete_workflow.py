#!/usr/bin/env python3
"""
Example: Complete Diffusion MRI Workflow

This script demonstrates a complete end-to-end workflow:
1. BIDS conversion with HeudiConv
2. Preprocessing with QSIPrep
3. Reconstruction with QSIRecon
4. Parcellation with QSIParc

Requirements:
- VoxelOps installed
- All pipeline configurations set up
- FreeSurfer license configured
"""

import sys
import time
from datetime import datetime
from pathlib import Path

from neuroflow.adapters.voxelops import VoxelopsAdapter
from neuroflow.config import NeuroflowConfig
from neuroflow.core.state import StateManager
from neuroflow.models.session import Session


class WorkflowRunner:
    """Manages complete diffusion MRI workflow execution."""

    def __init__(self, config_path: str):
        """Initialize workflow runner.

        Args:
            config_path: Path to neuroflow configuration
        """
        self.config = NeuroflowConfig.from_yaml(config_path)
        self.adapter = VoxelopsAdapter(self.config)
        self.state = StateManager(self.config)

        # Track execution
        self.start_time = None
        self.results = {
            "bids_conversion": None,
            "qsiprep": None,
            "qsirecon": None,
            "qsiparc": None,
        }

    def run_complete_workflow(
        self,
        session_id: int,
        skip_existing: bool = True,
        save_report: bool = True,
    ) -> bool:
        """Run complete workflow for a session.

        Args:
            session_id: Database ID of session to process
            skip_existing: Skip steps if outputs already exist
            save_report: Save workflow report to file

        Returns:
            True if entire workflow succeeded
        """
        self.start_time = datetime.now()

        # Get session info - extract data within database context
        with self.state.get_session() as db:
            session = db.get(Session, session_id)
            if not session:
                print(f"ERROR: Session {session_id} not found")
                return False

            # Extract all needed data within context to avoid DetachedInstanceError
            subject_id = session.subject_id
            participant_id = session.subject.participant_id
            session_label = session.session_id

        print("=" * 70)
        print("COMPLETE DIFFUSION MRI WORKFLOW")
        print("=" * 70)
        print(f"Subject: {participant_id}")
        print(f"Session: {session_label}")
        print(f"Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)

        # Step 1: BIDS Conversion
        success = self._run_step(
            "BIDS Conversion",
            "bids_conversion",
            session_id=session_id,
            force=not skip_existing,
        )
        if not success:
            return self._finalize_workflow(save_report, session_id)

        # Step 2: QSIPrep Preprocessing
        success = self._run_step(
            "QSIPrep Preprocessing",
            "qsiprep",
            session_id=session_id,
            force=not skip_existing,
        )
        if not success:
            return self._finalize_workflow(save_report, session_id)

        # Step 3: QSIRecon Reconstruction
        success = self._run_step(
            "QSIRecon Reconstruction",
            "qsirecon",
            subject_id=subject_id,
            force=not skip_existing,
        )
        if not success:
            return self._finalize_workflow(save_report, session_id)

        # Step 4: QSIParc Parcellation
        success = self._run_step(
            "QSIParc Parcellation",
            "qsiparc",
            subject_id=subject_id,
            force=not skip_existing,
        )

        return self._finalize_workflow(save_report, session_id)

    def _run_step(
        self,
        step_name: str,
        pipeline_name: str,
        **kwargs
    ) -> bool:
        """Run a single workflow step.

        Args:
            step_name: Human-readable step name
            pipeline_name: Pipeline identifier
            **kwargs: Arguments for adapter.run()

        Returns:
            True if step succeeded
        """
        print(f"\n{'─' * 70}")
        print(f"Step: {step_name}")
        print(f"{'─' * 70}")

        step_start = time.time()

        try:
            result = self.adapter.run(pipeline_name, **kwargs)
            self.results[pipeline_name] = result

            duration = time.time() - step_start

            if result.success:
                if result.metrics and result.metrics.get("skipped"):
                    print(f"✓ {step_name} - Skipped (outputs exist)")
                    print(f"  Reason: {result.metrics['reason']}")
                else:
                    print(f"✓ {step_name} - Success")
                    print(f"  Duration: {duration / 60:.1f} minutes")

                if result.output_path:
                    print(f"  Output: {result.output_path}")

                return True
            else:
                print(f"✗ {step_name} - Failed")
                print(f"  Error: {result.error_message}")
                print(f"  Duration: {duration / 60:.1f} minutes")
                return False

        except Exception as e:
            print(f"✗ {step_name} - Exception")
            print(f"  Error: {str(e)}")
            self.results[pipeline_name] = None
            return False

    def _finalize_workflow(self, save_report: bool, session_id: int) -> bool:
        """Finalize workflow and print summary.

        Args:
            save_report: Whether to save report to file
            session_id: Session database ID

        Returns:
            True if all steps succeeded
        """
        end_time = datetime.now()
        total_duration = (end_time - self.start_time).total_seconds()

        print("\n" + "=" * 70)
        print("WORKFLOW SUMMARY")
        print("=" * 70)

        # Check each step
        all_success = True
        for pipeline_name, result in self.results.items():
            if result is None:
                status = "Not Run"
                all_success = False
            elif result.success:
                if result.metrics and result.metrics.get("skipped"):
                    status = "Skipped"
                else:
                    status = "Success"
            else:
                status = "Failed"
                all_success = False

            print(f"  {pipeline_name:20s}: {status}")

        print(f"\nTotal Duration: {total_duration / 60:.1f} minutes ({total_duration / 3600:.1f} hours)")
        print(f"Completed: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")

        if all_success:
            print("\n✓ Complete workflow finished successfully!")
        else:
            print("\n✗ Workflow incomplete or failed")

        print("=" * 70)

        # Save report
        if save_report:
            self._save_report(session_id, all_success, total_duration)

        return all_success

    def _save_report(self, session_id: int, success: bool, duration: float):
        """Save workflow report to file.

        Args:
            session_id: Session database ID
            success: Whether workflow succeeded
            duration: Total duration in seconds
        """
        # Extract session data within database context
        with self.state.get_session() as db:
            session = db.get(Session, session_id)
            # Access relationships within context to avoid DetachedInstanceError
            participant_id = session.subject.participant_id
            session_label = session.session_id

        # Create reports directory
        reports_dir = self.config.paths.work_dir / "reports"
        reports_dir.mkdir(exist_ok=True, parents=True)

        report_file = reports_dir / f"{participant_id}_{session_label}_workflow_{self.start_time.strftime('%Y%m%d_%H%M%S')}.txt"

        with open(report_file, 'w') as f:
            f.write("=" * 70 + "\n")
            f.write("DIFFUSION MRI WORKFLOW REPORT\n")
            f.write("=" * 70 + "\n\n")

            f.write(f"Subject: {participant_id}\n")
            f.write(f"Session: {session_label}\n")
            f.write(f"Session ID: {session_id}\n\n")

            f.write(f"Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Duration: {duration / 3600:.2f} hours\n\n")

            f.write(f"Status: {'SUCCESS' if success else 'FAILED'}\n\n")

            f.write("=" * 70 + "\n")
            f.write("PIPELINE RESULTS\n")
            f.write("=" * 70 + "\n\n")

            for pipeline_name, result in self.results.items():
                f.write(f"{pipeline_name}:\n")
                if result is None:
                    f.write("  Status: Not Run\n\n")
                else:
                    f.write(f"  Success: {result.success}\n")
                    f.write(f"  Exit Code: {result.exit_code}\n")
                    if result.duration_seconds:
                        f.write(f"  Duration: {result.duration_seconds / 60:.1f} minutes\n")
                    if result.output_path:
                        f.write(f"  Output: {result.output_path}\n")
                    if result.error_message:
                        f.write(f"  Error: {result.error_message}\n")
                    if result.metrics and result.metrics.get("skipped"):
                        f.write(f"  Note: Skipped - {result.metrics['reason']}\n")
                    f.write("\n")

        print(f"\nWorkflow report saved: {report_file}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run complete diffusion MRI workflow"
    )
    parser.add_argument(
        "--config",
        default="neuroflow.yaml",
        help="Path to neuroflow configuration",
    )
    parser.add_argument(
        "--session-id",
        type=int,
        required=True,
        help="Database ID of session to process",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reprocessing (don't skip existing outputs)",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Don't save workflow report",
    )

    args = parser.parse_args()

    # Create runner and execute workflow
    runner = WorkflowRunner(args.config)
    success = runner.run_complete_workflow(
        session_id=args.session_id,
        skip_existing=not args.force,
        save_report=not args.no_report,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
