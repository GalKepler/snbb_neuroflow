"""Discovery CLI commands."""

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def scan() -> None:
    """Discovery commands."""


@scan.command("list")
@click.option(
    "--status",
    type=click.Choice(
        ["discovered", "validating", "validated", "invalid", "converting", "converted", "processing", "completed", "failed"],
        case_sensitive=False,
    ),
    help="Filter by session status",
)
@click.option("--subject", help="Filter by subject ID")
@click.pass_context
def scan_list(ctx: click.Context, status: str | None, subject: str | None) -> None:
    """List discovered sessions in the database."""
    from neuroflow.core.state import StateManager
    from neuroflow.models.session import Session, SessionStatus

    config = ctx.obj["config"]
    state = StateManager(config)

    with state.get_session() as db:
        query = db.query(Session)

        # Apply filters
        if status:
            status_enum = SessionStatus(status.lower())
            query = query.filter(Session.status == status_enum)

        if subject:
            query = query.join(Session.subject).filter_by(participant_id=subject)

        sessions = query.order_by(Session.created_at.desc()).all()

        if not sessions:
            console.print("[yellow]No sessions found.[/yellow]")
            return

        # Create table
        table = Table(title=f"Sessions ({len(sessions)} total)")
        table.add_column("ID", style="dim")
        table.add_column("Subject", style="cyan")
        table.add_column("Session", style="cyan")
        table.add_column("Status", style="magenta")
        table.add_column("Valid", justify="center")
        table.add_column("Scans", justify="right")
        table.add_column("Discovered", style="dim")

        for s in sessions:
            # Format status with color
            status_str = s.status.value
            if s.status == SessionStatus.VALIDATED:
                status_str = f"[green]{status_str}[/green]"
            elif s.status == SessionStatus.INVALID:
                status_str = f"[red]{status_str}[/red]"
            elif s.status == SessionStatus.FAILED:
                status_str = f"[red]{status_str}[/red]"
            elif s.status == SessionStatus.COMPLETED:
                status_str = f"[green]{status_str}[/green]"

            # Format valid column
            valid_str = ""
            if s.is_valid is not None:
                valid_str = "[green]✓[/green]" if s.is_valid else "[red]✗[/red]"

            # Format scans count
            scans_count = ""
            if s.scans_found:
                scans_count = str(sum(s.scans_found.values()))

            table.add_row(
                str(s.id),
                s.subject.participant_id,
                s.session_id,
                status_str,
                valid_str,
                scans_count,
                s.discovered_at.strftime("%Y-%m-%d %H:%M") if s.discovered_at else "",
            )

        console.print(table)

        # Show summary by status
        from collections import Counter

        status_counts = Counter(s.status.value for s in sessions)
        console.print(f"\n[bold]Status Summary:[/bold]")
        for status_name, count in status_counts.most_common():
            console.print(f"  {status_name}: {count}")


@scan.command("now")
@click.option("--dry-run", is_flag=True, help="Show what would be found without registering")
@click.option("--path", default=None, help="Override scan path")
@click.pass_context
def scan_now(ctx: click.Context, dry_run: bool, path: str | None) -> None:
    """Scan for new DICOM sessions."""
    from neuroflow.discovery.scanner import SessionScanner

    config = ctx.obj["config"]
    scanner = SessionScanner(config)

    with console.status("Scanning directories..."):
        results = scanner.scan_all()

    if not results:
        console.print("[yellow]No new sessions found.[/yellow]")
        return

    table = Table(title=f"Found {len(results)} Sessions")
    table.add_column("Subject", style="cyan")
    table.add_column("Session", style="cyan")
    table.add_column("Recruitment ID", style="magenta")
    table.add_column("Scans", justify="right")
    table.add_column("Path")

    for r in results:
        table.add_row(
            r.subject_id,
            r.session_id,
            r.recruitment_id or "",
            str(len(r.scans)),
            str(r.session_path)[:60],
        )

    console.print(table)

    if not dry_run:
        console.print(
            f"\n[green]{len(results)} sessions registered and queued for processing.[/green]"
        )


@scan.command("validate")
@click.argument("path", required=False)
@click.option("--all", "validate_all", is_flag=True, help="Validate all discovered sessions")
@click.option(
    "--status",
    type=click.Choice(["discovered", "validating", "validated", "invalid"], case_sensitive=False),
    help="Filter sessions by status (use with --all)",
)
@click.pass_context
def scan_validate(
    ctx: click.Context,
    path: str | None,
    validate_all: bool,
    status: str | None,
) -> None:
    """Validate DICOM sessions.

    Examples:
        neuroflow scan validate /path/to/session  # Validate specific path
        neuroflow scan validate --all             # Validate all sessions
        neuroflow scan validate --all --status discovered  # Validate only discovered sessions
    """
    from pathlib import Path

    from neuroflow.core.state import StateManager
    from neuroflow.discovery.scanner import SessionScanner
    from neuroflow.discovery.validator import SessionValidator
    from neuroflow.models.session import Session, SessionStatus

    config = ctx.obj["config"]
    scanner = SessionScanner(config)
    validator = SessionValidator(config)

    # Validate all sessions from database
    if validate_all:
        state = StateManager(config)
        with state.get_session() as db:
            query = db.query(Session)

            # Filter by status if specified
            if status:
                status_enum = SessionStatus(status.lower())
                query = query.filter(Session.status == status_enum)

            sessions = query.all()

            if not sessions:
                filter_msg = f" with status '{status}'" if status else ""
                console.print(f"[yellow]No sessions found{filter_msg}.[/yellow]")
                return

            console.print(f"[cyan]Validating {len(sessions)} sessions...[/cyan]\n")

            results = {"valid": 0, "invalid": 0, "errors": 0}
            failed_sessions = []

            for session in sessions:
                session_path = Path(session.dicom_path)

                try:
                    with console.status(
                        f"Validating {session.subject.participant_id}/{session.session_id}..."
                    ):
                        # Scan the session directory
                        scans = scanner._identify_scans(session_path)
                        result = validator.validate(scans)

                        # Update session in database
                        session.is_valid = result.is_valid
                        session.validation_message = result.message
                        session.scans_found = result.scans_found
                        session.status = (
                            SessionStatus.VALIDATED if result.is_valid else SessionStatus.INVALID
                        )
                        db.commit()

                        if result.is_valid:
                            results["valid"] += 1
                            console.print(
                                f"  ✓ [green]{session.subject.participant_id}/{session.session_id}[/green]"
                            )
                        else:
                            results["invalid"] += 1
                            failed_sessions.append(
                                (session.subject.participant_id, session.session_id, result.message)
                            )
                            console.print(
                                f"  ✗ [red]{session.subject.participant_id}/{session.session_id}[/red]: {result.message}"
                            )

                except Exception as e:
                    results["errors"] += 1
                    console.print(
                        f"  ✗ [red]{session.subject.participant_id}/{session.session_id}[/red]: Error - {str(e)}"
                    )

            # Summary
            console.print(f"\n[bold]Validation Summary:[/bold]")
            console.print(f"  Valid:   [green]{results['valid']}[/green]")
            console.print(f"  Invalid: [red]{results['invalid']}[/red]")
            if results["errors"]:
                console.print(f"  Errors:  [yellow]{results['errors']}[/yellow]")

            # Show failed sessions table if any
            if failed_sessions:
                console.print(f"\n[bold]Invalid Sessions:[/bold]")
                table = Table()
                table.add_column("Subject", style="cyan")
                table.add_column("Session", style="cyan")
                table.add_column("Reason", style="red")
                for subject_id, session_id, message in failed_sessions:
                    table.add_row(subject_id, session_id, message)
                console.print(table)

        return

    # Validate specific path
    if not path:
        console.print("[red]Error: Must specify PATH or use --all flag[/red]")
        console.print("\nUsage:")
        console.print("  neuroflow scan validate /path/to/session")
        console.print("  neuroflow scan validate --all")
        console.print("  neuroflow scan validate --all --status discovered")
        raise SystemExit(1)

    session_path = Path(path)
    if not session_path.exists():
        console.print(f"[red]Path not found: {path}[/red]")
        raise SystemExit(1)

    with console.status("Scanning session..."):
        scans = scanner._identify_scans(session_path)

    result = validator.validate(scans)

    if result.is_valid:
        console.print(f"[green]✓ Session is valid: {result.message}[/green]")
    else:
        console.print(f"[red]✗ Session is invalid: {result.message}[/red]")

    if result.scans_found:
        table = Table(title="Scans Found")
        table.add_column("Scan Type")
        table.add_column("Files", justify="right")
        for name, count in result.scans_found.items():
            table.add_row(name, str(count))
        console.print(table)
