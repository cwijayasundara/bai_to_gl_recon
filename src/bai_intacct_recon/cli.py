"""
Command-line interface for the BAI2 to Sage Intacct reconciliation tool.
"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional
import logging
import sys

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from .config import load_config, generate_default_config, ReconConfig
from .parsers.bai2_parser import BAI2Parser
from .parsers.intacct_parser import IntacctParser
from .matching.engine import ReconciliationEngine
from .reports.excel_generator import ExcelReportGenerator
from .utils.logging_config import setup_logging

console = Console()


@click.group()
@click.version_option(version="0.1.0")
def main():
    """BAI2 to Sage Intacct Bank Reconciliation Tool."""
    pass


@main.command()
@click.argument("bai2_file", type=click.Path(exists=True, path_type=Path))
@click.argument("intacct_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-c",
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path to configuration file (YAML)",
)
@click.option("-o", "--output", type=click.Path(path_type=Path), help="Output Excel file path")
@click.option(
    "--date-tolerance", type=int, default=None, help="Override date tolerance in days"
)
@click.option(
    "--amount-tolerance",
    type=float,
    default=None,
    help="Override amount tolerance in dollars",
)
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose output")
@click.option(
    "--dry-run", is_flag=True, help="Parse files and show summary without generating report"
)
def reconcile(
    bai2_file: Path,
    intacct_file: Path,
    config: Optional[Path],
    output: Optional[Path],
    date_tolerance: Optional[int],
    amount_tolerance: Optional[float],
    verbose: bool,
    dry_run: bool,
):
    """
    Reconcile a BAI2 bank statement with Sage Intacct transactions.

    BAI2_FILE: Path to the BAI2 bank statement file
    INTACCT_FILE: Path to the Sage Intacct CSV export
    """
    # Setup logging
    log_level = logging.DEBUG if verbose else logging.INFO
    setup_logging(log_level)

    try:
        # Load configuration
        recon_config = load_config(config)

        # Apply command-line overrides
        if date_tolerance is not None:
            _apply_date_tolerance_override(recon_config, date_tolerance)
        if amount_tolerance is not None:
            _apply_amount_tolerance_override(recon_config, amount_tolerance)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            # Parse BAI2 file
            task = progress.add_task("Parsing BAI2 file...", total=None)
            bai2_parser = BAI2Parser(recon_config)
            bank_transactions = bai2_parser.parse_file(bai2_file)
            progress.update(task, completed=True)

            # Parse Intacct file
            task = progress.add_task("Parsing Intacct CSV...", total=None)
            intacct_parser = IntacctParser(recon_config)
            intacct_transactions = intacct_parser.parse_file(intacct_file)
            progress.update(task, completed=True)

            # Run reconciliation
            task = progress.add_task("Running reconciliation...", total=None)
            start_time = datetime.now()

            engine = ReconciliationEngine(recon_config)
            matches, bank_only, intacct_only = engine.reconcile(
                bank_transactions, intacct_transactions
            )

            processing_time = (datetime.now() - start_time).total_seconds()
            progress.update(task, completed=True)

            # Generate summary
            summary = engine.generate_summary(
                bank_transactions=bank_transactions,
                intacct_transactions=intacct_transactions,
                matches=matches,
                bank_only=bank_only,
                intacct_only=intacct_only,
                bai2_filename=bai2_file.name,
                intacct_filename=intacct_file.name,
                processing_time=processing_time,
            )

        # Display summary
        _display_summary(summary)

        if dry_run:
            console.print("\n[yellow]Dry run - no report generated[/yellow]")
            return

        # Generate report
        if output is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output = Path(f"reconciliation_report_{timestamp}.xlsx")

        report_generator = ExcelReportGenerator(recon_config)
        report_path = report_generator.generate_report(
            summary=summary,
            matches=matches,
            bank_only=bank_only,
            intacct_only=intacct_only,
            output_path=output,
        )

        console.print(f"\n[green]Report generated: {report_path}[/green]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if verbose:
            console.print_exception()
        sys.exit(1)


@main.command("parse-bai2")
@click.argument("bai2_file", type=click.Path(exists=True, path_type=Path))
@click.option("-c", "--config", type=click.Path(exists=True, path_type=Path))
def parse_bai2(bai2_file: Path, config: Optional[Path]):
    """
    Parse a BAI2 file and display transaction summary.

    BAI2_FILE: Path to the BAI2 bank statement file
    """
    recon_config = load_config(config)
    parser = BAI2Parser(recon_config)

    try:
        transactions = parser.parse_file(bai2_file)

        table = Table(title=f"BAI2 Transactions: {bai2_file.name}")
        table.add_column("Date")
        table.add_column("Reference")
        table.add_column("Amount", justify="right")
        table.add_column("Type")
        table.add_column("Description")

        for txn in transactions[:20]:  # Show first 20
            table.add_row(
                str(txn.date),
                txn.reference or "-",
                f"${txn.amount:,.2f}",
                txn.type.value,
                (
                    txn.description[:40] + "..."
                    if len(txn.description) > 40
                    else txn.description
                ),
            )

        console.print(table)

        if len(transactions) > 20:
            console.print(f"\n... and {len(transactions) - 20} more transactions")

        console.print(f"\nTotal transactions: {len(transactions)}")

    except Exception as e:
        console.print(f"[red]Error parsing file: {e}[/red]")
        sys.exit(1)


@main.command("parse-intacct")
@click.argument("intacct_file", type=click.Path(exists=True, path_type=Path))
@click.option("-c", "--config", type=click.Path(exists=True, path_type=Path))
def parse_intacct(intacct_file: Path, config: Optional[Path]):
    """
    Parse a Sage Intacct CSV file and display transaction summary.

    INTACCT_FILE: Path to the Sage Intacct CSV export
    """
    recon_config = load_config(config)
    parser = IntacctParser(recon_config)

    try:
        transactions = parser.parse_file(intacct_file)

        table = Table(title=f"Intacct Transactions: {intacct_file.name}")
        table.add_column("Date")
        table.add_column("Reference")
        table.add_column("Amount", justify="right")
        table.add_column("Type")
        table.add_column("GL Account")

        for txn in transactions[:20]:  # Show first 20
            table.add_row(
                str(txn.date),
                txn.reference or "-",
                f"${txn.amount:,.2f}",
                txn.type.value,
                txn.gl_account or "-",
            )

        console.print(table)

        if len(transactions) > 20:
            console.print(f"\n... and {len(transactions) - 20} more transactions")

        console.print(f"\nTotal transactions: {len(transactions)}")

    except Exception as e:
        console.print(f"[red]Error parsing file: {e}[/red]")
        sys.exit(1)


@main.command("init-config")
@click.option(
    "-o", "--output", type=click.Path(path_type=Path), default=Path("config.yaml")
)
def init_config(output: Path):
    """Generate a sample configuration file."""
    generate_default_config(output)
    console.print(f"[green]Configuration file generated: {output}[/green]")


def _display_summary(summary) -> None:
    """Display reconciliation summary in console."""
    table = Table(title="Reconciliation Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Total Bank Transactions", str(summary.total_bank_transactions))
    table.add_row("Total Intacct Transactions", str(summary.total_intacct_transactions))
    table.add_row("Matched", str(summary.matched_count))
    table.add_row("Bank Only", str(summary.bank_only_count))
    table.add_row("Intacct Only", str(summary.intacct_only_count))
    table.add_row("Amount Variances", str(summary.variance_count))
    table.add_row("Bank Match Rate", f"{summary.match_rate_bank:.1f}%")
    table.add_row("Intacct Match Rate", f"{summary.match_rate_intacct:.1f}%")
    table.add_row("Processing Time", f"{summary.processing_time_seconds:.2f}s")

    console.print(table)


def _apply_date_tolerance_override(config: ReconConfig, days: int) -> None:
    """Apply date tolerance override to all relevant tiers."""
    matching_config = config.matching
    tiers = matching_config.tiers if hasattr(matching_config, "tiers") else []

    for tier in tiers:
        for rule in tier.rules:
            if rule.field == "date" and rule.match_type == "tolerance":
                rule.tolerance_days = days


def _apply_amount_tolerance_override(config: ReconConfig, amount: float) -> None:
    """Apply amount tolerance override to all relevant tiers."""
    matching_config = config.matching
    tiers = matching_config.tiers if hasattr(matching_config, "tiers") else []

    for tier in tiers:
        for rule in tier.rules:
            if rule.field == "amount" and rule.match_type == "tolerance":
                rule.tolerance_amount = amount


if __name__ == "__main__":
    main()
