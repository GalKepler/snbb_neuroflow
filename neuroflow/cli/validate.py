"""Validate CLI command."""

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.command("validate")
@click.pass_context
def validate(ctx: click.Context) -> None:
    """Validate discovered sessions against protocol requirements."""
    from neuroflow.discovery.scanner import SessionScanner
    from neuroflow.discovery.validator import SessionValidator
    from neuroflow.state import SessionState

    config = ctx.obj["config"]
    state = SessionState(config.execution.state_dir)
    scanner = SessionScanner(config)
    validator = SessionValidator(config)

    sessions = state.load_sessions()

    # Only validate discovered or previously invalidated sessions
    to_validate = sessions[sessions["status"].isin(["discovered", "invalid"])]

    if to_validate.empty:
        console.print("[yellow]No sessions to validate.[/yellow]")
        return

    console.print(f"[cyan]Validating {len(to_validate)} sessions...[/cyan]\n")

    results = {"valid": 0, "invalid": 0, "errors": 0}
    failed_sessions: list[tuple[str, str, str]] = []

    for _, row in to_validate.iterrows():
        participant_id = row["participant_id"]
        session_id = row["session_id"]
        dicom_path = Path(row["dicom_path"])

        try:
            with console.status(f"Validating {participant_id}/{session_id}..."):
                scans = scanner._identify_scans(dicom_path)
                result = validator.validate(scans)

                scans_found = result.scans_found
                status = "validated" if result.is_valid else "invalid"

                state.update_session_status(
                    participant_id=participant_id,
                    session_id=session_id,
                    status=status,
                    validation_message=result.message,
                    scans_found=scans_found,
                )

                if result.is_valid:
                    results["valid"] += 1
                    console.print(f"  [green]\u2713 {participant_id}/{session_id}[/green]")
                else:
                    results["invalid"] += 1
                    failed_sessions.append((participant_id, session_id, result.message))
                    console.print(
                        f"  [red]\u2717 {participant_id}/{session_id}[/red]: {result.message}"
                    )

        except Exception as e:
            results["errors"] += 1
            console.print(
                f"  [red]\u2717 {participant_id}/{session_id}[/red]: Error - {e}"
            )

    # Summary
    console.print(f"\n[bold]Validation Summary:[/bold]")
    console.print(f"  Valid:   [green]{results['valid']}[/green]")
    console.print(f"  Invalid: [red]{results['invalid']}[/red]")
    if results["errors"]:
        console.print(f"  Errors:  [yellow]{results['errors']}[/yellow]")

    if failed_sessions:
        console.print(f"\n[bold]Invalid Sessions:[/bold]")
        table = Table()
        table.add_column("Participant", style="cyan")
        table.add_column("Session", style="cyan")
        table.add_column("Reason", style="red")
        for pid, sid, message in failed_sessions:
            table.add_row(pid, sid, message)
        console.print(table)
