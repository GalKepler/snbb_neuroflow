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
@click.option("--interval", default=5, type=int, help="Watch interval in seconds (default: 5)")
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


def _show_summary(state: "SessionState") -> None:
    """Show overall summary counts."""
    from pathlib import Path

    sessions_df = state.get_session_table()
    pipeline_df = state.get_pipeline_summary()

    console.print("\n[bold]Neuroflow Status[/bold]\n")

    if sessions_df.empty:
        console.print("[dim]No data yet. Run 'neuroflow scan' to discover sessions.[/dim]")
        return

    # Worker status
    _show_worker_status(state)
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


def _show_worker_status(state: "SessionState") -> None:
    """Show worker and queue status."""
    from pathlib import Path
    from neuroflow.tasks import configure_huey, get_queue_stats

    # Configure Huey to use correct state directory
    configure_huey(Path(state.state_dir))

    # Get queue stats
    try:
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
        console.print(f"Worker: {worker_status}  |  Queue: {queue_display} pending")

    except Exception as e:
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


def _show_pipelines(state: "SessionState", output_format: str, status_filter: str = "all") -> None:
    """Show pipeline run details, including queued tasks."""
    import pandas as pd
    from pathlib import Path
    from neuroflow.tasks import configure_huey, get_queue_details

    # Configure Huey to use correct state directory
    configure_huey(Path(state.state_dir))

    # Get completed/failed runs from state
    df = state.load_pipeline_runs()

    # Get queued tasks from queue
    try:
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

            # Combine with existing runs
            if not df.empty:
                df = pd.concat([queue_df, df], ignore_index=True)
            else:
                df = queue_df
    except Exception as e:
        console.print(f"[dim]Warning: Could not fetch queue details: {e}[/dim]")

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
        table.add_column("Task ID")

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
    from neuroflow.state import SessionState

    console.print(f"[dim]Watching status (refresh every {interval}s, Ctrl+C to exit)...[/dim]\n")

    try:
        while True:
            # Clear screen
            console.clear()

            # Reload state
            state = SessionState(config.execution.state_dir)

            # Display status
            if sessions:
                _show_sessions(state, "table")
            elif pipelines:
                _show_pipelines(state, "table", status_filter)
            else:
                _show_summary(state)

            # Show refresh info
            import datetime
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            console.print(f"\n[dim]Last updated: {now} | Refresh every {interval}s | Press Ctrl+C to exit[/dim]")

            # Wait for next refresh
            time.sleep(interval)

    except KeyboardInterrupt:
        console.print("\n[dim]Watch mode stopped[/dim]")
        sys.exit(0)
