#!/usr/bin/env python3
"""
Example: QSIPrep Diffusion Preprocessing

This script demonstrates how to preprocess diffusion MRI data using QSIPrep
through the VoxelOps adapter.

Requirements:
- VoxelOps installed
- BIDS-formatted data with DWI sequences
- FreeSurfer license configured
"""

import sys
from pathlib import Path

from neuroflow.adapters.voxelops import VoxelopsAdapter
from neuroflow.config import NeuroflowConfig
from neuroflow.core.state import StateManager
from neuroflow.models.session import Session


def check_dwi_data(session: Session, bids_root: Path) -> bool:
    """Check if session has DWI data in BIDS format.

    Args:
        session: Database session object
        bids_root: Path to BIDS root directory

    Returns:
        True if DWI data exists
    """
    # Construct expected DWI path
    participant = session.subject.participant_id
    session_label = session.session_id

    dwi_dir = bids_root / f"sub-{participant}" / f"ses-{session_label}" / "dwi"
    print(dwi_dir)

    if not dwi_dir.exists():
        return False

    # Check for DWI NIfTI files
    dwi_files = list(dwi_dir.glob("*_dwi.nii.gz"))
    return len(dwi_files) > 0


def run_qsiprep_for_session(
    config_path: str,
    session_id: int,
    force: bool = False,
    nprocs: int = None,
    mem_mb: int = None,
):
    """Run QSIPrep preprocessing for a session.

    Args:
        config_path: Path to neuroflow configuration
        session_id: Database ID of session to process
        force: Force reprocessing even if outputs exist
        nprocs: Number of CPUs (overrides config)
        mem_mb: Memory limit in MB (overrides config)
    """
    # Load configuration
    print(f"Loading configuration from {config_path}")
    config = NeuroflowConfig.from_yaml(config_path)

    # Verify FreeSurfer license
    qsiprep_cfg = None
    for pipeline in config.pipelines.subject_level:
        if pipeline.name == "qsiprep":
            qsiprep_cfg = pipeline
            break

    if not qsiprep_cfg:
        print("ERROR: QSIPrep not configured in neuroflow.yaml")
        sys.exit(1)

    fs_license = qsiprep_cfg.voxelops_config.get("fs_license")
    if not fs_license or not Path(fs_license).exists():
        print(f"ERROR: FreeSurfer license not found: {fs_license}")
        print("Obtain license from: https://surfer.nmr.mgh.harvard.edu/registration.html")
        sys.exit(1)

    # Get session from database
    state = StateManager(config)
    with state.get_session() as db:
        session = db.get(Session, session_id)
        if not session:
            print(f"ERROR: Session {session_id} not found")
            sys.exit(1)

        print(f"\nSession Information:")
        print(f"  Subject: {session.subject.participant_id}")
        print(f"  Session: {session.session_id}")

        # Check for DWI data
        if not check_dwi_data(session, config.paths.bids_root):
            print("\nERROR: No DWI data found in BIDS directory")
            print(
                f"  Expected: {config.paths.bids_root}/{session.subject.participant_id}/{session.session_id}/dwi/"
            )
            print("\nRun BIDS conversion first: python 01_bids_conversion.py")
            sys.exit(1)

        print("  DWI data: ✓ Found")

    # Prepare runtime parameters
    kwargs = {}
    if force:
        kwargs["force"] = True
    if nprocs:
        kwargs["nprocs"] = nprocs
    if mem_mb:
        kwargs["mem_mb"] = mem_mb

    # Display configuration
    print("\nQSIPrep Configuration:")
    print(f"  CPUs: {nprocs or qsiprep_cfg.voxelops_config.get('nprocs', 8)}")
    print(f"  Memory: {mem_mb or qsiprep_cfg.voxelops_config.get('mem_mb', 16000)} MB")
    print(f"  Output resolution: {qsiprep_cfg.voxelops_config.get('output_resolution', 1.6)} mm")
    print(f"  Force reprocessing: {force}")
    print(f"  FreeSurfer license: {fs_license}")

    # Estimate processing time
    print("\nEstimated processing time: 4-12 hours (depending on hardware)")
    response = input("Continue? [y/N]: ")
    if response.lower() != "y":
        print("Cancelled")
        sys.exit(0)

    # Run QSIPrep
    print("\nStarting QSIPrep preprocessing...")
    adapter = VoxelopsAdapter(config)

    if not adapter._voxelops_available:
        print("WARNING: VoxelOps not available, will use container mode")

    result = adapter.run("qsiprep", session_id=session_id, **kwargs)

    # Display results
    print("\n" + "=" * 60)
    if result.success:
        print("✓ QSIPrep Successful!")
        print(
            f"  Duration: {result.duration_seconds / 60:.1f} minutes ({result.duration_seconds / 3600:.1f} hours)"
        )
        print(f"  Output: {result.output_path}")

        if result.metrics and result.metrics.get("skipped"):
            print(f"  Note: {result.metrics['reason']}")
        else:
            # Check outputs
            if result.output_path:
                preproc_files = list(result.output_path.rglob("*_desc-preproc_dwi.nii.gz"))
                print(f"  Preprocessed DWI files: {len(preproc_files)}")

                html_reports = list(result.output_path.rglob("*.html"))
                if html_reports:
                    print(f"  Quality reports: {len(html_reports)}")
                    print(f"    View: {html_reports[0]}")
    else:
        print("✗ QSIPrep Failed")
        print(f"  Exit Code: {result.exit_code}")
        print(f"  Error: {result.error_message}")

        if result.logs:
            print("\n  Last 30 lines of logs:")
            log_lines = result.logs.split("\n")
            for line in log_lines[-30:]:
                print(f"    {line}")

    print("=" * 60)

    return result.success


def batch_process_sessions(config_path: str, force: bool = False):
    """Run QSIPrep on all sessions with DWI data.

    Args:
        config_path: Path to neuroflow configuration
        force: Force reprocessing
    """
    config = NeuroflowConfig.from_yaml(config_path)
    state = StateManager(config)

    # Find sessions with DWI data
    sessions_with_dwi = []
    with state.get_session() as db:
        all_sessions = db.query(Session).all()
        print("Scanning for sessions with DWI data...")
        for session in all_sessions:
            if check_dwi_data(session, config.paths.bids_root):
                # Extract data while in session context
                subject_id = session.subject.participant_id
                session_label = session.session_id
                sessions_with_dwi.append(session.id)
                print(f"  ✓ {subject_id}/{session_label}")

    if not sessions_with_dwi:
        print("\nNo sessions with DWI data found")
        return

    print(f"\nFound {len(sessions_with_dwi)} sessions with DWI data")
    print(
        f"Estimated total time: {len(sessions_with_dwi) * 6} - {len(sessions_with_dwi) * 12} hours"
    )
    response = input(f"\nProcess all {len(sessions_with_dwi)} sessions? [y/N]: ")
    if response.lower() != "y":
        print("Cancelled")
        return

    # Process each session
    adapter = VoxelopsAdapter(config)
    results = {"success": 0, "failed": 0, "skipped": 0}

    for i, session_id in enumerate(sessions_with_dwi, 1):
        print(f"\n{'=' * 60}")
        print(f"[{i}/{len(sessions_with_dwi)}] Processing session {session_id}")
        print("=" * 60)

        result = adapter.run("qsiprep", session_id=session_id, force=force)

        if result.success:
            if result.metrics and result.metrics.get("skipped"):
                results["skipped"] += 1
            else:
                results["success"] += 1
        else:
            results["failed"] += 1
            print(f"  Failed: {result.error_message}")

    # Summary
    print("\n" + "=" * 60)
    print("Batch Processing Summary:")
    print(f"  Successful: {results['success']}")
    print(f"  Skipped: {results['skipped']}")
    print(f"  Failed: {results['failed']}")
    print("=" * 60)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Run QSIPrep diffusion preprocessing via VoxelOps")
    parser.add_argument(
        "--config",
        default="neuroflow.yaml",
        help="Path to neuroflow configuration",
    )
    parser.add_argument(
        "--session-id",
        type=int,
        help="Database ID of session to process",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all sessions with DWI data",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reprocessing even if outputs exist",
    )
    parser.add_argument(
        "--nprocs",
        type=int,
        help="Number of CPUs (overrides config)",
    )
    parser.add_argument(
        "--mem-mb",
        type=int,
        help="Memory limit in MB (overrides config)",
    )

    args = parser.parse_args()

    if args.all:
        batch_process_sessions(args.config, force=args.force)
    elif args.session_id:
        success = run_qsiprep_for_session(
            args.config,
            args.session_id,
            force=args.force,
            nprocs=args.nprocs,
            mem_mb=args.mem_mb,
        )
        sys.exit(0 if success else 1)
    else:
        parser.print_help()
        print("\nERROR: Must specify either --session-id or --all")
        sys.exit(1)


if __name__ == "__main__":
    main()
