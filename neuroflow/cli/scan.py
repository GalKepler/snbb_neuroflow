"""Scan CLI command."""

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.command("scan")
@click.pass_context
def scan(ctx: click.Context) -> None:
    """Scan for new DICOM sessions and register them."""
    from neuroflow.discovery.scanner import SessionScanner
    from neuroflow.state import SessionState

    config = ctx.obj["config"]
    state = SessionState(config.execution.state_dir)
    scanner = SessionScanner(config)

    with console.status("Scanning directories..."):
        sessions_df, scans_by_session = scanner.scan_all()

    if sessions_df.empty:
        console.print("[yellow]No sessions found.[/yellow]")
        return

    # Register into state
    new_count = state.register_sessions(sessions_df)

    # Display results
    table = Table(title=f"Found {len(sessions_df)} Sessions ({new_count} new)")
    table.add_column("Participant", style="cyan")
    table.add_column("Session", style="cyan")
    table.add_column("Recruitment ID", style="magenta")
    table.add_column("Scans", justify="right")
    table.add_column("Path")

    for _, row in sessions_df.iterrows():
        key = (row["participant_id"], row["session_id"])
        scans = scans_by_session.get(key, [])
        table.add_row(
            row["participant_id"],
            row["session_id"],
            row.get("recruitment_id", ""),
            str(len(scans)),
            str(row["dicom_path"])[:60],
        )

    console.print(table)
    console.print(f"\n[green]{new_count} new sessions registered.[/green]")
