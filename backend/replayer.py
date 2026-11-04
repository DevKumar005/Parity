"""Replayer — replays golden inputs through migrated Python code and compares.

Dynamically imports the migrated module, runs each golden input through the
corresponding function, and performs strict comparison (exact match, no float
tolerance) against the golden output.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from . import GoldenFile, GoldenRecord, Mismatch, TestInput

console = Console()


def _load_migrated_module(migrated_path: Path) -> Any:
    """Dynamically import the migrated Python module."""
    module_name = migrated_path.stem
    spec = importlib.util.spec_from_file_location(module_name, migrated_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec from {migrated_path}")

    module = importlib.util.module_from_spec(spec)
    # Avoid polluting sys.modules across runs
    old_module = sys.modules.pop(module_name, None)
    try:
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    finally:
        # Restore or remove
        if old_module is not None:
            sys.modules[module_name] = old_module
        else:
            sys.modules.pop(module_name, None)

    return module


def _call_function(module: Any, function_name: str, args: list[Any]) -> Any:
    """Call a function in the migrated module with the given arguments.

    Handles array arguments by passing them as Python lists.
    """
    fn = getattr(module, function_name, None)
    if fn is None:
        raise AttributeError(f"Function '{function_name}' not found in migrated module")

    return fn(*args)


def replay_and_compare(
    migrated_path: Path,
    golden: GoldenFile,
    run_dir: Path,
) -> tuple[float, list[Mismatch]]:
    """Replay golden inputs through the migrated module and compare.

    Args:
        migrated_path: Path to the migrated Python file.
        golden: Golden file with expected outputs.
        run_dir: Directory for output artifacts.

    Returns:
        Tuple of (match_rate, list_of_mismatches).
    """
    console.rule("[bold cyan]Replayer — Comparing Against Golden[/]")

    # Load the migrated module
    try:
        module = _load_migrated_module(migrated_path)
        console.print(f"  Loaded: [dim]{migrated_path}[/]")
    except Exception as exc:
        console.print(f"  [red][ERROR] Failed to load migrated module: {exc}[/]")
        # All records are mismatches
        mismatches = [
            Mismatch(
                input=rec.input,
                expected=rec.output,
                actual=f"LOAD_ERROR: {exc}",
            )
            for rec in golden.records
            if rec.error is None
        ]
        return 0.0, mismatches

    # Replay each golden record
    total = 0
    matches = 0
    mismatches: list[Mismatch] = []
    errors: list[str] = []

    for rec in golden.records:
        # Skip records that had errors in golden recording
        if rec.error is not None:
            continue

        total += 1
        try:
            actual = _call_function(module, rec.input.function_name, rec.input.args)
        except Exception as exc:
            actual = f"RUNTIME_ERROR: {type(exc).__name__}: {exc}"
            mismatches.append(Mismatch(
                input=rec.input,
                expected=rec.output,
                actual=actual,
            ))
            if len(errors) < 5:
                errors.append(f"  {rec.input.function_name}({rec.input.args}): {exc}")
            continue

        # Strict comparison — exact match
        if actual == rec.output:
            matches += 1
        else:
            mismatches.append(Mismatch(
                input=rec.input,
                expected=rec.output,
                actual=actual,
            ))

    # Calculate match rate
    match_rate = matches / total if total > 0 else 1.0

    # Display results
    console.print(f"\n  Total records:  {total}")
    console.print(f"  Matches:        {matches}")
    console.print(f"  Mismatches:     {len(mismatches)}")

    if match_rate >= 1.0:
        console.print(f"  Match rate:     [bold green]{match_rate:.1%}[/]")
    elif match_rate >= 0.9:
        console.print(f"  Match rate:     [bold yellow]{match_rate:.1%}[/]")
    else:
        console.print(f"  Match rate:     [bold red]{match_rate:.1%}[/]")

    # Show sample mismatches
    if mismatches:
        table = Table(title="Sample Mismatches (first 10)", show_lines=True)
        table.add_column("Function", style="bold")
        table.add_column("Args")
        table.add_column("Expected", style="green")
        table.add_column("Actual", style="red")

        for mm in mismatches[:10]:
            args_str = json.dumps(mm.input.args)
            if len(args_str) > 50:
                args_str = args_str[:47] + "..."
            table.add_row(
                mm.input.function_name,
                args_str,
                str(mm.expected),
                str(mm.actual),
            )
        console.print(table)

    if errors:
        console.print("\n  [yellow]Runtime errors:[/]")
        for err in errors:
            console.print(f"    {err}")

    # Save mismatch report
    run_dir.mkdir(parents=True, exist_ok=True)
    mismatch_path = run_dir / "mismatches.json"
    mismatch_data = [
        {
            "function_name": mm.input.function_name,
            "args": mm.input.args,
            "expected": mm.expected,
            "actual": mm.actual,
        }
        for mm in mismatches
    ]
    mismatch_path.write_text(json.dumps(mismatch_data, indent=2), encoding="utf-8")

    console.print(f"  [green][OK] Replay complete — {match_rate:.1%} match rate[/]")

    return match_rate, mismatches
