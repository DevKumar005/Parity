"""Parity CLI — Single entry point for autonomous migration verification.

Commands:
    parity run <path_to_c_module>   Run full pipeline on a single legacy C module
    parity evaluate                 Run evaluation suite across all sample modules
    parity info                     Show configuration, models, and provider status
    parity serve                    Start local web dashboard & visualization server
"""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
app = typer.Typer(
    name="parity",
    help="Parity: Verify migrated billing systems behave identically to legacy code.",
    add_completion=False,
)

BANNER = r"""[bold cyan]
  ____             _ _
 |  _ \ __ _ _ __ (_) |_ _   _
 | |_) / _` | '__|| | __| | | |
 |  __/ (_| | |   | | |_| |_| |
 |_|   \__,_|_|   |_|\__|\__, |
                         |___/
[/bold cyan][dim]Autonomous Billing Migration & Behavioral Equivalence Verification[/dim]
[dim]Powered by Muse Spark Open (Meta Open Weights)[/dim]
"""


def _load_env_file() -> None:
    """Load variables from .env file if present."""
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())


@app.callback()
def main() -> None:
    """Ensure environment is initialized."""
    _load_env_file()


@app.command(name="run")
def run_command(
    source_path: Path = typer.Argument(
        ...,
        help="Path to the legacy C file to migrate and verify",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
    seed: int = typer.Option(42, "--seed", "-s", help="Random seed for input generation"),
    skip_redteam: bool = typer.Option(False, "--skip-redteam", help="Skip red team adversarial checks"),
    open_report: bool = typer.Option(False, "--open-report", "-o", help="Automatically open HTML report in browser"),
) -> None:
    """Run Parity autonomous verification pipeline on a legacy C module."""
    console.print(BANNER)
    from .pipeline import run_pipeline

    result = run_pipeline(
        source_path=source_path,
        seed=seed,
        skip_redteam=skip_redteam,
    )

    if open_report and result.run_dir:
        report_file = result.run_dir / "report.html"
        if report_file.exists():
            console.print(f"[cyan]Opening {report_file}...[/cyan]")
            webbrowser.open(report_file.as_uri())


@app.command(name="evaluate")
def evaluate_command(
    samples_dir: Path = typer.Option(
        Path("samples/legacy"),
        "--samples",
        "-d",
        help="Directory containing legacy C modules",
    ),
    seed: int = typer.Option(42, "--seed", "-s", help="Base seed for reproducibility"),
) -> None:
    """Run the complete evaluation suite across all sample modules and output summary table."""
    console.print(BANNER)
    from .pipeline import run_pipeline

    if not samples_dir.exists():
        console.print(f"[red]Error: Samples directory '{samples_dir}' not found.[/red]")
        raise typer.Exit(code=1)

    c_files = sorted(list(samples_dir.glob("*.c")))
    if not c_files:
        console.print(f"[red]No .c files found in '{samples_dir}'.[/red]")
        raise typer.Exit(code=1)

    results = []
    console.print(f"[bold]Evaluating {len(c_files)} legacy module(s)...[/bold]\n")

    for c_file in c_files:
        console.print(f"[bold cyan]Testing module: {c_file.name}[/bold cyan]")
        res = run_pipeline(source_path=c_file, seed=seed, skip_redteam=False)
        results.append(res)
        console.print("\n" + "=" * 60 + "\n")

    # Evaluation Summary Table
    table = Table(title="Parity Evaluation Benchmark Summary", show_header=True, header_style="bold magenta")
    table.add_column("Module", style="bold")
    table.add_column("Inputs")
    table.add_column("First-Pass BPR")
    table.add_column("Final BPR")
    table.add_column("Held-Out BPR")
    table.add_column("Adversarial")
    table.add_column("Quirks")
    table.add_column("Cost ($)")

    for r in results:
        first_pass_str = f"{r.first_pass_match_rate * 100:.1f}%"
        final_str = f"[bold green]{r.final_match_rate * 100:.1f}%[/bold green]"
        heldout_str = f"[cyan]{r.held_out_match_rate * 100:.1f}%[/cyan]"
        adv_str = f"{r.adversarial_breaks} break(s)"
        quirks_str = f"{len(r.quirks)} flagged"
        cost_str = f"${r.total_cost_usd:.4f}"

        table.add_row(
            r.module_name,
            str(r.total_inputs),
            first_pass_str,
            final_str,
            heldout_str,
            adv_str,
            quirks_str,
            cost_str,
        )

    console.print("\n")
    console.print(table)


@app.command(name="info")
def info_command() -> None:
    """Display Parity configuration, provider status, and active models."""
    console.print(BANNER)
    providers = os.getenv("PARITY_PROVIDERS", "mock").split(",")

    table = Table(title="Parity Configuration & Provider Status", show_header=True, header_style="bold cyan")
    table.add_column("Setting", style="bold")
    table.add_column("Value")
    table.add_column("Status")

    baseten_key = os.getenv("BASETEN_API_KEY", "")
    baseten_model = os.getenv("BASETEN_MODEL_ID", "muse-spark-open-1026")
    modal_key = os.getenv("MODAL_API_KEY", "")
    fireworks_key = os.getenv("FIREWORKS_API_KEY", "")

    table.add_row(
        "Provider Priority Order",
        ", ".join(providers),
        "[green]Active[/green]",
    )
    table.add_row(
        "Baseten (Primary Partner)",
        f"Model: {baseten_model}",
        "[green]Configured[/green]" if baseten_key else "[yellow]Pending Approval (Mock fallback active)[/yellow]",
    )
    table.add_row(
        "Modal (Backup Partner)",
        "OpenAI-compatible endpoint",
        "[green]Configured[/green]" if modal_key else "[yellow]Pending Approval[/yellow]",
    )
    table.add_row(
        "Fireworks (Backup Partner)",
        "OpenAI-compatible endpoint",
        "[green]Configured[/green]" if fireworks_key else "[yellow]Pending Approval[/yellow]",
    )
    table.add_row(
        "Mock Provider",
        "Deterministic local simulator",
        "[bold green]Online (Ready for zero-API demo)[/bold green]",
    )

    console.print(table)
    console.print(
        "\n[dim]Note: Parity works 100% in Demo / Mock mode when API approvals are pending.\n"
        "As soon as you obtain your keys, add them to .env and set PARITY_PROVIDERS=baseten,modal[/dim]\n"
    )


@app.command(name="serve")
def serve_command(
    port: int = typer.Option(8000, "--port", "-p", help="Port for web dashboard"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host address"),
) -> None:
    """Launch the Parity interactive Web Dashboard and API server."""
    console.print(BANNER)
    console.print(f"[bold green]Starting Parity Dashboard on http://{host}:{port}...[/bold green]")
    import uvicorn
    from backend.server import app as web_app
    uvicorn.run(web_app, host=host, port=port)


if __name__ == "__main__":
    app()
