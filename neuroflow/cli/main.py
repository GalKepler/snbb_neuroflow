"""Neuroflow CLI entry point."""

import click
from rich.console import Console

from neuroflow.config import NeuroflowConfig
from neuroflow.core.logging import setup_logging

console = Console()


@click.group()
@click.option("--config", "-c", default=None, help="Config file path")
@click.option("--log-level", default=None, help="Log level")
@click.pass_context
def cli(ctx: click.Context, config: str | None, log_level: str | None) -> None:
    """Neuroflow - Neuroimaging pipeline orchestration."""
    ctx.ensure_object(dict)

    try:
        cfg = NeuroflowConfig.find_and_load(config)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(2) from e

    ctx.obj["config"] = cfg

    level = log_level or cfg.logging.level
    setup_logging(level=level, format=cfg.logging.format)


@cli.group()
def admin() -> None:
    """Administrative commands."""


@admin.command("init-db")
@click.pass_context
def init_db(ctx: click.Context) -> None:
    """Initialize the database."""
    from neuroflow.core.state import StateManager

    config = ctx.obj["config"]
    state = StateManager(config)
    state.init_db()
    console.print("[green]Database initialized successfully.[/green]")


@admin.command("reset")
@click.option("--confirm", is_flag=True, help="Confirm database reset")
@click.pass_context
def reset_db(ctx: click.Context, confirm: bool) -> None:
    """Reset the database (DANGEROUS)."""
    if not confirm:
        console.print("[red]Use --confirm to reset the database.[/red]")
        return

    from neuroflow.core.state import StateManager

    config = ctx.obj["config"]
    state = StateManager(config)
    state.drop_db()
    state.init_db()
    console.print("[green]Database reset successfully.[/green]")


@cli.group("config")
def config_cmd() -> None:
    """Configuration commands."""


@config_cmd.command("show")
@click.option("--section", default=None, help="Show specific section")
@click.pass_context
def config_show(ctx: click.Context, section: str | None) -> None:
    """Show current configuration."""
    import json

    config = ctx.obj["config"]
    data = config.model_dump(mode="json")

    if section:
        if section in data:
            data = {section: data[section]}
        else:
            console.print(f"[red]Unknown section: {section}[/red]")
            raise SystemExit(1)

    console.print_json(json.dumps(data, indent=2, default=str))


@config_cmd.command("validate")
@click.option("--config-file", default=None, help="Config file to validate")
@click.pass_context
def config_validate(ctx: click.Context, config_file: str | None) -> None:
    """Validate configuration file."""
    if config_file:
        try:
            NeuroflowConfig.from_yaml(config_file)
            console.print(f"[green]Configuration valid: {config_file}[/green]")
        except Exception as e:
            console.print(f"[red]Configuration invalid: {e}[/red]")
            raise SystemExit(2)
    else:
        console.print("[green]Current configuration is valid.[/green]")


# Import and register subcommand groups
def _register_commands() -> None:
    from neuroflow.cli.export import export
    from neuroflow.cli.process import process
    from neuroflow.cli.run import run
    from neuroflow.cli.scan import scan
    from neuroflow.cli.status import status

    cli.add_command(scan)
    cli.add_command(status)
    cli.add_command(run)
    cli.add_command(process)
    cli.add_command(export)


_register_commands()


if __name__ == "__main__":
    cli()
