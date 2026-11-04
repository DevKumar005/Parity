"""Pipeline orchestrator for Parity.

Executes the complete 10-stage verification workflow:
1. Archaeologist: reads legacy C code, extracts function signatures & probe notes
2. Fuzzer: builds boundary seeds + model edge cases + mutations (300+ inputs/func)
3. Recorder: compiles driver with defined overflow, executes, hashes immutable golden file
4. Migrator: translates module to Python 3, preserves signatures, stores baseline
5. Replayer: replays golden inputs against baseline with strict comparison
6. Debugger: shrinks, clusters, diagnoses, monotonic repair with no-regression check
7. Held-out check: fresh seed + fresh model edge cases replayed against final code
8. Red-team verifier: adversarial input generation targeting language divergences
9. Quirk triage & behavior contract: labels bugs vs intentional behaviors with evidence
10. Reporter: compiles HTML report, JSON export, and shareable Parity Score card
"""

from __future__ import annotations

import datetime
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from . import (
    GoldenFile,
    PipelineResult,
)
from .archaeologist import analyze_module
from .debugger import repair_loop
from .fuzzer import generate_inputs
from .heldout import held_out_check
from .llm import LLMClient
from .migrator import migrate_module
from .quirks import triage_quirks
from .recorder import record_golden
from .redteam import red_team_check
from .replayer import replay_and_compare
from .report import generate_report, generate_scorecard, print_terminal_summary

console = Console()


def run_pipeline(
    source_path: Path,
    run_dir: Path | None = None,
    seed: int = 42,
    skip_redteam: bool = False,
) -> PipelineResult:
    """Run the complete end-to-end Parity autonomous verification pipeline.

    Args:
        source_path: Path to the legacy C module.
        run_dir: Directory for storing output artifacts (default: runs/<timestamp>_<module>).
        seed: Random seed for deterministic fuzzing (default: 42).
        skip_redteam: If True, skips stage 8 red-team check.

    Returns:
        Complete PipelineResult dataclass instance.
    """
    start_time = time.time()
    source_path = source_path.resolve()
    module_name = source_path.stem

    if run_dir is None:
        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = Path.cwd() / "runs" / f"{timestamp_str}_{module_name}"
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    console.print(
        Panel.fit(
            f"[bold cyan]PARITY VERIFICATION PIPELINE[/bold cyan]\n"
            f"[white]Target: {source_path.name}[/white]\n"
            f"[dim]Artifacts: {run_dir}[/dim]",
            border_style="cyan",
        )
    )

    legacy_code = source_path.read_text(encoding="utf-8")
    llm = LLMClient(run_dir=run_dir)

    # Stage 1: Archaeologist
    console.print("\n[bold]Stage 1: Archaeologist Agent[/bold]")
    signatures = analyze_module(source_path=source_path, llm=llm)

    # Stage 2: Fuzzer
    console.print("\n[bold]Stage 2: Fuzzer (Boundary + Edge-case generation)[/bold]")
    inputs = generate_inputs(
        signatures=signatures,
        source_code=legacy_code,
        llm=llm,
        seed=seed,
    )
    console.print(f"[green][OK] Total test inputs generated: {len(inputs)}[/green]")

    # Stage 3: Recorder
    console.print("\n[bold]Stage 3: Recorder (Compile, Execute & Hash Golden Records)[/bold]")
    golden = record_golden(
        source_path=source_path,
        inputs=inputs,
        run_dir=run_dir,
    )
    console.print(f"[bold green][OK] Golden file created: {len(golden.records)} records[/bold green]")
    console.print(f"[dim]Immutable SHA-256 Hash: {golden.hash}[/dim]")

    # Stage 4: Migrator
    console.print("\n[bold]Stage 4: Migrator (C → Python Translation)[/bold]")
    migrated_code, migrated_path = migrate_module(
        source_path=source_path,
        signatures=signatures,
        llm=llm,
        run_dir=run_dir,
    )

    # Stage 5: Replayer (First-pass evaluation)
    console.print("\n[bold]Stage 5: Replayer (First-pass baseline evaluation)[/bold]")
    first_pass_rate, first_pass_mismatches = replay_and_compare(
        migrated_path=migrated_path,
        golden=golden,
        run_dir=run_dir,
    )
    console.print(
        f"[yellow]First-pass Behavioral Preservation Rate (BPR): {first_pass_rate * 100:.1f}% "
        f"({len(first_pass_mismatches)} mismatches)[/yellow]"
    )

    # Stage 6: Debugger (Monotonic repair loop)
    console.print("\n[bold]Stage 6: Debugger (Monotonic repair loop with no-regression check)[/bold]")
    final_code, final_rate, patch_history, remaining_mismatches = repair_loop(
        migrated_path=migrated_path,
        golden=golden,
        mismatches=first_pass_mismatches,
        llm=llm,
        run_dir=run_dir,
        max_rounds=6,
    )

    # Stage 7: Held-out Generalization Check
    console.print("\n[bold]Stage 7: Held-out Generalization Check (Unseen inputs)[/bold]")
    held_out_rate, held_out_matches, held_out_total = held_out_check(
        migrated_path=migrated_path,
        source_path=source_path,
        signatures=signatures,
        llm=llm,
        run_dir=run_dir,
        seed=seed + 9957,
    )

    # Stage 8: Red-Team Adversarial Verifier
    breaks_found = 0
    breaks_fixed = 0
    if not skip_redteam:
        console.print("\n[bold]Stage 8: Red-Team Adversarial Verifier[/bold]")
        breaks_found, breaks_fixed, _ = red_team_check(
            legacy_code=legacy_code,
            migrated_code=final_code,
            signatures=signatures,
            llm=llm,
            run_dir=run_dir,
            source_path=source_path,
            rounds=2,
        )

    # Stage 9: Quirk Triage & Behavior Contract
    console.print("\n[bold]Stage 9: Quirk Triage & Behavior Contract[/bold]")
    quirks, contract = triage_quirks(
        legacy_code=legacy_code,
        migrated_code=final_code,
        mismatches=remaining_mismatches,
        golden=golden,
        llm=llm,
    )

    wall_clock = time.time() - start_time

    # Compile result
    result = PipelineResult(
        module_name=module_name,
        signatures=signatures,
        total_inputs=len(inputs),
        golden_hash=golden.hash,
        first_pass_match_rate=first_pass_rate,
        final_match_rate=final_rate,
        held_out_match_rate=held_out_rate,
        adversarial_breaks=breaks_found,
        adversarial_fixed=breaks_fixed,
        repair_rounds=len(patch_history),
        mismatches=first_pass_mismatches,
        remaining_mismatches=remaining_mismatches,
        patch_history=patch_history,
        quirks=quirks,
        behavior_contract=contract,
        usage_ledger=llm.ledger,
        wall_clock_seconds=wall_clock,
        total_cost_usd=llm.total_cost,
        migrated_code=final_code,
        legacy_code=legacy_code,
        run_dir=run_dir,
        seeds={"fuzzer": seed, "heldout": seed + 9957},
    )

    # Stage 10: Reporter
    console.print("\n[bold]Stage 10: Reporter (HTML, JSON & Parity Score Card)[/bold]")
    report_path = generate_report(result, run_dir)
    scorecard_path = generate_scorecard(result, run_dir)
    print_terminal_summary(result)

    console.print(
        f"\n[bold green][OK] Parity run complete in {wall_clock:.1f}s![/bold green]\n"
        f"  [cyan]Report:[/cyan] file://{report_path}\n"
        f"  [cyan]Scorecard:[/cyan] file://{scorecard_path}\n"
    )

    return result
