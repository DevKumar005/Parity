"""Report generation for Parity pipeline results.

Renders HTML reports, scorecards, JSON dumps, and terminal summaries.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import (
    Mismatch,
    PipelineResult,
    QuirkEntry,
    QuirkLabel,
    UsageLedgerEntry,
)

console = Console()


_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _rate_color_class(rate: float) -> str:
    """Return a CSS class for the rate value."""
    if rate >= 1.0:
        return "rate-green"
    elif rate >= 0.9:
        return "rate-yellow"
    else:
        return "rate-red"


def _rate_bar_class(rate: float) -> str:
    """Return a CSS bar-fill class for the rate value."""
    if rate >= 1.0:
        return "green"
    elif rate >= 0.9:
        return "yellow"
    else:
        return "red"


def _hex_color_for_rate(rate: float) -> str:
    """Return a hex color for a rate value."""
    if rate >= 1.0:
        return "#22c55e"
    elif rate >= 0.9:
        return "#eab308"
    else:
        return "#ef4444"


def _find_scariest_bug(result: PipelineResult) -> str:
    """Find the most dramatic quirk labeled as a bug."""
    for q in result.quirks:
        if q.label == QuirkLabel.LIKELY_BUG:
            return q.behavior
    if result.remaining_mismatches:
        m = result.remaining_mismatches[0]
        return (
            f"{m.input.function_name}({', '.join(str(a) for a in m.input.args)}) "
            f"expected {m.expected}, got {m.actual}"
        )
    return ""


def _build_timeline(result: PipelineResult) -> list[dict[str, str]]:
    """Build a simplified agent timeline from the pipeline result."""
    stages = [
        {
            "name": "🏛️ Archaeologist",
            "description": f"Extracted {len(result.signatures)} function signature(s) with probe notes",
            "duration": "",
        },
        {
            "name": "🎯 Fuzzer",
            "description": f"Generated {result.total_inputs} test inputs across boundary, model, and mutation strategies",
            "duration": "",
        },
        {
            "name": "🔨 Migrator",
            "description": "Translated C module to Python with semantic preservation",
            "duration": "",
        },
        {
            "name": "📊 First-Pass Comparison",
            "description": f"Matched {result.first_pass_match_rate * 100:.1f}% of golden records on initial migration",
            "duration": "",
        },
    ]
    if result.repair_rounds > 0:
        stages.append({
            "name": f"🔧 Debugger ({result.repair_rounds} round{'s' if result.repair_rounds != 1 else ''})",
            "description": f"Diagnosed mismatches and applied patches → {result.final_match_rate * 100:.1f}% final rate",
            "duration": "",
        })
    if result.adversarial_breaks > 0 or result.adversarial_fixed > 0:
        stages.append({
            "name": "🔴 Red Team",
            "description": f"Found {result.adversarial_breaks} adversarial breaks, fixed {result.adversarial_fixed}",
            "duration": "",
        })
    if result.quirks:
        stages.append({
            "name": "🔍 Quirk Triage",
            "description": f"Labeled {len(result.quirks)} suspicious behaviors with evidence",
            "duration": "",
        })
    stages.append({
        "name": "✅ Held-Out Validation",
        "description": f"Validated on unseen inputs → {result.held_out_match_rate * 100:.1f}% match rate",
        "duration": f"Total wall clock: {result.wall_clock_seconds:.1f}s",
    })
    return stages


def _mismatch_to_dict(m: Mismatch) -> dict[str, Any]:
    """Convert a mismatch to a template-friendly dict."""
    return {
        "function": m.input.function_name,
        "args": ", ".join(str(a) for a in m.input.args),
        "expected": str(m.expected),
        "actual": str(m.actual),
        "diagnosis": m.diagnosis.value if m.diagnosis else "unknown",
    }


def _quirk_to_dict(q: QuirkEntry) -> dict[str, Any]:
    """Convert a quirk to a template-friendly dict."""
    return {
        "behavior": q.behavior,
        "label": q.label.value,
        "evidence": q.evidence,
        "action": q.recommended_action,
    }


def _usage_to_dict(u: UsageLedgerEntry) -> dict[str, Any]:
    """Convert a usage entry to a template-friendly dict."""
    return {
        "provider": u.provider,
        "model": u.model,
        "role": u.role,
        "purpose": u.purpose,
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cost": u.cost_usd,
        "latency": u.latency_ms,
    }


def _safe_asdict(obj: Any) -> Any:
    """Safely convert dataclass to dict, handling non-serializable fields."""
    try:
        d = asdict(obj)
        # Convert Path objects to strings
        for k, v in d.items():
            if isinstance(v, Path):
                d[k] = str(v)
        return d
    except Exception:
        return str(obj)




def generate_report(result: PipelineResult, run_dir: Path) -> Path:
    """Render the full HTML report and write report.json.

    Args:
        result: Complete pipeline result.
        run_dir: Directory to write output files.

    Returns:
        Path to the generated HTML report.
    """
    run_dir.mkdir(parents=True, exist_ok=True)

    # Compute verified count
    total = result.total_inputs or 1
    verified = int(result.final_match_rate * total)

    # Total tokens
    total_in = sum(u.input_tokens for u in result.usage_ledger)
    total_out = sum(u.output_tokens for u in result.usage_ledger)

    # Build template context
    ctx = {
        "module_name": result.module_name,
        "verified_count": verified,
        "total_inputs": result.total_inputs,
        "first_pass_rate": result.first_pass_match_rate,
        "final_rate": result.final_match_rate,
        "held_out_rate": result.held_out_match_rate,
        "first_pass_color": _rate_color_class(result.first_pass_match_rate),
        "final_color": _rate_color_class(result.final_match_rate),
        "held_out_color": _rate_color_class(result.held_out_match_rate),
        "first_pass_bar": _rate_bar_class(result.first_pass_match_rate),
        "final_bar": _rate_bar_class(result.final_match_rate),
        "held_out_bar": _rate_bar_class(result.held_out_match_rate),
        "adversarial_breaks": result.adversarial_breaks,
        "adversarial_fixed": result.adversarial_fixed,
        "repair_rounds": result.repair_rounds,
        "timeline": _build_timeline(result),
        "remaining_mismatches": [_mismatch_to_dict(m) for m in result.remaining_mismatches],
        "quirks": [_quirk_to_dict(q) for q in result.quirks],
        "behavior_contract": result.behavior_contract,
        "golden_hash": result.golden_hash or "n/a",
        "wall_clock_seconds": result.wall_clock_seconds,
        "total_cost": result.total_cost_usd,
        "seeds": result.seeds,
        "usage_ledger": [_usage_to_dict(u) for u in result.usage_ledger],
        "total_tokens_in": total_in,
        "total_tokens_out": total_out,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
    }

    # Render HTML
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )
    template = env.get_template("report.html")
    html = template.render(**ctx)

    html_path = run_dir / "report.html"
    html_path.write_text(html, encoding="utf-8")

    # Write JSON
    json_data = {
        "module_name": result.module_name,
        "first_pass_match_rate": result.first_pass_match_rate,
        "final_match_rate": result.final_match_rate,
        "held_out_match_rate": result.held_out_match_rate,
        "adversarial_breaks": result.adversarial_breaks,
        "adversarial_fixed": result.adversarial_fixed,
        "repair_rounds": result.repair_rounds,
        "total_inputs": result.total_inputs,
        "golden_hash": result.golden_hash,
        "wall_clock_seconds": result.wall_clock_seconds,
        "total_cost_usd": result.total_cost_usd,
        "signatures": [_safe_asdict(s) for s in result.signatures],
        "remaining_mismatches": [_safe_asdict(m) for m in result.remaining_mismatches],
        "patch_history": [_safe_asdict(p) for p in result.patch_history],
        "quirks": [_safe_asdict(q) for q in result.quirks],
        "behavior_contract": result.behavior_contract,
        "usage_ledger": [_safe_asdict(u) for u in result.usage_ledger],
        "seeds": result.seeds,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    json_path = run_dir / "report.json"
    json_path.write_text(json.dumps(json_data, indent=2, default=str), encoding="utf-8")

    return html_path


def generate_scorecard(result: PipelineResult, run_dir: Path) -> Path:
    """Generate a screenshot-worthy scorecard HTML file.

    Args:
        result: Complete pipeline result.
        run_dir: Directory to write output files.

    Returns:
        Path to the generated scorecard HTML.
    """
    run_dir.mkdir(parents=True, exist_ok=True)

    score = result.final_match_rate
    score_color = _hex_color_for_rate(score)
    glow_color = score_color
    first_pass_color = _hex_color_for_rate(result.first_pass_match_rate)
    final_color = _hex_color_for_rate(result.final_match_rate)
    scariest_bug = _find_scariest_bug(result)

    ctx = {
        "module_name": result.module_name,
        "score": score,
        "score_color": score_color,
        "glow_color": glow_color,
        "first_pass_rate": result.first_pass_match_rate,
        "final_rate": result.final_match_rate,
        "first_pass_color": first_pass_color,
        "final_color": final_color,
        "scariest_bug": scariest_bug,
    }

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )
    template = env.get_template("scorecard.html")
    html = template.render(**ctx)

    scorecard_path = run_dir / "scorecard.html"
    scorecard_path.write_text(html, encoding="utf-8")

    return scorecard_path


def print_terminal_summary(result: PipelineResult) -> None:
    """Print a rich-formatted terminal summary of pipeline results.

    Args:
        result: Complete pipeline result.
    """
    banner = Text()
    banner.append("⚖️  Parity Results", style="bold bright_white")
    banner.append(f" — {result.module_name}", style="bold magenta")
    console.print(Panel(banner, border_style="blue", padding=(0, 2)))
    console.print()

    rate_table = Table(title="Match Rates", show_header=True, header_style="bold cyan")
    rate_table.add_column("Stage", style="bold")
    rate_table.add_column("Rate", justify="right")
    rate_table.add_column("Bar", min_width=30)

    def _rate_style(r: float) -> str:
        if r >= 1.0:
            return "bold green"
        elif r >= 0.9:
            return "bold yellow"
        return "bold red"

    def _rate_bar(r: float) -> str:
        filled = int(r * 30)
        return "█" * filled + "░" * (30 - filled)

    for name, rate in [
        ("First-Pass", result.first_pass_match_rate),
        ("Final", result.final_match_rate),
        ("Held-Out", result.held_out_match_rate),
    ]:
        style = _rate_style(rate)
        rate_table.add_row(
            name,
            Text(f"{rate * 100:.1f}%", style=style),
            Text(_rate_bar(rate), style=style),
        )

    console.print(rate_table)
    console.print()

    console.print(f"  Total inputs: [cyan]{result.total_inputs}[/]  |  "
                  f"Debug rounds: [cyan]{result.repair_rounds}[/]  |  "
                  f"Adversarial breaks: [{'red' if result.adversarial_breaks else 'green'}]"
                  f"{result.adversarial_breaks}[/]  |  "
                  f"Wall clock: [cyan]{result.wall_clock_seconds:.1f}s[/]")
    console.print()

    if result.quirks:
        quirk_table = Table(title="Quirk Triage", show_header=True, header_style="bold cyan")
        quirk_table.add_column("Behavior", max_width=50)
        quirk_table.add_column("Label", justify="center")
        quirk_table.add_column("Action", max_width=40)

        label_styles = {
            QuirkLabel.LIKELY_BUG: ("🐛 LIKELY BUG", "bold red"),
            QuirkLabel.LIKELY_INTENTIONAL: ("✅ INTENTIONAL", "bold green"),
            QuirkLabel.UNCLEAR: ("❓ UNCLEAR", "bold yellow"),
        }

        for q in result.quirks:
            label_text, label_style = label_styles.get(
                q.label, ("❓ UNCLEAR", "bold yellow")
            )
            quirk_table.add_row(
                q.behavior,
                Text(label_text, style=label_style),
                q.recommended_action,
            )

        console.print(quirk_table)
        console.print()

    if result.usage_ledger:
        usage_table = Table(title="Usage Ledger", show_header=True, header_style="bold cyan")
        usage_table.add_column("Provider")
        usage_table.add_column("Role")
        usage_table.add_column("Purpose", max_width=35)
        usage_table.add_column("Tokens", justify="right")
        usage_table.add_column("Cost", justify="right")
        usage_table.add_column("Latency", justify="right")

        total_cost = 0.0
        total_in = 0
        total_out = 0

        for u in result.usage_ledger:
            total_cost += u.cost_usd
            total_in += u.input_tokens
            total_out += u.output_tokens
            usage_table.add_row(
                u.provider,
                u.role,
                u.purpose,
                f"{u.input_tokens}/{u.output_tokens}",
                f"${u.cost_usd:.4f}",
                f"{u.latency_ms:.0f}ms",
            )

        usage_table.add_row(
            "[bold]TOTAL[/]", "", "",
            f"[bold]{total_in}/{total_out}[/]",
            f"[bold]${total_cost:.4f}[/]",
            "",
            style="on dark_blue",
        )

        console.print(usage_table)
        console.print()

    if result.final_match_rate >= 1.0:
        console.print(Panel(
            "✅ [bold green]PERFECT MATCH[/] — Migration verified on all recorded behaviors",
            border_style="green",
        ))
    elif result.final_match_rate >= 0.9:
        console.print(Panel(
            f"⚠️  [bold yellow]NEAR MATCH[/] — {result.final_match_rate * 100:.1f}% verified, "
            f"{len(result.remaining_mismatches)} difference(s) remain",
            border_style="yellow",
        ))
    else:
        console.print(Panel(
            f"❌ [bold red]SIGNIFICANT DIFFERENCES[/] — {result.final_match_rate * 100:.1f}% verified, "
            f"{len(result.remaining_mismatches)} difference(s) remain",
            border_style="red",
        ))

    console.print()
    console.print("[dim]Built with Muse Spark Open[/]")
