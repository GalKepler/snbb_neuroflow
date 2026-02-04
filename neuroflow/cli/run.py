"""Service run CLI commands."""

import click
from rich.console import Console

console = Console()


@click.group()
def run() -> None:
    """Service commands."""


@run.command("worker")
@click.option("-c", "--concurrency", default=None, type=int, help="Worker concurrency")
@click.option("--loglevel", default="INFO", help="Log level")
@click.pass_context
def run_worker(ctx: click.Context, concurrency: int | None, loglevel: str) -> None:
    """Start Celery worker."""
    from neuroflow.workers.celery_app import create_celery_app

    config = ctx.obj["config"]
    app = create_celery_app(config)
    conc = concurrency or config.celery.worker_concurrency

    console.print(f"[green]Starting Celery worker (concurrency={conc})...[/green]")
    app.worker_main(["worker", f"--concurrency={conc}", f"--loglevel={loglevel}"])


@run.command("beat")
@click.option("--loglevel", default="INFO", help="Log level")
@click.pass_context
def run_beat(ctx: click.Context, loglevel: str) -> None:
    """Start Celery beat scheduler."""
    from neuroflow.workers.celery_app import create_celery_app

    config = ctx.obj["config"]
    app = create_celery_app(config)

    console.print("[green]Starting Celery beat...[/green]")
    app.worker_main(["beat", f"--loglevel={loglevel}"])


@run.command("watcher")
@click.pass_context
def run_watcher(ctx: click.Context) -> None:
    """Start DICOM file watcher."""
    import time

    from neuroflow.discovery.watcher import DicomWatcher

    config = ctx.obj["config"]
    watcher = DicomWatcher(config)

    console.print(f"[green]Watching {config.paths.dicom_incoming}...[/green]")

    try:
        watcher.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        watcher.stop()
        console.print("[yellow]Watcher stopped.[/yellow]")


@run.command("all")
@click.option("-c", "--concurrency", default=None, type=int, help="Worker concurrency")
@click.pass_context
def run_all(ctx: click.Context, concurrency: int | None) -> None:
    """Start all services (worker, beat, watcher)."""
    import signal
    import threading
    import time

    from neuroflow.discovery.watcher import DicomWatcher
    from neuroflow.workers.celery_app import create_celery_app

    config = ctx.obj["config"]
    app = create_celery_app(config)
    conc = concurrency or config.celery.worker_concurrency

    console.print("[green]Starting all neuroflow services...[/green]")

    # Start watcher in background thread
    watcher = DicomWatcher(config)
    watcher_thread = threading.Thread(target=watcher.start, daemon=True)
    watcher_thread.start()
    console.print(f"  Watcher: watching {config.paths.dicom_incoming}")

    # Start worker (this blocks)
    console.print(f"  Worker: concurrency={conc}")
    console.print(f"  Beat: scheduled tasks enabled")
    try:
        app.worker_main([
            "worker",
            f"--concurrency={conc}",
            "--loglevel=INFO",
            "--beat",
        ])
    except KeyboardInterrupt:
        watcher.stop()
        console.print("[yellow]All services stopped.[/yellow]")
