"""Held-out check — tests the final migrated code on fresh, unseen inputs.

Generates fresh deterministic seeds + fresh model edge cases with an independent
seed that was never seen during migration or debugging. Runs both legacy C and
migrated Python, and returns the held-out Behavioral Preservation Rate (BPR).
"""

from __future__ import annotations

from pathlib import Path
from rich.console import Console

from . import FunctionSignature, PipelineResult
from .fuzzer import generate_inputs
from .llm import LLMClient
from .recorder import record_golden
from .replayer import replay_and_compare

console = Console()


def held_out_check(
    migrated_path: Path,
    source_path: Path,
    signatures: list[FunctionSignature],
    llm: LLMClient,
    run_dir: Path,
    seed: int = 9999,
) -> tuple[float, int, int]:
    """Execute the held-out generalization test.

    Args:
        migrated_path: Path to the finalized migrated Python file.
        source_path: Path to original legacy C source file.
        signatures: Extracted function signatures.
        llm: LLM client.
        run_dir: Directory for outputs.
        seed: Distinct seed for fresh input generation (default: 9999).

    Returns:
        (held_out_match_rate, matches_count, total_inputs)
    """
    console.print(f"[bold cyan]── Held-out Generalization Check (Seed: {seed}) ──[/bold cyan]")
    heldout_dir = run_dir / "heldout"
    heldout_dir.mkdir(parents=True, exist_ok=True)

    source_code = source_path.read_text(encoding="utf-8")

    # 1. Generate fresh inputs
    fresh_inputs = generate_inputs(
        signatures=signatures,
        source_code=source_code,
        llm=llm,
        seed=seed,
    )

    console.print(f"[dim]Generated {len(fresh_inputs)} fresh held-out inputs[/dim]")

    # 2. Record golden expectations from original C implementation
    golden = record_golden(
        source_path=source_path,
        inputs=fresh_inputs,
        run_dir=heldout_dir,
    )

    # 3. Replay against migrated Python code
    match_rate, mismatches = replay_and_compare(
        migrated_path=migrated_path,
        golden=golden,
        run_dir=heldout_dir,
    )

    total = len(golden.records)
    matches = total - len(mismatches)

    color = "green" if match_rate >= 1.0 else ("yellow" if match_rate >= 0.9 else "red")
    console.print(
        f"[{color}]Held-out BPR: {match_rate * 100:.1f}% ({matches}/{total} matched)[/{color}]"
    )

    return match_rate, matches, total

