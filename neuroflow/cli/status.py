"""Status CLI command."""

import csv
import json
import sys
from io import StringIO

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.command("status")
@click.option("--sessions", is_flag=True, help="Show session details")
@click.option("--pipelines", is_flag=True, help="Show pipeline run details")
@click.option("--format", "output_format", default="table", type=click.Choice(["table", "csv", "json"]), help="Output format")
@click.option("--filter", "status_filter", default="all", type=click.Choice(["all", "queued", "running", "completed", "failed"]), help="Filter by status (default: all)")
@click.option("--watch", is_flag=True, help="Refresh display every 5 seconds (Ctrl+C to exit)")
@click.option("--interval", default=5, type=click.IntRange(min=1), help="Watch interval in seconds (default: 5)")
@click.pass_context
def status(
    ctx: click.Context,
    sessions: bool,
    pipelines: bool,
    output_format: str,
    status_filter: str,
    watch: bool,
    interval: int,
) -> None:
    """Show system status from CSV state.

    Examples:
        # Show summary
        neuroflow status

        # Show all pipeline runs
        neuroflow status --pipelines

        # Show only queued tasks
        neuroflow status --pipelines --filter queued

        # Watch status in real-time
        neuroflow status --pipelines --watch

        # Watch with custom interval
        neuroflow status --pipelines --watch --interval 10
    """
    from neuroflow.state import SessionState

    config = ctx.obj["config"]

    if watch:
        # Watch mode: refresh display
        if output_format != "table":
            console.print("[yellow]Watch mode only works with table format[/yellow]")
            sys.exit(1)

        _watch_status(config, sessions, pipelines, status_filter, interval)
    else:
        # Single display
        state = SessionState(config.execution.state_dir)

        if sessions:
            _show_sessions(state, output_format)
        elif pipelines:
            _show_pipelines(state, output_format, status_filter)
        else:
            _show_summary(state)


def _show_summary(state: "SessionState", skip_huey_config: bool = False) -> None:
    """Show overall summary counts.
    
    Args:
        state: SessionState instance
        skip_huey_config: If True, skip Huey configuration (already done by caller)
    """

    sessions_df = state.get_session_table()
    pipeline_df = state.get_pipeline_summary()

    console.print("\n[bold]Neuroflow Status[/bold]\n")

    if sessions_df.empty:
        console.print("[dim]No data yet. Run 'neuroflow scan' to discover sessions.[/dim]")
        return

    # Worker status
    _show_worker_status(state, skip_huey_config=skip_huey_config)
    console.print()

    console.print(f"Sessions: {len(sessions_df)}\n")

    # Session status counts
    if not sessions_df.empty:
        status_counts = sessions_df["status"].value_counts()
        table = Table(title="Sessions by Status")
        table.add_column("Status")
        table.add_column("Count", justify="right")
        for status_val, count in status_counts.items():
            style = {
                "completed": "green",
                "failed": "red",
                "validated": "green",
                "invalid": "red",
                "discovered": "yellow",
            }.get(status_val, "white")
            table.add_row(f"[{style}]{status_val}[/]", str(count))
        console.print(table)

    # Pipeline run summary
    if not pipeline_df.empty:
        console.print()
        table = Table(title="Pipeline Runs")
        table.add_column("Pipeline")
        table.add_column("Status")
        table.add_column("Count", justify="right")
        for _, row in pipeline_df.iterrows():
            style = {
                "completed": "green",
                "failed": "red",
                "running": "yellow",
                "queued": "cyan",
            }.get(row["status"], "white")
            table.add_row(
                row["pipeline_name"],
                f"[{style}]{row['status']}[/]",
                str(row["count"]),
            )
        console.print(table)


def _show_worker_status(state: "SessionState", skip_huey_config: bool = False) -> None:
    """Show worker and queue status.
    
    Args:
        state: SessionState instance
        skip_huey_config: If True, skip Huey configuration (already done by caller)
    """
    from pathlib import Path
    from neuroflow.tasks import configure_huey, get_queue_stats

    # Get queue stats - wrap everything including configure_huey in try-except
    try:
        if not skip_huey_config:
            # Configure Huey to use correct state directory
            # This may fail on read-only mounts or permission errors
            configure_huey(Path(state.state_dir))

        stats = get_queue_stats()
        queued_count = stats.get("pending", 0) + stats.get("scheduled", 0)

        # Check if worker is running
        from neuroflow.cli.worker import _read_pid, _get_pid_file

        pid_file = _get_pid_file(Path(state.state_dir))
        worker_pid = _read_pid(pid_file)

        if worker_pid:
            worker_status = f"[green]✓[/green] Running (PID: {worker_pid})"
        else:
            worker_status = "[yellow]✗[/yellow] Not running"

        # Display compact status line
        queue_display = f"[cyan]{queued_count}[/cyan]" if queued_count > 0 else f"[dim]{queued_count}[/dim]"
        console.print(f"Worker: {worker_status}  |  Queue: {queue_display} queued")

    except Exception as e:
        # Gracefully handle failures (read-only dirs, permission errors, etc.)
        console.print(f"[dim]Worker status: unavailable ({e})[/dim]")


def _show_sessions(state: "SessionState", output_format: str) -> None:
    """Show session details."""
    df = state.get_session_table()

    if df.empty:
        console.print("[yellow]No sessions found.[/yellow]")
        return

    if output_format == "csv":
        console.print(df.to_csv(index=False))
    elif output_format == "json":
        console.print(df.to_json(orient="records", indent=2))
    else:
        table = Table(title=f"Sessions ({len(df)} total)")
        table.add_column("Participant", style="cyan")
        table.add_column("Session", style="cyan")
        table.add_column("Status", style="bold")
        table.add_column("Validation")
        table.add_column("DICOM Path")

        for _, row in df.iterrows():
            status_val = row.get("status", "")
            style = {
                "validated": "green",
                "invalid": "red",
                "failed": "red",
                "discovered": "yellow",
            }.get(status_val, "white")

            table.add_row(
                row["participant_id"],
                row["session_id"],
                f"[{style}]{status_val}[/]",
                str(row.get("validation_message", ""))[:40],
                str(row.get("dicom_path", ""))[:50],
            )

        console.print(table)


def _show_pipelines(state: "SessionState", output_format: str, status_filter: str = "all", skip_huey_config: bool = False) -> None:
    """Show pipeline run details, including queued tasks.
    
    Args:
        state: SessionState instance
        output_format: Output format (table/csv/json)
        status_filter: Status filter (all/queued/running/completed/failed)
        skip_huey_config: If True, skip Huey configuration (already done by caller)
    """
    import pandas as pd
    from pathlib import Path
    from neuroflow.tasks import configure_huey, get_queue_details

    # Get completed/failed runs from state
    df = state.load_pipeline_runs()

    # Get queued tasks from queue - wrap in try-except to handle read-only state dirs
    try:
        if not skip_huey_config:
            # Configure Huey to use correct state directory
            # This may fail on read-only mounts or permission errors
            configure_huey(Path(state.state_dir))

        queue_details = get_queue_details()
        if queue_details:
            # Convert queue details to DataFrame
            queue_df = pd.DataFrame(queue_details)
            # Add empty columns to match state schema
            queue_df["duration_seconds"] = ""
            queue_df["exit_code"] = ""
            queue_df["start_time"] = ""
            queue_df["end_time"] = ""
            queue_df["error_message"] = ""

            # Combine with existing runs, avoiding duplicate queued/scheduled entries
            if not df.empty:
                key_cols = ["participant_id", "session_id", "pipeline_name"]
                # Only attempt de-duplication if all key columns are present in both DataFrames
                if all(col in df.columns for col in key_cols) and all(col in queue_df.columns for col in key_cols):
                    # Identify keys present in the queue and drop matching queued/scheduled state rows
                    queued_keys = queue_df[key_cols].drop_duplicates()
                    df = df.merge(
                        queued_keys.assign(_nf_in_queue=True),
                        on=key_cols,
                        how="left",
                    )
                    df = df[~(df["_nf_in_queue"] & df["status"].isin(["queued", "scheduled"]))]
                    df = df.drop(columns=["_nf_in_queue"])
                df = pd.concat([queue_df, df], ignore_index=True)
            else:
                df = queue_df
    except Exception as e:
        # Gracefully skip queue details if configure_huey fails (read-only dirs, etc.)
        # Status command should remain read-only and work even without queue access
        pass  # Silently skip queue details, continue with state data only

    if df.empty:
        console.print("[yellow]No pipeline runs found.[/yellow]")
        return

    # Apply status filter
    if status_filter != "all":
        df = df[df["status"] == status_filter]

        if df.empty:
            console.print(f"[yellow]No pipeline runs with status '{status_filter}'.[/yellow]")
            return

    if output_format == "csv":
        console.print(df.to_csv(index=False))
    elif output_format == "json":
        console.print(df.to_json(orient="records", indent=2))
    else:
        filter_text = f" (filtered: {status_filter})" if status_filter != "all" else ""
        table = Table(title=f"Pipeline Runs ({len(df)} total{filter_text})")
        table.add_column("Participant", style="cyan")
        table.add_column("Session", style="cyan")
        table.add_column("Pipeline")
        table.add_column("Status", style="bold")
        table.add_column("Duration")
        table.add_column("Task / Exit")

        for _, row in df.iterrows():
            status_val = row.get("status", "")
            style = {
                "completed": "green",
                "failed": "red",
                "running": "yellow",
                "queued": "cyan",
                "scheduled": "blue",
            }.get(status_val, "white")

            duration = row.get("duration_seconds", "")
            if duration and duration != "nan" and duration != "":
                try:
                    duration = f"{float(duration):.1f}s"
                except (ValueError, TypeError):
                    duration = ""

            # Show task ID for queued tasks, exit code for completed
            task_info = ""
            if status_val in ("queued", "scheduled"):
                task_id = str(row.get("task_id", ""))
                task_info = task_id[:8] if task_id else ""  # Show first 8 chars
            else:
                exit_code = row.get("exit_code", "")
                task_info = f"exit: {exit_code}" if exit_code else ""

            table.add_row(
                row["participant_id"],
                row["session_id"],
                row["pipeline_name"],
                f"[{style}]{status_val}[/]",
                str(duration) if duration else "[dim]-[/dim]",
                task_info if task_info else "[dim]-[/dim]",
            )

        console.print(table)

def _watch_status(
    config: "NeuroflowConfig",
    sessions: bool,
    pipelines: bool,
    status_filter: str,
    interval: int,
) -> None:
    """Watch status with automatic refresh.

    Args:
        config: Neuroflow configuration
        sessions: Show session details
        pipelines: Show pipeline details
        status_filter: Status filter for pipelines
        interval: Refresh interval in seconds
    """
    import time
    from pathlib import Path
    from neuroflow.state import SessionState
    from neuroflow.tasks import configure_huey

    # Configure Huey once at the start (not on every refresh)
    huey_configured = False
    try:
        state_dir = Path(config.execution.state_dir)
        configure_huey(state_dir)
        huey_configured = True
    except Exception:
        # If Huey configuration fails, continue without queue integration
        pass

    console.print(f"[dim]Watching status (refresh every {interval}s, Ctrl+C to exit)...[/dim]\n")

    try:
        while True:
            # Clear screen
            console.clear()

            # Reload state
            state = SessionState(config.execution.state_dir)

            # Display status (skip Huey config since we did it once above)
            if sessions:
                _show_sessions(state, "table")
            elif pipelines:
                _show_pipelines(state, "table", status_filter, skip_huey_config=huey_configured)
            else:
                _show_summary(state, skip_huey_config=huey_configured)

            # Show refresh info
            import datetime
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            console.print(f"\n[dim]Last updated: {now} | Refresh every {interval}s | Press Ctrl+C to exit[/dim]")

            # Wait for next refresh
            time.sleep(interval)

    except KeyboardInterrupt:
        console.print("\n[dim]Watch mode stopped[/dim]")
        sys.exit(0)
