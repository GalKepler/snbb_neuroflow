"""Run CLI commands for pipeline execution."""

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def run() -> None:
    """Pipeline execution commands."""


@run.command("pipeline")
@click.argument("name")
@click.option("--participant", default=None, help="Run only for specific participant")
@click.option("--max-workers", default=None, type=int, help="Override max workers")
@click.option("--force", is_flag=True, help="Re-run all validated sessions, even if already completed")
@click.pass_context
def run_pipeline(
    ctx: click.Context,
    name: str,
    participant: str | None,
    max_workers: int | None,
    force: bool = False,
) -> None:
    """Run a specific pipeline for pending sessions."""
    from neuroflow.runner import PipelineRunner, RunRequest
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

    # Execute
    runner = PipelineRunner(config, config_path)
    console.print(
        f"[cyan]Running '{name}' for {len(requests)} session(s) "
        f"(max_workers={config.execution.max_workers})...[/cyan]\n"
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

    table = Table(title=f"Results: {name}")
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


@run.command("all")
@click.option("--participant", default=None, help="Run only for specific participant")
@click.option("--max-workers", default=None, type=int, help="Override max workers")
@click.option("--force", is_flag=True, help="Re-run all validated sessions, even if already completed")
@click.pass_context
def run_all(
    ctx: click.Context,
    participant: str | None,
    max_workers: int | None,
    force: bool = False,
) -> None:
    """Run all enabled pipelines in order (bids_conversion -> session -> subject)."""
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
        )
