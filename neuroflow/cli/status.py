"""Status CLI commands."""

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.command("status")
@click.option("--sessions", is_flag=True, help="Show session details")
@click.option("--subjects", is_flag=True, help="Show subject details")
@click.option("--failed", is_flag=True, help="Show only failed")
@click.option("--status-filter", "status_filter", default=None, help="Filter by status")
@click.option("--subject", "subject_filter", default=None, help="Filter by subject")
@click.option("--format", "output_format", default="table", help="Output format: table, json, csv")
@click.pass_context
def status(
    ctx: click.Context,
    sessions: bool,
    subjects: bool,
    failed: bool,
    status_filter: str | None,
    subject_filter: str | None,
    output_format: str,
) -> None:
    """Show system status."""
    from sqlalchemy import func, select

    from neuroflow.core.state import StateManager
    from neuroflow.models import (
        PipelineRun,
        PipelineRunStatus,
        Session,
        SessionStatus,
        Subject,
    )

    config = ctx.obj["config"]
    state = StateManager(config)

    if sessions:
        _show_sessions(state, failed, status_filter, subject_filter)
    elif subjects:
        _show_subjects(state, failed)
    else:
        _show_summary(state)


def _show_summary(state: "StateManager") -> None:
    """Show overall system summary."""
    from sqlalchemy import func, select

    from neuroflow.models import (
        PipelineRun,
        PipelineRunStatus,
        Session,
        SessionStatus,
        Subject,
    )

    with state.get_session() as db:
        subject_count = db.execute(select(func.count(Subject.id))).scalar() or 0
        session_count = db.execute(select(func.count(Session.id))).scalar() or 0

        session_stats = {}
        for s in SessionStatus:
            count = db.execute(
                select(func.count(Session.id)).where(Session.status == s)
            ).scalar()
            if count and count > 0:
                session_stats[s.value] = count

        run_stats = {}
        for s in PipelineRunStatus:
            count = db.execute(
                select(func.count(PipelineRun.id)).where(PipelineRun.status == s)
            ).scalar()
            if count and count > 0:
                run_stats[s.value] = count

    console.print("\n[bold]Neuroflow Status[/bold]\n")
    console.print(f"Subjects: {subject_count}")
    console.print(f"Sessions: {session_count}\n")

    if session_stats:
        table = Table(title="Sessions by Status")
        table.add_column("Status")
        table.add_column("Count", justify="right")
        for s, count in session_stats.items():
            style = {
                "completed": "green",
                "failed": "red",
                "processing": "yellow",
                "invalid": "red",
            }.get(s, "white")
            table.add_row(f"[{style}]{s}[/]", str(count))
        console.print(table)

    if run_stats:
        table = Table(title="Pipeline Runs by Status")
        table.add_column("Status")
        table.add_column("Count", justify="right")
        for s, count in run_stats.items():
            style = {
                "completed": "green",
                "failed": "red",
                "running": "yellow",
            }.get(s, "white")
            table.add_row(f"[{style}]{s}[/]", str(count))
        console.print(table)

    if not session_stats and not run_stats:
        console.print("[dim]No data yet. Run 'neuroflow scan now' to discover sessions.[/dim]")


def _show_sessions(
    state: "StateManager",
    failed: bool,
    status_filter: str | None,
    subject_filter: str | None,
) -> None:
    """Show session details."""
    from sqlalchemy import select

    from neuroflow.models import Session, SessionStatus, Subject

    with state.get_session() as db:
        query = select(Session).join(Subject)

        if failed:
            query = query.where(Session.status == SessionStatus.FAILED)
        elif status_filter:
            query = query.where(Session.status == status_filter)

        if subject_filter:
            query = query.where(Subject.participant_id == subject_filter)

        query = query.order_by(Session.discovered_at.desc())
        sessions_list = db.execute(query).scalars().all()

    if not sessions_list:
        console.print("[yellow]No sessions found matching filters.[/yellow]")
        return

    title = "Sessions"
    if failed:
        title += " (failed)"
    elif status_filter:
        title += f" (status={status_filter})"

    table = Table(title=title)
    table.add_column("Subject", style="cyan")
    table.add_column("Session", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Discovered")
    table.add_column("Pipelines (C/F/P)", justify="center")

    for s in sessions_list:
        status_style = {
            "completed": "green",
            "failed": "red",
            "processing": "yellow",
            "invalid": "red",
        }.get(s.status.value, "white")

        table.add_row(
            s.subject.participant_id,
            s.session_id,
            f"[{status_style}]{s.status.value}[/]",
            s.discovered_at.strftime("%Y-%m-%d %H:%M") if s.discovered_at else "-",
            f"{s.pipelines_completed}/{s.pipelines_failed}/{s.pipelines_pending}",
        )

    console.print(table)
    console.print(f"\n{len(sessions_list)} sessions shown.")


def _show_subjects(state: "StateManager", failed: bool) -> None:
    """Show subject details."""
    from sqlalchemy import select

    from neuroflow.models import Subject, SubjectStatus

    with state.get_session() as db:
        query = select(Subject)
        if failed:
            query = query.where(Subject.status == SubjectStatus.FAILED)
        query = query.order_by(Subject.updated_at.desc())
        subjects_list = db.execute(query).scalars().all()

    if not subjects_list:
        console.print("[yellow]No subjects found.[/yellow]")
        return

    table = Table(title="Subjects")
    table.add_column("Participant ID", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Sessions", justify="right")
    table.add_column("Completed", justify="right")
    table.add_column("Failed", justify="right")

    for s in subjects_list:
        status_style = {
            "completed": "green",
            "failed": "red",
            "processing": "yellow",
        }.get(s.status.value, "white")

        table.add_row(
            s.participant_id,
            f"[{status_style}]{s.status.value}[/]",
            str(s.session_count),
            str(s.completed_pipelines),
            str(s.failed_pipelines),
        )

    console.print(table)
