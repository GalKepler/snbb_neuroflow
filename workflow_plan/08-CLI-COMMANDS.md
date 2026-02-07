# CLI Commands Implementation

## Overview

This document describes the complete CLI implementation for workflow management, including the `neuroflow workflow` command group.

## Main CLI Structure

```
neuroflow
├── workflow           # Workflow management
│   ├── run           # Run the workflow
│   ├── status        # Show current status
│   ├── list          # List workflow runs
│   └── cancel        # Cancel a workflow
├── session           # Session management
│   ├── list          # List sessions
│   ├── show          # Show session details
│   ├── rerun         # Mark for rerun
│   └── exclude       # Exclude from processing
├── subject           # Subject management
│   ├── list          # List subjects
│   └── show          # Show subject details
├── pipeline          # Pipeline management
│   ├── list          # List pipeline runs
│   ├── show          # Show run details
│   └── cancel        # Cancel a run
├── logs              # Log viewing
│   ├── show          # Show logs
│   ├── pipeline      # Pipeline logs
│   ├── audit         # Audit logs
│   └── workflow      # Workflow logs
├── recovery          # Error recovery
│   ├── list          # List failed runs
│   ├── retry         # Retry a failed run
│   └── resolve       # Resolve without retry
└── run               # Service management
    ├── worker        # Run Celery worker
    └── beat          # Run Celery beat
```

## Workflow CLI Implementation

### File: `neuroflow/cli/workflow.py`

```python
"""Workflow management CLI commands."""

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


@click.group()
def workflow() -> None:
    """Workflow management commands."""


@workflow.command("run")
@click.option("--stage", default=None, help="Run specific stage only")
@click.option("--sync", is_flag=True, help="Wait for completion")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.option("--force", is_flag=True, help="Force run even if recently completed")
@click.pass_context
def run_workflow(
    ctx: click.Context,
    stage: str | None,
    sync: bool,
    dry_run: bool,
    force: bool,
) -> None:
    """Run the complete workflow or a specific stage.
    
    Examples:
    
        # Run complete workflow
        neuroflow workflow run
        
        # Run specific stage
        neuroflow workflow run --stage bids_conversion
        
        # Dry run to see what would happen
        neuroflow workflow run --dry-run
        
        # Wait for completion
        neuroflow workflow run --sync
    """
    from neuroflow.config import NeuroflowConfig
    from neuroflow.orchestrator.scheduler import WorkflowScheduler, WorkflowStage
    
    config = ctx.obj["config"]
    scheduler = WorkflowScheduler(config)
    
    # Parse stage if provided
    force_stage = None
    if stage:
        try:
            force_stage = WorkflowStage(stage)
        except ValueError:
            valid_stages = [s.value for s in WorkflowStage]
            console.print(f"[red]Invalid stage '{stage}'. Valid stages: {valid_stages}[/red]")
            raise click.Abort()
    
    if dry_run:
        console.print("[yellow]Dry run - showing what would be executed:[/yellow]\n")
    
    if sync:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Running workflow...", total=None)
            
            result = scheduler.run_workflow(
                sync=True,
                force_stage=force_stage,
                dry_run=dry_run,
            )
            
            progress.update(task, completed=True)
    else:
        result = scheduler.run_workflow(
            sync=False,
            force_stage=force_stage,
            dry_run=dry_run,
        )
    
    # Display results
    status_color = {
        "completed": "green",
        "running": "blue",
        "failed": "red",
        "pending": "yellow",
    }.get(result.status.value, "white")
    
    console.print(Panel(
        f"Workflow Run ID: [bold]{result.workflow_run_id}[/bold]\n"
        f"Status: [{status_color}]{result.status.value}[/{status_color}]\n"
        f"Stages completed: {len(result.stages_completed)}",
        title="Workflow Result",
    ))
    
    if result.error_message:
        console.print(f"\n[red]Error: {result.error_message}[/red]")
    
    if dry_run:
        console.print("\n[bold]Would process:[/bold]")
        for stage_result in result.stage_results:
            console.print(f"  {stage_result.stage.value}: {stage_result.tasks_queued} tasks")


@workflow.command("status")
@click.option("--workflow-id", default=None, type=int, help="Specific workflow run ID")
@click.pass_context
def workflow_status(ctx: click.Context, workflow_id: int | None) -> None:
    """Show current workflow status.
    
    Shows the status of the most recent or specified workflow run,
    including progress through stages and any errors.
    """
    from neuroflow.config import NeuroflowConfig
    from neuroflow.core.state import StateManager
    
    config = ctx.obj["config"]
    state = StateManager(config)
    
    if workflow_id:
        run = state.get_workflow_run(workflow_id)
    else:
        run = state.get_latest_workflow_run()
    
    if not run:
        console.print("[yellow]No workflow runs found[/yellow]")
        return
    
    # Status color
    status_color = {
        "completed": "green",
        "running": "blue",
        "failed": "red",
        "pending": "yellow",
        "cancelled": "dim",
    }.get(run.status.value, "white")
    
    # Build status panel
    duration = ""
    if run.duration_seconds:
        hours, remainder = divmod(int(run.duration_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        duration = f"{hours}h {minutes}m {seconds}s"
    elif run.started_at:
        from datetime import datetime, timezone
        elapsed = (datetime.now(timezone.utc) - run.started_at).total_seconds()
        hours, remainder = divmod(int(elapsed), 3600)
        minutes, seconds = divmod(remainder, 60)
        duration = f"{hours}h {minutes}m {seconds}s (running)"
    
    panel_content = f"""
[bold]Workflow Run #{run.id}[/bold]

Status: [{status_color}]{run.status.value}[/{status_color}]
Trigger: {run.trigger_type}
Started: {run.started_at.strftime('%Y-%m-%d %H:%M:%S') if run.started_at else 'N/A'}
Duration: {duration or 'N/A'}

[bold]Current Stage:[/bold] {run.current_stage or 'None'}
[bold]Completed Stages:[/bold] {', '.join(run.stages_completed) or 'None'}

[bold]Metrics:[/bold]
  Sessions discovered: {run.sessions_discovered}
  Sessions converted: {run.sessions_converted}
  Subjects preprocessed: {run.subjects_preprocessed}
  Sessions reconstructed: {run.sessions_reconstructed}
  Sessions parcellated: {run.sessions_parcellated}
"""
    
    if run.error_message:
        panel_content += f"\n[red]Error: {run.error_message}[/red]"
        if run.error_stage:
            panel_content += f"\n[red]Error Stage: {run.error_stage}[/red]"
    
    console.print(Panel(panel_content.strip(), title="Workflow Status"))


@workflow.command("list")
@click.option("--limit", default=10, type=int, help="Number of runs to show")
@click.option("--status", default=None, help="Filter by status")
@click.pass_context
def list_workflows(ctx: click.Context, limit: int, status: str | None) -> None:
    """List recent workflow runs.
    
    Examples:
    
        # List recent runs
        neuroflow workflow list
        
        # List failed runs
        neuroflow workflow list --status failed
        
        # Show more history
        neuroflow workflow list --limit 50
    """
    from neuroflow.config import NeuroflowConfig
    from neuroflow.core.state import StateManager
    from neuroflow.models import WorkflowRunStatus
    
    config = ctx.obj["config"]
    state = StateManager(config)
    
    status_filter = None
    if status:
        try:
            status_filter = WorkflowRunStatus(status)
        except ValueError:
            valid = [s.value for s in WorkflowRunStatus]
            console.print(f"[red]Invalid status '{status}'. Valid: {valid}[/red]")
            raise click.Abort()
    
    runs = state.get_workflow_run_history(limit=limit, status=status_filter)
    
    if not runs:
        console.print("[yellow]No workflow runs found[/yellow]")
        return
    
    table = Table(title="Workflow Runs")
    table.add_column("ID", style="bold")
    table.add_column("Status")
    table.add_column("Trigger")
    table.add_column("Started")
    table.add_column("Duration")
    table.add_column("Stages")
    table.add_column("Pipelines")
    
    for run in runs:
        # Format duration
        duration = "-"
        if run.duration_seconds:
            hours, remainder = divmod(int(run.duration_seconds), 3600)
            minutes, _ = divmod(remainder, 60)
            duration = f"{hours}h {minutes}m"
        
        # Status color
        status_color = {
            "completed": "green",
            "running": "blue",
            "failed": "red",
            "pending": "yellow",
            "cancelled": "dim",
        }.get(run.status.value, "white")
        
        # Pipeline counts
        pipelines = f"{run.sessions_discovered}/{run.sessions_converted}/{run.subjects_preprocessed}"
        
        table.add_row(
            str(run.id),
            f"[{status_color}]{run.status.value}[/{status_color}]",
            run.trigger_type,
            run.started_at.strftime("%Y-%m-%d %H:%M") if run.started_at else "-",
            duration,
            str(len(run.stages_completed)),
            pipelines,
        )
    
    console.print(table)
    console.print("[dim]Pipelines: discovered/converted/preprocessed[/dim]")


@workflow.command("cancel")
@click.argument("workflow_id", type=int)
@click.option("--force", is_flag=True, help="Force cancel even if running")
@click.pass_context
def cancel_workflow(ctx: click.Context, workflow_id: int, force: bool) -> None:
    """Cancel a running workflow.
    
    This will:
    - Mark the workflow as cancelled
    - Stop any pending tasks from starting
    - Currently running tasks will complete
    """
    from neuroflow.config import NeuroflowConfig
    from neuroflow.core.state import StateManager
    from neuroflow.models import WorkflowRunStatus
    
    config = ctx.obj["config"]
    state = StateManager(config)
    
    run = state.get_workflow_run(workflow_id)
    if not run:
        console.print(f"[red]Workflow run {workflow_id} not found[/red]")
        raise click.Abort()
    
    if run.status != WorkflowRunStatus.RUNNING and not force:
        console.print(f"[yellow]Workflow {workflow_id} is not running (status: {run.status.value})[/yellow]")
        console.print("Use --force to cancel anyway")
        return
    
    state.update_workflow_run(
        workflow_id,
        status=WorkflowRunStatus.CANCELLED,
        error_message="Cancelled by user",
    )
    
    console.print(f"[green]Workflow {workflow_id} cancelled[/green]")
```

## Session CLI Implementation

### File: `neuroflow/cli/session.py`

```python
"""Session management CLI commands."""

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def session() -> None:
    """Session management commands."""


@session.command("list")
@click.option("--status", default=None, help="Filter by status")
@click.option("--subject", default=None, help="Filter by subject ID")
@click.option("--limit", default=50, type=int, help="Number of sessions")
@click.pass_context
def list_sessions(
    ctx: click.Context,
    status: str | None,
    subject: str | None,
    limit: int,
) -> None:
    """List sessions in the database."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.core.state import StateManager
    
    config = ctx.obj["config"]
    state = StateManager(config)
    
    sessions = state.get_sessions(status=status, subject_label=subject, limit=limit)
    
    if not sessions:
        console.print("[yellow]No sessions found[/yellow]")
        return
    
    table = Table(title=f"Sessions ({len(sessions)} shown)")
    table.add_column("ID")
    table.add_column("Subject")
    table.add_column("Session")
    table.add_column("Status")
    table.add_column("Pipelines")
    table.add_column("Updated")
    
    for sess in sessions:
        status_color = {
            "completed": "green",
            "processing": "blue",
            "failed": "red",
            "validated": "yellow",
            "discovered": "dim",
        }.get(sess.status.value, "white")
        
        table.add_row(
            str(sess.id),
            sess.subject.subject_label if sess.subject else "-",
            sess.session_label,
            f"[{status_color}]{sess.status.value}[/{status_color}]",
            str(len(sess.pipeline_runs)) if sess.pipeline_runs else "0",
            sess.updated_at.strftime("%Y-%m-%d %H:%M") if sess.updated_at else "-",
        )
    
    console.print(table)


@session.command("show")
@click.argument("session_id", type=int)
@click.pass_context
def show_session(ctx: click.Context, session_id: int) -> None:
    """Show detailed session information."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.core.state import StateManager
    
    config = ctx.obj["config"]
    state = StateManager(config)
    
    sess = state.get_session(session_id)
    if not sess:
        console.print(f"[red]Session {session_id} not found[/red]")
        return
    
    console.print(f"[bold]Session {sess.id}[/bold]")
    console.print(f"Subject: {sess.subject.subject_label if sess.subject else 'N/A'}")
    console.print(f"Label: {sess.session_label}")
    console.print(f"Status: {sess.status.value}")
    console.print(f"DICOM Path: {sess.dicom_path}")
    console.print(f"BIDS Path: {sess.bids_path or 'Not converted'}")
    
    if sess.pipeline_runs:
        console.print("\n[bold]Pipeline Runs:[/bold]")
        for run in sess.pipeline_runs:
            status_color = "green" if run.status.value == "completed" else "red"
            console.print(
                f"  {run.pipeline_name}: [{status_color}]{run.status.value}[/{status_color}]"
            )


@session.command("rerun")
@click.argument("session_id", type=int)
@click.option("--reason", default="Manual rerun", help="Reason for rerun")
@click.pass_context
def rerun_session(ctx: click.Context, session_id: int, reason: str) -> None:
    """Mark a session for reprocessing."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.core.state import StateManager
    
    config = ctx.obj["config"]
    state = StateManager(config)
    
    state.mark_session_for_rerun(session_id, reason)
    console.print(f"[green]Session {session_id} marked for rerun[/green]")


@session.command("exclude")
@click.argument("session_id", type=int)
@click.option("--reason", required=True, help="Reason for exclusion")
@click.pass_context
def exclude_session(ctx: click.Context, session_id: int, reason: str) -> None:
    """Exclude a session from processing."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.core.state import StateManager
    from neuroflow.models import SessionStatus
    
    config = ctx.obj["config"]
    state = StateManager(config)
    
    state.update_session(session_id, status=SessionStatus.EXCLUDED)
    console.print(f"[yellow]Session {session_id} excluded: {reason}[/yellow]")
```

## Main CLI Entry Point

### File: `neuroflow/cli/main.py`

```python
"""Main CLI entry point."""

import click
from rich.console import Console

from neuroflow.cli.logs import logs
from neuroflow.cli.recovery import recovery
from neuroflow.cli.session import session
from neuroflow.cli.workflow import workflow

console = Console()


@click.group()
@click.option("--config", "-c", default=None, help="Path to config file")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def cli(ctx: click.Context, config: str | None, verbose: bool) -> None:
    """Neuroflow - Neuroimaging workflow orchestration."""
    from neuroflow.config import NeuroflowConfig
    from neuroflow.core.logging import setup_logging
    
    # Load config
    if config:
        cfg = NeuroflowConfig.from_file(config)
    else:
        cfg = NeuroflowConfig.find_and_load()
    
    # Setup logging
    log_format = "console" if verbose else "json"
    log_level = "DEBUG" if verbose else cfg.logging.level
    setup_logging(level=log_level, format=log_format)
    
    # Store in context
    ctx.ensure_object(dict)
    ctx.obj["config"] = cfg
    ctx.obj["verbose"] = verbose


@cli.group()
def run() -> None:
    """Run services."""


@run.command("worker")
@click.option("--queues", "-Q", default=None, help="Comma-separated queue names")
@click.option("--concurrency", "-c", default=None, type=int, help="Worker concurrency")
@click.pass_context
def run_worker(ctx: click.Context, queues: str | None, concurrency: int | None) -> None:
    """Run Celery worker."""
    from neuroflow.workers.celery_app import get_celery_app
    
    config = ctx.obj["config"]
    app = get_celery_app()
    
    # Build worker arguments
    argv = ["worker", "--loglevel=INFO"]
    
    if queues:
        argv.extend(["-Q", queues])
    else:
        argv.extend(["-Q", "workflow,discovery,bids,processing,heavy_processing,default"])
    
    if concurrency:
        argv.extend(["-c", str(concurrency)])
    else:
        argv.extend(["-c", str(config.celery.worker_concurrency)])
    
    console.print("[green]Starting Celery worker...[/green]")
    app.worker_main(argv)


@run.command("beat")
@click.pass_context
def run_beat(ctx: click.Context) -> None:
    """Run Celery beat scheduler."""
    from neuroflow.workers.celery_app import get_celery_app
    
    app = get_celery_app()
    
    console.print("[green]Starting Celery beat...[/green]")
    app.Beat().run()


@cli.command("init")
@click.option("--force", is_flag=True, help="Overwrite existing config")
@click.pass_context
def init_config(ctx: click.Context, force: bool) -> None:
    """Initialize neuroflow configuration."""
    from pathlib import Path
    
    config_path = Path("neuroflow.yaml")
    
    if config_path.exists() and not force:
        console.print("[yellow]Config file already exists. Use --force to overwrite.[/yellow]")
        return
    
    default_config = """# Neuroflow Configuration
# See documentation for full options

paths:
  dicom_root: /data/dicom
  bids_root: /data/bids
  derivatives_root: /data/derivatives
  log_dir: /var/log/neuroflow

database:
  url: sqlite:///neuroflow.db

redis:
  url: redis://localhost:6379/0

workflow:
  schedule: "0 2 */3 * *"  # 2 AM every 3 days
  max_concurrent:
    bids_conversion: 4
    qsiprep: 1
    qsirecon: 2
    qsiparc: 4

pipelines:
  bids_conversion:
    enabled: true
    timeout_minutes: 60
  
  subject_level:
    - name: qsiprep
      enabled: true
      timeout_minutes: 1440
  
  session_level:
    - name: qsirecon
      enabled: true
      timeout_minutes: 720
    - name: qsiparc
      enabled: true
      timeout_minutes: 240

logging:
  level: INFO
  format: json
"""
    
    config_path.write_text(default_config)
    console.print(f"[green]Created {config_path}[/green]")


# Register command groups
cli.add_command(workflow)
cli.add_command(session)
cli.add_command(logs)
cli.add_command(recovery)


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
```

## Setup Entry Point

### Update `pyproject.toml`:

```toml
[project.scripts]
neuroflow = "neuroflow.cli.main:main"
```

## Usage Examples

```bash
# Initialize configuration
neuroflow init

# Run complete workflow
neuroflow workflow run

# Run with verbose output
neuroflow -v workflow run

# Run specific stage
neuroflow workflow run --stage bids_conversion

# Dry run
neuroflow workflow run --dry-run

# Check status
neuroflow workflow status

# List recent workflow runs
neuroflow workflow list

# List failed runs
neuroflow workflow list --status failed

# View sessions
neuroflow session list
neuroflow session list --status failed
neuroflow session show 123

# Mark session for rerun
neuroflow session rerun 123 --reason "Data was incomplete"

# View logs
neuroflow logs show --tail 100
neuroflow logs pipeline 456
neuroflow logs audit --entity session --entity-id 123

# Recovery commands
neuroflow recovery list
neuroflow recovery retry 789
neuroflow recovery resolve 789 --notes "Data quality issue"

# Run services
neuroflow run worker
neuroflow run worker -Q heavy_processing -c 1
neuroflow run beat
```
