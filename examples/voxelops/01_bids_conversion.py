#!/usr/bin/env python3
"""
Example: BIDS Conversion with HeudiConv

This script demonstrates how to convert DICOM files to BIDS format using
HeudiConv through the VoxelOps adapter.

Requirements:
- VoxelOps installed
- Heuristic file configured
- DICOM data in neuroflow database
"""

import sys
from pathlib import Path

from neuroflow.adapters.voxelops import VoxelopsAdapter
from neuroflow.config import NeuroflowConfig
from neuroflow.core.state import StateManager
from neuroflow.models.session import Session, SessionStatus


def convert_session_to_bids(config_path: str, session_id: int):
    """Convert a single session from DICOM to BIDS.

    Args:
        config_path: Path to neuroflow configuration file
        session_id: Database ID of session to convert
    """
    # Load configuration
    print(f"Loading configuration from {config_path}")
    config = NeuroflowConfig.from_yaml(config_path)

    # Verify heuristic file exists
    bids_cfg = config.pipelines.bids_conversion
    heuristic = bids_cfg.voxelops_config.get("heuristic")
    if not heuristic or not Path(heuristic).exists():
        print(f"ERROR: Heuristic file not found: {heuristic}")
        print("Please configure a valid heuristic file in neuroflow.yaml")
        sys.exit(1)

    # Get session information from database
    state = StateManager(config)
    with state.get_session() as db:
        session = db.get(Session, session_id)
        if not session:
            print(f"ERROR: Session {session_id} not found in database")
            sys.exit(1)

        print(f"\nSession Information:")
        print(f"  Subject: {session.subject.participant_id}")
        print(f"  Session: {session.session_id}")
        print(f"  DICOM Path: {session.dicom_path}")
        print(f"  Status: {session.status.value}")

        if session.status != SessionStatus.VALIDATED:
            print(f"\nWARNING: Session status is {session.status.value}, not VALIDATED")
            response = input("Continue anyway? [y/N]: ")
            if response.lower() != 'y':
                sys.exit(0)

    # Create adapter and run conversion
    print("\nInitializing VoxelOps adapter...")
    adapter = VoxelopsAdapter(config)

    if not adapter._voxelops_available:
        print("WARNING: VoxelOps not available, will use container mode")

    print(f"\nStarting BIDS conversion...")
    print(f"  Using heuristic: {heuristic}")
    print(f"  Output directory: {config.paths.bids_root}")

    result = adapter.run("bids_conversion", session_id=session_id)

    # Display results
    print("\n" + "=" * 60)
    if result.success:
        print("✓ BIDS Conversion Successful!")
        print(f"  Duration: {result.duration_seconds:.1f} seconds")
        print(f"  Output: {result.output_path}")

        if result.metrics and result.metrics.get("skipped"):
            print(f"  Note: {result.metrics['reason']}")

        # Verify outputs
        if result.output_path and result.output_path.exists():
            bids_files = list(result.output_path.rglob("*.nii.gz"))
            print(f"  NIfTI files created: {len(bids_files)}")
            if bids_files:
                print("\n  Sample outputs:")
                for f in bids_files[:5]:  # Show first 5
                    print(f"    - {f.relative_to(result.output_path)}")
                if len(bids_files) > 5:
                    print(f"    ... and {len(bids_files) - 5} more")
    else:
        print("✗ BIDS Conversion Failed")
        print(f"  Exit Code: {result.exit_code}")
        print(f"  Error: {result.error_message}")

        if result.logs:
            print("\n  Last 20 lines of logs:")
            log_lines = result.logs.split('\n')
            for line in log_lines[-20:]:
                print(f"    {line}")

    print("=" * 60)

    return result.success


def convert_all_validated_sessions(config_path: str):
    """Convert all validated sessions to BIDS.

    Args:
        config_path: Path to neuroflow configuration file
    """
    config = NeuroflowConfig.from_yaml(config_path)
    state = StateManager(config)

    # Query validated sessions
    with state.get_session() as db:
        sessions = db.query(Session).filter(
            Session.status == SessionStatus.VALIDATED
        ).all()

        print(f"Found {len(sessions)} validated sessions")

        if not sessions:
            print("No validated sessions to process")
            return

        # Confirm before batch processing
        print("\nSessions to process:")
        for s in sessions:
            print(f"  - {s.subject.participant_id} / {s.session_id}")

        response = input(f"\nProcess all {len(sessions)} sessions? [y/N]: ")
        if response.lower() != 'y':
            print("Cancelled")
            return

    # Process each session
    adapter = VoxelopsAdapter(config)
    results = {"success": 0, "failed": 0, "skipped": 0}

    for i, session in enumerate(sessions, 1):
        print(f"\n[{i}/{len(sessions)}] Processing {session.subject.participant_id}/{session.session_id}")

        result = adapter.run("bids_conversion", session_id=session.id)

        if result.success:
            if result.metrics and result.metrics.get("skipped"):
                results["skipped"] += 1
                print("  → Skipped (outputs exist)")
            else:
                results["success"] += 1
                print("  → Success")
        else:
            results["failed"] += 1
            print(f"  → Failed: {result.error_message}")

    # Summary
    print("\n" + "=" * 60)
    print("Batch Conversion Summary:")
    print(f"  Successful: {results['success']}")
    print(f"  Skipped: {results['skipped']}")
    print(f"  Failed: {results['failed']}")
    print("=" * 60)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert DICOM to BIDS using HeudiConv via VoxelOps"
    )
    parser.add_argument(
        "--config",
        default="neuroflow.yaml",
        help="Path to neuroflow configuration (default: neuroflow.yaml)",
    )
    parser.add_argument(
        "--session-id",
        type=int,
        help="Database ID of session to convert",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Convert all validated sessions",
    )

    args = parser.parse_args()

    if args.all:
        convert_all_validated_sessions(args.config)
    elif args.session_id:
        success = convert_session_to_bids(args.config, args.session_id)
        sys.exit(0 if success else 1)
    else:
        parser.print_help()
        print("\nERROR: Must specify either --session-id or --all")
        sys.exit(1)


if __name__ == "__main__":
    main()
