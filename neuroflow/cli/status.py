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
@click.pass_context
def status(
    ctx: click.Context,
    sessions: bool,
    pipelines: bool,
    output_format: str,
) -> None:
    """Show system status from CSV state."""
    from neuroflow.state import SessionState

    config = ctx.obj["config"]
    state = SessionState(config.execution.state_dir)

    if sessions:
        _show_sessions(state, output_format)
    elif pipelines:
        _show_pipelines(state, output_format)
    else:
        _show_summary(state)


def _show_summary(state: "SessionState") -> None:
    """Show overall summary counts."""
    sessions_df = state.get_session_table()
    pipeline_df = state.get_pipeline_summary()

    console.print("\n[bold]Neuroflow Status[/bold]\n")

    if sessions_df.empty:
        console.print("[dim]No data yet. Run 'neuroflow scan' to discover sessions.[/dim]")
        return

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
            }.get(row["status"], "white")
            table.add_row(
                row["pipeline_name"],
                f"[{style}]{row['status']}[/]",
                str(row["count"]),
            )
        console.print(table)


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


def _show_pipelines(state: "SessionState", output_format: str) -> None:
    """Show pipeline run details."""
    df = state.load_pipeline_runs()

    if df.empty:
        console.print("[yellow]No pipeline runs found.[/yellow]")
        return

    if output_format == "csv":
        console.print(df.to_csv(index=False))
    elif output_format == "json":
        console.print(df.to_json(orient="records", indent=2))
    else:
        table = Table(title=f"Pipeline Runs ({len(df)} total)")
        table.add_column("Participant", style="cyan")
        table.add_column("Session", style="cyan")
        table.add_column("Pipeline")
        table.add_column("Status", style="bold")
        table.add_column("Duration")
        table.add_column("Exit Code", justify="right")

        for _, row in df.iterrows():
            status_val = row.get("status", "")
            style = {
                "completed": "green",
                "failed": "red",
                "running": "yellow",
            }.get(status_val, "white")

            duration = row.get("duration_seconds", "")
            if duration and duration != "nan":
                try:
                    duration = f"{float(duration):.1f}s"
                except (ValueError, TypeError):
                    pass

            table.add_row(
                row["participant_id"],
                row["session_id"],
                row["pipeline_name"],
                f"[{style}]{status_val}[/]",
                str(duration),
                str(row.get("exit_code", "")),
            )

        console.print(table)
