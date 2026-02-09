"""Worker CLI commands for managing the Huey consumer."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import click
import psutil
from rich.console import Console
from rich.table import Table

console = Console()


def _get_pid_file(state_dir: Path) -> Path:
    """Get the path to the worker PID file."""
    return state_dir / "worker.pid"


def _read_pid(pid_file: Path) -> int | None:
    """Read PID from file, return None if file doesn't exist or is invalid."""
    if not pid_file.exists():
        return None

    try:
        pid = int(pid_file.read_text().strip())
        # Verify process exists
        if psutil.pid_exists(pid):
            return pid
        else:
            # Stale PID file
            pid_file.unlink()
            return None
    except (ValueError, OSError):
        return None


def _write_pid(pid_file: Path, pid: int) -> None:
    """Write PID to file."""
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(pid))


def _get_worker_info(pid: int) -> dict | None:
    """Get information about a running worker process."""
    try:
        proc = psutil.Process(pid)
        return {
            "pid": pid,
            "status": proc.status(),
            "cpu_percent": proc.cpu_percent(interval=0.1),
            "memory_mb": proc.memory_info().rss / 1024 / 1024,
            "num_threads": proc.num_threads(),
            "create_time": proc.create_time(),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


@click.group()
def worker() -> None:
    """Manage the background pipeline worker (Huey consumer)."""


@worker.command("start")
@click.option(
    "--workers",
    "-w",
    default=None,
    type=int,
    help="Number of parallel workers (default: from config)",
)
@click.option(
    "--daemon/--no-daemon",
    default=False,
    help="Run in background as daemon (default: foreground)",
)
@click.option(
    "--logfile",
    "-l",
    default=None,
    type=click.Path(),
    help="Log file path (default: logs/worker.log)",
)
@click.pass_context
def start(
    ctx: click.Context,
    workers: int | None,
    daemon: bool,
    logfile: str | None,
) -> None:
    """Start the Huey consumer to process queued pipelines.

    The consumer pulls tasks from the background queue and executes them
    in parallel workers. By default, runs in foreground. Use --daemon to
    run in background.

    Examples:
        # Start in foreground with 4 workers
        neuroflow worker start -w 4

        # Start in background as daemon
        neuroflow worker start --daemon

        # Start with custom log file
        neuroflow worker start -w 4 -l /var/log/neuroflow/worker.log --daemon
    """
    config = ctx.obj["config"]
    state_dir = Path(config.execution.state_dir)
    pid_file = _get_pid_file(state_dir)

    # Check if worker is already running
    existing_pid = _read_pid(pid_file)
    if existing_pid:
        console.print(
            f"[yellow]Worker already running with PID {existing_pid}[/yellow]"
        )
        console.print("Use 'neuroflow worker stop' to stop it first.")
        sys.exit(1)

    # Determine worker count
    num_workers = workers or config.execution.max_workers

    # Determine log file
    if logfile is None:
        logfile = str(config.paths.log_dir / "worker.log")

    # Ensure log directory exists
    Path(logfile).parent.mkdir(parents=True, exist_ok=True)

    # Build consumer command
    # Set NEUROFLOW_STATE_DIR environment variable for consumer
    env = os.environ.copy()
    env["NEUROFLOW_STATE_DIR"] = str(state_dir)

    cmd = [
        sys.executable,
        "-m",
        "huey.bin.huey_consumer",
        "neuroflow.tasks.huey",
        "-w",
        str(num_workers),
        "-k",
        "process",
        "-l",
        logfile,
    ]

    console.print(f"[cyan]Starting Huey consumer...[/cyan]")
    console.print(f"  Workers: {num_workers}")
    console.print(f"  State dir: {state_dir}")
    console.print(f"  Log file: {logfile}")
    console.print(f"  Mode: {'daemon' if daemon else 'foreground'}")

    if daemon:
        # Start as background daemon
        console.print("\n[dim]Starting consumer in background...[/dim]")

        # Redirect stdout/stderr to log file
        with open(logfile, "a") as log_fh:
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # Detach from terminal
            )

        # Wait a moment to check if it started successfully
        time.sleep(1)

        if proc.poll() is None:
            # Process is still running
            _write_pid(pid_file, proc.pid)
            console.print(
                f"\n[green]✓[/green] Worker started successfully (PID: {proc.pid})"
            )
            console.print(f"  Monitor: tail -f {logfile}")
            console.print(f"  Status: neuroflow worker status")
            console.print(f"  Stop: neuroflow worker stop")
        else:
            console.print(
                f"\n[red]✗[/red] Worker failed to start (exit code: {proc.returncode})"
            )
            console.print(f"  Check log: {logfile}")
            sys.exit(1)
    else:
        # Run in foreground
        console.print("\n[dim]Running consumer in foreground (Ctrl+C to stop)...[/dim]\n")

        try:
            # Run with current process's stdout/stderr
            proc = subprocess.Popen(cmd, env=env)
            _write_pid(pid_file, proc.pid)

            # Wait for process to complete
            proc.wait()
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted by user, stopping worker...[/yellow]")
            proc.terminate()
            proc.wait(timeout=10)
        finally:
            # Clean up PID file
            if pid_file.exists():
                pid_file.unlink()


@worker.command("stop")
@click.option(
    "--timeout",
    "-t",
    default=30,
    type=int,
    help="Wait timeout in seconds (default: 30)",
)
@click.pass_context
def stop(ctx: click.Context, timeout: int) -> None:
    """Stop the running Huey consumer gracefully.

    Sends SIGTERM to allow graceful shutdown, then waits for process to exit.
    If process doesn't stop within timeout, sends SIGKILL.

    Examples:
        # Stop with default 30s timeout
        neuroflow worker stop

        # Stop with 60s timeout
        neuroflow worker stop -t 60
    """
    config = ctx.obj["config"]
    state_dir = Path(config.execution.state_dir)
    pid_file = _get_pid_file(state_dir)

    pid = _read_pid(pid_file)
    if not pid:
        console.print("[yellow]No running worker found[/yellow]")
        sys.exit(0)

    console.print(f"[cyan]Stopping worker (PID: {pid})...[/cyan]")

    try:
        proc = psutil.Process(pid)

        # Send SIGTERM for graceful shutdown
        console.print("  Sending SIGTERM (graceful shutdown)...")
        proc.terminate()

        # Wait for process to exit
        try:
            proc.wait(timeout=timeout)
            console.print(f"[green]✓[/green] Worker stopped successfully")
        except psutil.TimeoutExpired:
            # Process didn't stop, send SIGKILL
            console.print(
                f"[yellow]  Process didn't stop within {timeout}s, sending SIGKILL...[/yellow]"
            )
            proc.kill()
            proc.wait(timeout=5)
            console.print("[green]✓[/green] Worker killed")

        # Clean up PID file
        if pid_file.exists():
            pid_file.unlink()

    except psutil.NoSuchProcess:
        console.print("[yellow]Process not found (already stopped)[/yellow]")
        if pid_file.exists():
            pid_file.unlink()
    except psutil.AccessDenied:
        console.print(
            f"[red]✗[/red] Permission denied (try: kill {pid})"
        )
        sys.exit(1)


@worker.command("status")
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show worker status and queue information.

    Displays:
    - Worker process status (running/stopped)
    - Process information (PID, CPU, memory)
    - Queue statistics (pending/scheduled tasks)

    Examples:
        neuroflow worker status
    """
    from neuroflow.tasks import get_queue_stats

    config = ctx.obj["config"]
    state_dir = Path(config.execution.state_dir)
    pid_file = _get_pid_file(state_dir)

    # Check worker status
    pid = _read_pid(pid_file)

    if not pid:
        console.print("[yellow]Worker: Not running[/yellow]")
        console.print("\nStart with: neuroflow worker start")
    else:
        info = _get_worker_info(pid)

        if not info:
            console.print(f"[yellow]Worker: Process {pid} not found (stale PID file)[/yellow]")
            if pid_file.exists():
                pid_file.unlink()
        else:
            console.print("[green]Worker: Running[/green]")

            # Worker info table
            table = Table(title="Worker Process")
            table.add_column("Property", style="cyan")
            table.add_column("Value")

            table.add_row("PID", str(info["pid"]))
            table.add_row("Status", info["status"])
            table.add_row("CPU %", f"{info['cpu_percent']:.1f}%")
            table.add_row("Memory", f"{info['memory_mb']:.1f} MB")
            table.add_row("Threads", str(info["num_threads"]))

            # Calculate uptime
            uptime_seconds = time.time() - info["create_time"]
            uptime_hours = uptime_seconds / 3600
            if uptime_hours < 1:
                uptime_str = f"{uptime_seconds / 60:.1f} minutes"
            elif uptime_hours < 24:
                uptime_str = f"{uptime_hours:.1f} hours"
            else:
                uptime_str = f"{uptime_hours / 24:.1f} days"
            table.add_row("Uptime", uptime_str)

            console.print(table)

    # Queue stats
    console.print("\n[cyan]Queue Statistics:[/cyan]")

    # Set environment variable for queue stats
    os.environ["NEUROFLOW_STATE_DIR"] = str(state_dir)

    try:
        stats = get_queue_stats()
        console.print(f"  Pending: {stats['pending']}")
        console.print(f"  Scheduled: {stats['scheduled']}")
    except Exception as e:
        console.print(f"  [red]Error getting queue stats: {e}[/red]")

    # Show state directory
    console.print(f"\n[dim]State directory: {state_dir}[/dim]")


@worker.command("restart")
@click.option(
    "--workers",
    "-w",
    default=None,
    type=int,
    help="Number of parallel workers (default: from config)",
)
@click.pass_context
def restart(ctx: click.Context, workers: int | None) -> None:
    """Restart the Huey consumer.

    Stops the current worker and starts a new one. Always runs in daemon mode.

    Examples:
        # Restart with same config
        neuroflow worker restart

        # Restart with different worker count
        neuroflow worker restart -w 8
    """
    console.print("[cyan]Restarting worker...[/cyan]\n")

    # Stop existing worker
    ctx.invoke(stop, timeout=30)

    console.print()

    # Start new worker in daemon mode
    ctx.invoke(start, workers=workers, daemon=True, logfile=None)
