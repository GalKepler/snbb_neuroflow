"""Discovery CLI commands."""

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def scan() -> None:
    """Discovery commands."""


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
@click.argument("path")
@click.pass_context
def scan_validate(ctx: click.Context, path: str) -> None:
    """Validate a specific DICOM session directory."""
    from pathlib import Path

    from neuroflow.discovery.scanner import SessionScanner
    from neuroflow.discovery.validator import SessionValidator

    config = ctx.obj["config"]
    scanner = SessionScanner(config)
    validator = SessionValidator(config)

    session_path = Path(path)
    if not session_path.exists():
        console.print(f"[red]Path not found: {path}[/red]")
        raise SystemExit(1)

    with console.status("Scanning session..."):
        scans = scanner._identify_scans(session_path)

    result = validator.validate(scans)

    if result.is_valid:
        console.print(f"[green]Session is valid: {result.message}[/green]")
    else:
        console.print(f"[red]Session is invalid: {result.message}[/red]")

    if result.scans_found:
        table = Table(title="Scans Found")
        table.add_column("Scan Type")
        table.add_column("Files", justify="right")
        for name, count in result.scans_found.items():
            table.add_row(name, str(count))
        console.print(table)
