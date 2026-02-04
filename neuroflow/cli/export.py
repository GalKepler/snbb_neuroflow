"""Export CLI commands."""

import csv
import json
import sys
from io import StringIO

import click
from rich.console import Console

console = Console()


@click.group()
def export() -> None:
    """Export data commands."""


@export.command("sessions")
@click.option("--output", "-o", default=None, help="Output file (default: stdout)")
@click.option("--format", "fmt", default="csv", help="Format: csv or json")
@click.option("--verbose", is_flag=True, help="Include all fields")
@click.pass_context
def export_sessions(ctx: click.Context, output: str | None, fmt: str, verbose: bool) -> None:
    """Export session data."""
    from sqlalchemy import select

    from neuroflow.core.state import StateManager
    from neuroflow.models import Session, Subject

    config = ctx.obj["config"]
    state = StateManager(config)

    with state.get_session() as db:
        sessions = db.execute(
            select(Session).join(Subject).order_by(Session.discovered_at)
        ).scalars().all()

        rows = []
        for s in sessions:
            row = {
                "participant_id": s.subject.participant_id,
                "session_id": s.session_id,
                "status": s.status.value,
                "discovered_at": str(s.discovered_at) if s.discovered_at else "",
                "dicom_path": s.dicom_path or "",
                "pipelines_completed": s.pipelines_completed,
                "pipelines_failed": s.pipelines_failed,
                "pipelines_pending": s.pipelines_pending,
            }
            if verbose:
                row.update({
                    "is_valid": str(s.is_valid) if s.is_valid is not None else "",
                    "validation_message": s.validation_message or "",
                    "bids_path": s.bids_path or "",
                    "acquisition_date": str(s.acquisition_date) if s.acquisition_date else "",
                })
            rows.append(row)

    _write_output(rows, output, fmt)
    if output:
        console.print(f"[green]Exported {len(rows)} sessions to {output}[/green]")


@export.command("failures")
@click.option("--output", "-o", default=None, help="Output file")
@click.option("--format", "fmt", default="csv", help="Format: csv or json")
@click.pass_context
def export_failures(ctx: click.Context, output: str | None, fmt: str) -> None:
    """Export failure report."""
    from sqlalchemy import select

    from neuroflow.core.state import StateManager
    from neuroflow.models import PipelineRun, PipelineRunStatus, Session, Subject

    config = ctx.obj["config"]
    state = StateManager(config)

    with state.get_session() as db:
        runs = (
            db.execute(
                select(PipelineRun)
                .where(PipelineRun.status == PipelineRunStatus.FAILED)
                .order_by(PipelineRun.completed_at.desc())
            )
            .scalars()
            .all()
        )

        rows = []
        for r in runs:
            subject = db.get(Subject, r.subject_id) if r.subject_id else None
            session = db.get(Session, r.session_id) if r.session_id else None
            rows.append({
                "run_id": r.id,
                "participant_id": subject.participant_id if subject else "",
                "session_id": session.session_id if session else "",
                "pipeline": r.pipeline_name,
                "attempt": r.attempt_number,
                "error_message": r.error_message or "",
                "completed_at": str(r.completed_at) if r.completed_at else "",
            })

    _write_output(rows, output, fmt)
    if output:
        console.print(f"[green]Exported {len(rows)} failures to {output}[/green]")


@export.command("audit")
@click.option("--output", "-o", default=None, help="Output file")
@click.option("--format", "fmt", default="csv", help="Format: csv or json")
@click.option("--since", default=None, help="Filter by date")
@click.pass_context
def export_audit(ctx: click.Context, output: str | None, fmt: str, since: str | None) -> None:
    """Export audit log."""
    from sqlalchemy import select

    from neuroflow.core.state import StateManager
    from neuroflow.models import AuditLog

    config = ctx.obj["config"]
    state = StateManager(config)

    with state.get_session() as db:
        query = select(AuditLog).order_by(AuditLog.timestamp)

        if since:
            from dateutil.parser import parse

            since_dt = parse(since)
            query = query.where(AuditLog.timestamp >= since_dt)

        entries = db.execute(query).scalars().all()

        rows = []
        for e in entries:
            rows.append({
                "timestamp": str(e.timestamp),
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "action": e.action,
                "old_value": e.old_value or "",
                "new_value": e.new_value or "",
                "triggered_by": e.triggered_by or "",
                "message": e.message or "",
            })

    _write_output(rows, output, fmt)
    if output:
        console.print(f"[green]Exported {len(rows)} audit entries to {output}[/green]")


def _write_output(rows: list[dict], output: str | None, fmt: str) -> None:
    """Write data to file or stdout."""
    if fmt == "json":
        content = json.dumps(rows, indent=2, default=str)
    else:
        if not rows:
            return
        buf = StringIO()
        writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        content = buf.getvalue()

    if output:
        with open(output, "w") as f:
            f.write(content)
    else:
        console.print(content)
