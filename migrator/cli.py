"""Command-line interface for the ITGlue to SuperOps migration tool."""

import asyncio
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from migrator import __version__
from migrator.config import Config, load_config
from migrator.logging import logger


console = Console()


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="ITGlue to SuperOps Migrator")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Path to configuration file (YAML or JSON)",
)
@click.option(
    "--env-file",
    "-e",
    type=click.Path(exists=True, path_type=Path),
    help="Path to .env file",
)
@click.pass_context
def cli(ctx: click.Context, config: Optional[Path], env_file: Optional[Path]) -> None:
    """ITGlue to SuperOps Documentation Migration Tool.

    Enterprise-grade tool for migrating ITGlue document exports to SuperOps Knowledge Base.
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        return

    # Store configuration path in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["env_file"] = env_file


@cli.command()
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("config.yaml"),
    help="Output path for configuration file",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["yaml", "json"]),
    default="yaml",
    help="Configuration file format",
)
def init(output: Path, format: str) -> None:
    """Initialize a new configuration file with default values."""
    console.print(f"[bold blue]Creating configuration file: {output}[/bold blue]")

    # Create default configuration
    from migrator.config import (
        Config,
        DatabaseConfig,
        LoggingConfig,
        MigrationConfig,
        SourceConfig,
        SuperOpsConfig,
    )

    # Prompt for required values
    console.print("\n[bold yellow]Required Configuration:[/bold yellow]")

    api_token = click.prompt("SuperOps API Token", hide_input=True)
    subdomain = click.prompt("SuperOps Subdomain")
    data_center = click.prompt(
        "Data Center (us/eu)",
        default="us",
        type=click.Choice(["us", "eu"]),
    )

    # Create configuration
    try:
        config = Config(
            source=SourceConfig(),
            superops=SuperOpsConfig(
                api_token=api_token,  # type: ignore
                subdomain=subdomain,
                data_center=data_center,  # type: ignore
            ),
            database=DatabaseConfig(),
            migration=MigrationConfig(),
            logging=LoggingConfig(),
        )

        # Set extension based on format
        if format == "json" and not output.suffix:
            output = output.with_suffix(".json")
        elif format == "yaml" and not output.suffix:
            output = output.with_suffix(".yaml")

        # Save configuration
        config.to_file(output)
        console.print(f"\n[bold green]✓[/bold green] Configuration saved to: {output}")
        console.print("\n[yellow]Next steps:[/yellow]")
        console.print("1. Review and adjust the configuration file as needed")
        console.print("2. Run 'itglue-migrate validate' to verify configuration")
        console.print("3. Run 'itglue-migrate migrate' to start migration")

    except Exception as e:
        console.print(f"[bold red]Error creating configuration:[/bold red] {e}")
        sys.exit(1)


@cli.command()
@click.pass_context
def validate(ctx: click.Context) -> None:
    """Validate configuration and test API connectivity."""
    config_path = ctx.obj.get("config_path")
    env_file = ctx.obj.get("env_file")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Loading configuration...", total=None)

        try:
            config = load_config(config_path, env_file)
            progress.update(task, description="[green]✓[/green] Configuration loaded")
        except Exception as e:
            progress.update(task, description=f"[red]✗[/red] Configuration error: {e}")
            sys.exit(1)

        # Validate paths
        progress.add_task("Validating paths...", total=None)
        errors = config.validate_paths()
        if errors:
            console.print("\n[bold red]Path validation errors:[/bold red]")
            for error in errors:
                console.print(f"  • {error}")
            if not config.migration.dry_run:
                sys.exit(1)
        else:
            console.print("[green]✓[/green] All paths validated")

        # Test API connectivity
        progress.add_task("Testing SuperOps API connectivity...", total=None)
        asyncio.run(_test_api_connectivity(config))

    # Display configuration summary
    _display_config_summary(config)


@cli.command()
@click.pass_context
@click.option(
    "--resume",
    is_flag=True,
    help="Resume from last checkpoint",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Perform dry run without making API calls",
)
@click.option(
    "--batch-size",
    type=int,
    help="Override batch size from configuration",
)
@click.option(
    "--limit",
    type=int,
    help="Limit number of documents to migrate",
)
@click.option(
    "--filter",
    "doc_filter",
    help="Filter documents by title pattern (regex)",
)
def migrate(
    ctx: click.Context,
    resume: bool,
    dry_run: bool,
    batch_size: Optional[int],
    limit: Optional[int],
    doc_filter: Optional[str],
) -> None:
    """Start the migration process."""
    config_path = ctx.obj.get("config_path")
    env_file = ctx.obj.get("env_file")

    try:
        config = load_config(config_path, env_file)
    except Exception as e:
        console.print(f"[bold red]Error loading configuration:[/bold red] {e}")
        sys.exit(1)

    # Override configuration with CLI options
    if dry_run:
        config.migration.dry_run = True
    if batch_size:
        config.migration.batch_size = batch_size

    # Configure logging
    logger.configure(config.logging)
    log = logger.get_logger("cli")

    # Display migration plan
    console.print("\n[bold blue]Migration Configuration:[/bold blue]")
    console.print(f"  • Source: {config.source.documents_path}")
    console.print(f"  • Target: {config.superops.subdomain} ({config.superops.data_center})")
    console.print(f"  • Batch Size: {config.migration.batch_size}")
    console.print(f"  • Dry Run: {config.migration.dry_run}")
    console.print(f"  • Resume: {resume}")
    if limit:
        console.print(f"  • Limit: {limit} documents")
    if doc_filter:
        console.print(f"  • Filter: {doc_filter}")

    if not dry_run:
        if not click.confirm("\nProceed with migration?"):
            console.print("[yellow]Migration cancelled[/yellow]")
            return

    # Run migration
    console.print("\n[bold green]Starting migration...[/bold green]")
    log.info("migration_started", resume=resume, dry_run=dry_run, limit=limit)

    try:
        asyncio.run(_run_migration(config, resume, limit, doc_filter))
    except KeyboardInterrupt:
        console.print("\n[yellow]Migration interrupted by user[/yellow]")
        log.warning("migration_interrupted")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[bold red]Migration failed:[/bold red] {e}")
        log.error("migration_failed", error=str(e), exc_info=e)
        sys.exit(1)


@cli.command()
@click.pass_context
@click.option(
    "--format",
    "-f",
    type=click.Choice(["summary", "detailed", "json"]),
    default="summary",
    help="Report format",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Save report to file",
)
def report(ctx: click.Context, format: str, output: Optional[Path]) -> None:
    """Generate migration report from the database."""
    config_path = ctx.obj.get("config_path")
    env_file = ctx.obj.get("env_file")

    try:
        config = load_config(config_path, env_file)
    except Exception as e:
        console.print(f"[bold red]Error loading configuration:[/bold red] {e}")
        sys.exit(1)

    # Generate report
    asyncio.run(_generate_report(config, format, output))


@cli.command()
@click.pass_context
def clean(ctx: click.Context) -> None:
    """Clean up migration state and temporary files."""
    config_path = ctx.obj.get("config_path")
    env_file = ctx.obj.get("env_file")

    try:
        config = load_config(config_path, env_file)
    except Exception as e:
        console.print(f"[bold red]Error loading configuration:[/bold red] {e}")
        sys.exit(1)

    console.print("[bold yellow]This will remove:[/bold yellow]")
    console.print(f"  • Database: {config.database.path}")
    if config.logging.file:
        console.print(f"  • Log files: {config.logging.file}*")

    if not click.confirm("\nProceed with cleanup?"):
        console.print("[yellow]Cleanup cancelled[/yellow]")
        return

    # Remove database
    if config.database.path.exists():
        config.database.path.unlink()
        console.print(f"[green]✓[/green] Removed database: {config.database.path}")

    # Remove log files
    if config.logging.file:
        log_pattern = f"{config.logging.file.stem}*{config.logging.file.suffix}"
        for log_file in config.logging.file.parent.glob(log_pattern):
            log_file.unlink()
            console.print(f"[green]✓[/green] Removed log file: {log_file}")

    console.print("\n[bold green]Cleanup completed[/bold green]")


async def _test_api_connectivity(config: Config) -> None:
    """Test SuperOps API connectivity.

    Args:
        config: Configuration instance
    """
    # This will be implemented when we create the API client
    console.print("[yellow]API connectivity test will be available after API client implementation[/yellow]")


async def _run_migration(
    config: Config,
    resume: bool,
    limit: Optional[int],
    doc_filter: Optional[str],
) -> None:
    """Run the migration process.

    Args:
        config: Configuration instance
        resume: Whether to resume from last checkpoint
        limit: Maximum number of documents to migrate
        doc_filter: Document filter pattern
    """
    from migrator.core.orchestrator import MigrationOrchestrator
    
    orchestrator = MigrationOrchestrator(config)
    
    try:
        result = await orchestrator.migrate(
            resume=resume,
            limit=limit,
            filter_pattern=doc_filter,
        )
        
        # Display results
        console.print("\n[bold green]Migration completed successfully![/bold green]")
        console.print(f"  • Total documents: {result.get('total_documents', 0)}")
        console.print(f"  • Successful: {result.get('successful_documents', 0)}")
        console.print(f"  • Failed: {result.get('failed_documents', 0)}")
        console.print(f"  • Skipped: {result.get('skipped_documents', 0)}")
        console.print(f"  • Duration: {result.get('duration_seconds', 0):.1f} seconds")
        
    except Exception as e:
        console.print(f"[bold red]Migration failed:[/bold red] {e}")
        raise


async def _generate_report(
    config: Config,
    format: str,
    output: Optional[Path],
) -> None:
    """Generate migration report.

    Args:
        config: Configuration instance
        format: Report format
        output: Optional output file path
    """
    from migrator.core.database import Database
    
    db = Database(config.database.path, config.database.connection_timeout)
    await db.initialize()
    
    # Get latest run
    run = await db.get_latest_migration_run()
    if not run:
        console.print("[yellow]No migration runs found[/yellow]")
        return
    
    # Get statistics
    stats = await db.get_statistics(run.id)
    
    if format == "json":
        import json
        report_data = {
            "run_id": run.id,
            "started_at": run.started_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "statistics": stats,
            "totals": {
                "documents": run.total_documents,
                "successful": run.successful_documents,
                "failed": run.failed_documents,
                "skipped": run.skipped_documents,
            },
        }
        report = json.dumps(report_data, indent=2)
    else:
        # Create text report
        report_lines = [
            "=" * 60,
            "MIGRATION REPORT",
            "=" * 60,
            f"Run ID: {run.id}",
            f"Started: {run.started_at}",
            f"Completed: {run.completed_at or 'In Progress'}",
            "",
            "DOCUMENT STATISTICS",
            "-" * 30,
            f"Total: {run.total_documents}",
            f"Successful: {run.successful_documents}",
            f"Failed: {run.failed_documents}",
            f"Skipped: {run.skipped_documents}",
            "",
        ]
        
        if format == "detailed":
            report_lines.extend([
                "DETAILED STATISTICS",
                "-" * 30,
                f"Documents by status: {stats.get('documents', {})}",
                f"Attachments: {stats.get('attachments', {})}",
                "",
            ])
        
        report = "\n".join(report_lines)
    
    if output:
        output.write_text(report)
        console.print(f"[green]Report saved to {output}[/green]")
    else:
        console.print(report)


def _display_config_summary(config: Config) -> None:
    """Display configuration summary.

    Args:
        config: Configuration instance
    """
    table = Table(title="Configuration Summary", show_header=True)
    table.add_column("Category", style="cyan")
    table.add_column("Setting", style="yellow")
    table.add_column("Value", style="green")

    # Source configuration
    table.add_row("Source", "Documents Path", str(config.source.documents_path))
    table.add_row("Source", "CSV Path", str(config.source.csv_path))
    table.add_row("Source", "Attachments Path", str(config.source.attachments_path))

    # SuperOps configuration
    table.add_row("SuperOps", "Subdomain", config.superops.subdomain)
    table.add_row("SuperOps", "Data Center", config.superops.data_center.value)
    table.add_row("SuperOps", "Rate Limit", f"{config.superops.rate_limit} req/min")

    # Migration configuration
    table.add_row("Migration", "Batch Size", str(config.migration.batch_size))
    table.add_row("Migration", "Skip Existing", str(config.migration.skip_existing))
    table.add_row("Migration", "Dry Run", str(config.migration.dry_run))

    # Database configuration
    table.add_row("Database", "Path", str(config.database.path))

    # Logging configuration
    table.add_row("Logging", "Level", config.logging.level.value)
    table.add_row("Logging", "Console", str(config.logging.console))
    if config.logging.file:
        table.add_row("Logging", "File", str(config.logging.file))

    console.print("\n")
    console.print(table)


def main() -> None:
    """Main entry point for the CLI."""
    try:
        cli(obj={})
    except Exception as e:
        console.print(f"[bold red]Unexpected error:[/bold red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()