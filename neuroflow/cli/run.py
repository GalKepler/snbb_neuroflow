"""Run CLI commands for pipeline execution."""

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _run_pipeline_async(
    ctx: click.Context,
    pipeline_name: str,
    requests: list,
    config,
    config_path: str,
    state,
) -> None:
    """Enqueue pipelines to background queue (non-blocking).

    Args:
        ctx: Click context
        pipeline_name: Name of the pipeline
        requests: List of RunRequest objects
        config: NeuroflowConfig instance
        config_path: Path to config file
        state: SessionState instance
    """
    from neuroflow.tasks import enqueue_pipeline, get_queue_stats

    console.print(
        f"[cyan]Enqueueing '{pipeline_name}' for {len(requests)} session(s) "
        f"to background queue...[/cyan]\n"
    )

    # Get pipeline config for retry settings
    pipeline_config = None
    if pipeline_name == "bids_conversion":
        bids_cfg = config.pipelines.bids_conversion
        retries = bids_cfg.get("retries", 0) if isinstance(bids_cfg, dict) else getattr(bids_cfg, "retries", 0)
    else:
        for p in config.pipelines.session_level + config.pipelines.subject_level:
            if p.name == pipeline_name:
                pipeline_config = p
                break
        retries = pipeline_config.retries if pipeline_config else 0

    # Enqueue all tasks
    log_dir = str(config.paths.log_dir) if config.execution.log_per_session else ""
    task_ids = []

    table = Table(title=f"Enqueued: {pipeline_name}")
    table.add_column("Participant", style="cyan")
    table.add_column("Session", style="cyan")
    table.add_column("Task ID", style="dim")

    for req in requests:
        task_id = enqueue_pipeline(
            config_path=config_path,
            participant_id=req.participant_id,
            session_id=req.session_id,
            dicom_path=req.dicom_path,
            pipeline_name=req.pipeline_name,
            log_dir=log_dir,
            force=req.force,
            retries=retries,
        )
        task_ids.append(task_id)
        # Show shortened task ID (first 8 chars)
        table.add_row(req.participant_id, req.session_id, task_id[:8] + "...")

    console.print(table)

    # Show queue stats
    stats = get_queue_stats()
    console.print(
        f"\n[green]✓[/green] Enqueued {len(task_ids)} task(s) "
        f"(queue: {stats['pending']} pending, {stats['scheduled']} scheduled)\n"
    )

    console.print("[dim]Monitor with:[/dim] neuroflow status runs")
    console.print("[dim]Consumer:[/dim] huey_consumer neuroflow.tasks.huey -w 4 -k process")


def _run_pipeline_sync(
    ctx: click.Context,
    pipeline_name: str,
    requests: list,
    config,
    config_path: str,
    state,
) -> None:
    """Run pipelines synchronously in foreground (blocking).

    Args:
        ctx: Click context
        pipeline_name: Name of the pipeline
        requests: List of RunRequest objects
        config: NeuroflowConfig instance
        config_path: Path to config file
        state: SessionState instance
    """
    from neuroflow.runner import PipelineRunner

    # Execute synchronously (original behavior)
    runner = PipelineRunner(config, config_path)
    console.print(
        f"[cyan]Running '{pipeline_name}' for {len(requests)} session(s) "
        f"synchronously (max_workers={config.execution.max_workers})...[/cyan]\n"
    )

    results = runner.run_batch(requests, dry_run=False)

    # Record results to state
    from datetime import datetime, timezone

    for r in results:
        if r.pipeline_result:
            state.record_pipeline_run(
                participant_id=r.request.participant_id,
                session_id=r.request.session_id,
                pipeline_name=r.request.pipeline_name,
                status="completed" if r.pipeline_result.success else "failed",
                start_time="",
                end_time=datetime.now(timezone.utc).isoformat(),
                duration_seconds=str(r.pipeline_result.duration_seconds or ""),
                exit_code=str(r.pipeline_result.exit_code),
                error_message=r.pipeline_result.error_message or "",
                output_path=str(r.pipeline_result.output_path or ""),
                log_path=r.log_path,
            )
        elif r.error:
            state.record_pipeline_run(
                participant_id=r.request.participant_id,
                session_id=r.request.session_id,
                pipeline_name=r.request.pipeline_name,
                status="failed",
                error_message=r.error,
                log_path=r.log_path,
            )

    # Summary table with per-session results
    succeeded = sum(1 for r in results if r.pipeline_result and r.pipeline_result.success)
    failed = len(results) - succeeded

    table = Table(title=f"Results: {pipeline_name}")
    table.add_column("Participant", style="cyan")
    table.add_column("Session", style="cyan")
    table.add_column("Status")
    table.add_column("Duration")
    table.add_column("Log")

    for r in results:
        if r.pipeline_result and r.pipeline_result.success:
            status_str = "[green]completed[/green]"
            dur = f"{r.pipeline_result.duration_seconds:.1f}s" if r.pipeline_result.duration_seconds else ""
        elif r.pipeline_result:
            status_str = f"[red]failed (exit {r.pipeline_result.exit_code})[/red]"
            dur = f"{r.pipeline_result.duration_seconds:.1f}s" if r.pipeline_result.duration_seconds else ""
        else:
            status_str = f"[red]error[/red]"
            dur = ""

        table.add_row(
            r.request.participant_id,
            r.request.session_id,
            status_str,
            dur,
            r.log_path or "[dim]none[/dim]",
        )

    console.print(table)

    console.print(f"\n  Succeeded: [green]{succeeded}[/green]")
    if failed:
        console.print(f"  Failed:    [red]{failed}[/red]")

        # Show error previews for failures
        console.print(f"\n[bold]Failure details:[/bold]")
        for r in results:
            error_msg = None
            if r.pipeline_result and not r.pipeline_result.success:
                error_msg = r.pipeline_result.error_message
            elif r.error:
                error_msg = r.error

            if error_msg:
                console.print(
                    f"\n  [red]{r.request.participant_id}/{r.request.session_id}:[/red]"
                )
                # Show first 5 lines of error
                lines = error_msg.strip().splitlines()
                for line in lines[:5]:
                    console.print(f"    {line}")
                if len(lines) > 5:
                    console.print(f"    [dim]... ({len(lines) - 5} more lines, see log)[/dim]")
                if r.log_path:
                    console.print(f"    [dim]Full log: {r.log_path}[/dim]")


@click.group()
def run() -> None:
    """Pipeline execution commands."""


@run.command("pipeline")
@click.argument("name")
@click.option("--participant", default=None, help="Run only for specific participant")
@click.option("--max-workers", default=None, type=int, help="Override max workers")
@click.option("--force", is_flag=True, help="Re-run all validated sessions, even if already completed")
@click.option("--sync", is_flag=True, help="Run synchronously (blocking) instead of enqueueing to background queue")
@click.pass_context
def run_pipeline(
    ctx: click.Context,
    name: str,
    participant: str | None,
    max_workers: int | None,
    force: bool = False,
    sync: bool = False,
) -> None:
    """Run a specific pipeline for pending sessions.

    By default, tasks are enqueued to the background queue and executed by the
    Huey consumer. Use --sync to run synchronously in the foreground (useful for
    debugging or one-off runs).

    To start the consumer: huey_consumer neuroflow.tasks.huey -w 4 -k process
    """
    from neuroflow.state import SessionState

    config = ctx.obj["config"]
    config_path = ctx.obj["config_path"]
    dry_run = ctx.obj.get("dry_run", False)
    state = SessionState(config.execution.state_dir)

    if max_workers:
        config.execution.max_workers = max_workers

    # Get sessions for this pipeline
    pending = state.get_pending_sessions(for_pipeline=name, force=force)

    if participant:
        pending = pending[pending["participant_id"] == participant]

    if pending.empty:
        console.print(f"[yellow]No pending sessions for pipeline '{name}'.[/yellow]")
        return

    # Build run requests
    from neuroflow.runner import RunRequest

    requests = []
    for _, row in pending.iterrows():
        requests.append(
            RunRequest(
                participant_id=row["participant_id"],
                session_id=row["session_id"],
                dicom_path=row.get("dicom_path", ""),
                pipeline_name=name,
                force=force,
            )
        )

    if dry_run:
        console.print(f"[cyan]Dry run: would execute {len(requests)} run(s) for '{name}':[/cyan]\n")
        table = Table(title=f"Pipeline: {name}")
        table.add_column("Participant", style="cyan")
        table.add_column("Session", style="cyan")
        table.add_column("DICOM Path")
        for req in requests:
            table.add_row(req.participant_id, req.session_id, req.dicom_path[:60])
        console.print(table)
        return

    # Choose execution mode based on --sync flag
    if sync:
        _run_pipeline_sync(ctx, name, requests, config, config_path, state)
    else:
        _run_pipeline_async(ctx, name, requests, config, config_path, state)



@run.command("all")
@click.option("--participant", default=None, help="Run only for specific participant")
@click.option("--max-workers", default=None, type=int, help="Override max workers")
@click.option("--force", is_flag=True, help="Re-run all validated sessions, even if already completed")
@click.option("--sync", is_flag=True, help="Run synchronously (blocking) instead of enqueueing to background queue")
@click.pass_context
def run_all(
    ctx: click.Context,
    participant: str | None,
    max_workers: int | None,
    force: bool = False,
    sync: bool = False,
) -> None:
    """Run all enabled pipelines in order (bids_conversion -> session -> subject).

    By default, tasks are enqueued to the background queue. Use --sync to run
    synchronously in the foreground.
    """
    config = ctx.obj["config"]

    # Build ordered list of pipeline names
    pipeline_names: list[str] = []

    bids_cfg = config.pipelines.bids_conversion
    if isinstance(bids_cfg, dict):
        if bids_cfg.get("enabled", True):
            pipeline_names.append("bids_conversion")
    elif bids_cfg.enabled:
        pipeline_names.append("bids_conversion")

    for p in config.pipelines.session_level:
        if p.enabled:
            pipeline_names.append(p.name)

    for p in config.pipelines.subject_level:
        if p.enabled:
            pipeline_names.append(p.name)

    if not pipeline_names:
        console.print("[yellow]No enabled pipelines found.[/yellow]")
        return

    console.print(f"[cyan]Running pipelines in order: {', '.join(pipeline_names)}[/cyan]\n")

    for name in pipeline_names:
        console.print(f"\n[bold]--- {name} ---[/bold]")
        ctx.invoke(
            run_pipeline,
            name=name,
            participant=participant,
            max_workers=max_workers,
            force=force,
            sync=sync,
        )
