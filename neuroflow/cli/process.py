"""Processing CLI commands."""

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def process() -> None:
    """Processing commands."""


@process.command("session")
@click.argument("subject_id")
@click.argument("session_id")
@click.option("--pipeline", default=None, help="Run specific pipeline only")
@click.option("--force", is_flag=True, help="Force reprocessing even if completed")
@click.pass_context
def process_session(
    ctx: click.Context,
    subject_id: str,
    session_id: str,
    pipeline: str | None,
    force: bool,
) -> None:
    """Process a specific session through pipelines."""
    from neuroflow.core.state import StateManager
    from neuroflow.orchestrator.workflow import WorkflowManager

    config = ctx.obj["config"]
    state = StateManager(config)
    workflow = WorkflowManager(config, state)

    session = state.get_session_by_ids(subject_id, session_id)
    if not session:
        console.print(f"[red]Session not found: {subject_id}/{session_id}[/red]")
        raise SystemExit(1)

    run_ids = workflow.process_session(session.id, force=force, pipeline_filter=pipeline)

    if run_ids:
        console.print(
            f"[green]Queued {len(run_ids)} pipeline(s) for {subject_id}/{session_id}[/green]"
        )
    else:
        console.print("[yellow]No pipelines to run for this session.[/yellow]")


@process.command("subject")
@click.argument("subject_id")
@click.option("--force", is_flag=True, help="Force reprocessing")
@click.pass_context
def process_subject(ctx: click.Context, subject_id: str, force: bool) -> None:
    """Process all sessions for a subject."""
    from sqlalchemy import select

    from neuroflow.core.state import StateManager
    from neuroflow.models import Session, Subject
    from neuroflow.orchestrator.workflow import WorkflowManager

    config = ctx.obj["config"]
    state = StateManager(config)
    workflow = WorkflowManager(config, state)

    total_runs = 0
    with state.get_session() as db:
        subject = db.execute(
            select(Subject).where(Subject.participant_id == subject_id)
        ).scalar_one_or_none()

        if not subject:
            console.print(f"[red]Subject not found: {subject_id}[/red]")
            raise SystemExit(1)

        sessions = db.execute(
            select(Session).where(Session.subject_id == subject.id)
        ).scalars().all()

        session_ids = [s.id for s in sessions]

    for sid in session_ids:
        run_ids = workflow.process_session(sid, force=force)
        total_runs += len(run_ids)

    console.print(
        f"[green]Queued {total_runs} pipeline(s) across {len(session_ids)} session(s)[/green]"
    )


@process.command("pending")
@click.option("--max-tasks", default=None, type=int, help="Limit concurrent tasks")
@click.pass_context
def process_pending(ctx: click.Context, max_tasks: int | None) -> None:
    """Process all pending work."""
    from sqlalchemy import select

    from neuroflow.core.state import StateManager
    from neuroflow.models import Session, SessionStatus
    from neuroflow.orchestrator.workflow import WorkflowManager

    config = ctx.obj["config"]
    state = StateManager(config)
    workflow = WorkflowManager(config, state)

    with state.get_session() as db:
        pending = (
            db.execute(
                select(Session).where(
                    Session.status.in_([
                        SessionStatus.VALIDATED,
                        SessionStatus.CONVERTED,
                    ])
                )
            )
            .scalars()
            .all()
        )
        session_ids = [s.id for s in pending]

    total_runs = 0
    for i, sid in enumerate(session_ids):
        if max_tasks and total_runs >= max_tasks:
            break
        run_ids = workflow.process_session(sid)
        total_runs += len(run_ids)

    console.print(
        f"[green]Queued {total_runs} pipeline(s) for {len(session_ids)} session(s)[/green]"
    )


@process.command("retry")
@click.option("--all", "retry_all", is_flag=True, help="Retry all failed runs")
@click.option("--session", "session_filter", default=None, help="Retry for specific session (sub-X/ses-Y)")
@click.option("--pipeline", default=None, help="Retry specific pipeline")
@click.option("--run-id", default=None, type=int, help="Retry specific run")
@click.pass_context
def process_retry(
    ctx: click.Context,
    retry_all: bool,
    session_filter: str | None,
    pipeline: str | None,
    run_id: int | None,
) -> None:
    """Retry failed pipeline runs."""
    from sqlalchemy import select

    from neuroflow.core.state import StateManager
    from neuroflow.models import PipelineRun, PipelineRunStatus
    from neuroflow.orchestrator.workflow import WorkflowManager

    config = ctx.obj["config"]
    state = StateManager(config)
    workflow = WorkflowManager(config, state)

    with state.get_session() as db:
        query = select(PipelineRun).where(
            PipelineRun.status == PipelineRunStatus.FAILED
        )

        if run_id:
            query = query.where(PipelineRun.id == run_id)
        if pipeline:
            query = query.where(PipelineRun.pipeline_name == pipeline)

        failed_runs = db.execute(query).scalars().all()
        run_data = [
            {
                "session_id": r.session_id,
                "subject_id": r.subject_id,
                "pipeline_name": r.pipeline_name,
                "pipeline_level": r.pipeline_level,
            }
            for r in failed_runs
        ]

    if not run_data:
        console.print("[yellow]No failed runs to retry.[/yellow]")
        return

    retried = 0
    for rd in run_data:
        state.create_pipeline_run(
            pipeline_name=rd["pipeline_name"],
            pipeline_level=rd["pipeline_level"],
            session_id=rd["session_id"],
            subject_id=rd["subject_id"],
            trigger_reason="retry",
        )
        retried += 1

    console.print(f"[green]Retried {retried} pipeline run(s).[/green]")
