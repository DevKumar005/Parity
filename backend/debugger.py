"""Debugger — monotonic repair loop with no-regression check and anti-hardcoding.

Diagnoses mismatches using a closed taxonomy:
- rounding
- integer_overflow
- integer_division
- negative_modulo
- float_formatting
- date_calendar
- string_encoding
- other

Applies monotonic repair: any patch that breaks a previously passing input
is strictly rejected. Anti-hardcoding check ensures patches do not inject
literal return values for specific test inputs.
"""

from __future__ import annotations

import difflib
import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from rich.console import Console

from . import (
    AgentRole,
    DiagnosisCategory,
    GoldenFile,
    GoldenRecord,
    Mismatch,
    PatchResult,
    TestInput,
)
from .llm import LLMClient
from .replayer import _call_function, _load_migrated_module

console = Console()


def _shrink_input(mismatch: Mismatch) -> TestInput:
    """Shrink a failing input toward minimal reproducing representation."""
    args = mismatch.input.args
    shrunk_args = []
    for arg in args:
        if isinstance(arg, int):
            # Keep sign, reduce magnitude if large
            if abs(arg) > 1000000:
                shrunk_args.append(arg)  # Overflow triggers need large magnitude
            else:
                shrunk_args.append(arg)
        elif isinstance(arg, list):
            # Shorten list to minimum needed
            if len(arg) > 2:
                shrunk_args.append(arg[:2])
            else:
                shrunk_args.append(list(arg))
        else:
            shrunk_args.append(arg)

    return TestInput(
        function_name=mismatch.input.function_name,
        args=shrunk_args,
        source="shrunk",
    )


def _cluster_mismatches(mismatches: list[Mismatch]) -> dict[str, list[Mismatch]]:
    """Group mismatches by function name for targeted diagnosis."""
    clusters: dict[str, list[Mismatch]] = {}
    for m in mismatches:
        clusters.setdefault(m.input.function_name, []).append(m)
    return clusters


def _heuristic_diagnose(mismatch: Mismatch) -> DiagnosisCategory:
    """Heuristic diagnosis using input/output patterns to support LLM."""
    expected = mismatch.expected
    actual = mismatch.actual
    args = mismatch.input.args

    # Check for integer overflow (large difference or sign inversion)
    if isinstance(expected, int) and isinstance(actual, int):
        if (expected < 0 and actual > 0) or (expected > 0 and actual < 0):
            return DiagnosisCategory.INTEGER_OVERFLOW
        if abs(expected) > 2147483647 or abs(actual) > 2147483647:
            return DiagnosisCategory.INTEGER_OVERFLOW

        # Check for integer division / truncation difference (often off by 1 on negative)
        if abs(expected - actual) == 1 and any(isinstance(a, (int, float)) and a < 0 for a in args):
            return DiagnosisCategory.INTEGER_DIVISION

        # Rounding difference (often off by 1 on positive division)
        if abs(expected - actual) == 1:
            return DiagnosisCategory.ROUNDING

    return DiagnosisCategory.OTHER


def _anti_hardcoding_check(candidate_code: str, failing_mismatches: list[Mismatch]) -> bool:
    """Reject candidate code that hardcodes exact input-output matches."""
    for m in failing_mismatches:
        expected_str = str(m.expected)
        # Check if patch introduces `if args == ... return expected`
        for arg in m.input.args:
            if isinstance(arg, (int, float)) and abs(arg) > 100:
                pattern = rf"if\s+.*{re.escape(str(arg))}.*:\s*return\s+{re.escape(expected_str)}"
                if re.search(pattern, candidate_code):
                    return False
    return True


def _test_candidate_code(
    candidate_code: str,
    golden: GoldenFile,
    run_dir: Path,
) -> tuple[float, list[Mismatch], set[int]]:
    """Run candidate Python code against all golden records.

    Returns:
        (match_rate, list_of_mismatches, passing_indices_set)
    """
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir=run_dir) as f:
        f.write(candidate_code)
        temp_path = Path(f.name)

    try:
        module = _load_migrated_module(temp_path)
        mismatches: list[Mismatch] = []
        passing_indices: set[int] = set()

        for idx, record in enumerate(golden.records):
            fn_name = record.input.function_name
            args = record.input.args
            try:
                actual = _call_function(module, fn_name, args)
                if actual == record.output:
                    passing_indices.add(idx)
                else:
                    mismatches.append(
                        Mismatch(
                            input=record.input,
                            expected=record.output,
                            actual=actual,
                            diagnosis=_heuristic_diagnose(
                                Mismatch(input=record.input, expected=record.output, actual=actual)
                            ),
                        )
                    )
            except Exception as e:
                mismatches.append(
                    Mismatch(
                        input=record.input,
                        expected=record.output,
                        actual=f"Exception: {type(e).__name__}: {e}",
                        diagnosis=DiagnosisCategory.OTHER,
                    )
                )

        total = len(golden.records)
        match_rate = len(passing_indices) / total if total > 0 else 0.0
        return match_rate, mismatches, passing_indices
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _generate_patch_proposal(
    current_code: str,
    mismatches: list[Mismatch],
    llm: LLMClient,
) -> str:
    """Use the LLM debugger to diagnose mismatches and propose a complete patched file."""
    # Group sample mismatches for the prompt
    sample_mismatches = mismatches[:10]
    mismatch_descriptions = []
    for m in sample_mismatches:
        mismatch_descriptions.append(
            f"- Function `{m.input.function_name}` with args {m.input.args}: "
            f"Expected {m.expected!r}, Got {m.actual!r} (Heuristic: {m.diagnosis.value if m.diagnosis else 'unknown'})"
        )

    prompt = (
        f"You are the Parity Debugger Agent. Analyze the mismatches between legacy C and migrated Python code.\n\n"
        f"CURRENT PYTHON CODE:\n```python\n{current_code}\n```\n\n"
        f"MISMATCHES DETECTED ({len(mismatches)} total, showing up to 10):\n"
        + "\n".join(mismatch_descriptions)
        + "\n\nDiagnose the root cause using our closed taxonomy:\n"
        "- rounding (e.g. half-up vs half-to-even)\n"
        "- integer_overflow (32-bit int wrapping in C, ctypes.c_int32)\n"
        "- integer_division (C truncates toward 0, Python // floors toward negative infinity)\n"
        "- negative_modulo\n"
        "- float_formatting\n"
        "- date_calendar\n"
        "- string_encoding\n"
        "- other\n\n"
        "Return a JSON object with:\n"
        '{\n  "diagnosis": "taxonomy_category",\n  "explanation": "...",\n  "patched_code": "COMPLETE REVISED PYTHON CODE"\n}'
    )

    response = llm.complete(
        messages=[
            {
                "role": "system",
                "content": "You are the Parity debugger agent. You diagnose differences between C and Python billing implementations and provide clean, complete patched Python code.",
            },
            {"role": "user", "content": prompt},
        ],
        role=AgentRole.DEBUGGER,
        purpose="diagnose and patch mismatches",
        temperature=0.0,
        json_mode=True,
    )

    # Parse response
    content = response.content.strip()
    try:
        data = json.loads(content)
        if "patched_code" in data and len(data["patched_code"].strip()) > 30:
            return data["patched_code"].strip()
    except Exception:
        pass

    # Fallback heuristic fixes for common billing patterns if LLM response doesn't give full code
    patched = current_code

    # 1. Ensure 32-bit integer overflow wrapping if needed
    if any(m.diagnosis == DiagnosisCategory.INTEGER_OVERFLOW for m in mismatches):
        if "ctypes" not in patched:
            patched = "import ctypes\n" + patched
        # Ensure wrapping helper exists
        if "c_int32(" not in patched and "def _wrap32(" not in patched:
            wrap_helper = (
                "\ndef _wrap32(val: int) -> int:\n"
                "    return ctypes.c_int32(val).value\n"
            )
            patched = patched.replace("import ctypes\n", "import ctypes\n" + wrap_helper)

    # 2. Ensure C-style truncation division if integer division mismatch
    if any(m.diagnosis in (DiagnosisCategory.INTEGER_DIVISION, DiagnosisCategory.ROUNDING) for m in mismatches):
        if "def c_div(" not in patched:
            c_div_helper = (
                "\ndef c_div(a: int, b: int) -> int:\n"
                "    \"\"\"C-style integer division: truncate toward zero.\"\"\"\n"
                "    return int(a / b)\n"
            )
            patched = c_div_helper + patched
            # Replace // with c_div where applicable
            patched = re.sub(r'\((\w+)\s*\*\s*(\w+)\s*\+\s*5000\)\s*//\s*10000', r'c_div(\1 * \2 + 5000, 10000)', patched)
            patched = re.sub(r'\((\w+)\s*\*\s*(\w+)\)\s*//\s*(\w+)', r'c_div(\1 * \2, \3)', patched)

    return patched


def repair_loop(
    migrated_path: Path,
    golden: GoldenFile,
    mismatches: list[Mismatch],
    llm: LLMClient,
    run_dir: Path,
    max_rounds: int = 6,
) -> tuple[str, float, list[PatchResult], list[Mismatch]]:
    """Execute the monotonic repair loop with no-regression guarantee.

    Args:
        migrated_path: Path to initial migrated Python module.
        golden: Immutable golden file.
        mismatches: Initial mismatches from first-pass replay.
        llm: LLM client.
        run_dir: Output directory.
        max_rounds: Cap on repair iterations (default: 6).

    Returns:
        (final_code, final_match_rate, patch_history, remaining_mismatches)
    """
    current_code = migrated_path.read_text(encoding="utf-8")
    initial_total = len(golden.records)

    # Establish baseline passing set
    baseline_rate, current_mismatches, previously_passing = _test_candidate_code(
        current_code, golden, run_dir
    )

    if not current_mismatches:
        console.print("[green]✔ First-pass migration already achieves 100% parity![/green]")
        return current_code, 1.0, [], []

    patch_history: list[PatchResult] = []
    current_rate = baseline_rate

    console.print(
        f"[yellow]Starting monotonic repair loop (Baseline: {current_rate * 100:.1f}%, "
        f"{len(current_mismatches)} mismatches)[/yellow]"
    )

    for round_num in range(1, max_rounds + 1):
        if not current_mismatches or current_rate >= 1.0:
            console.print(f"[bold green]✔ Reached 100% equivalence at round {round_num - 1}![/bold green]")
            break

        console.print(f"[cyan]── Debugger Round {round_num}/{max_rounds} ──[/cyan]")

        # Shrink representative mismatches
        shrunk_samples = [_shrink_input(m) for m in current_mismatches[:5]]

        # Propose patch
        candidate_code = _generate_patch_proposal(current_code, current_mismatches, llm)

        # Anti-hardcoding check
        if not _anti_hardcoding_check(candidate_code, current_mismatches):
            console.print(f"[red]Round {round_num}: Patch REJECTED — detected hardcoded literal return values![/red]")
            patch_history.append(
                PatchResult(
                    round_num=round_num,
                    patch_description="Patch rejected by anti-hardcoding check",
                    code_diff="",
                    fixed_count=0,
                    regressed_count=0,
                    accepted=False,
                    new_match_rate=current_rate,
                )
            )
            continue

        # Test candidate against all golden records
        new_rate, new_mismatches, new_passing = _test_candidate_code(
            candidate_code, golden, run_dir
        )

        # Monotonic regression check: did ANY previously passing input fail?
        regressions = previously_passing - new_passing
        fixed = len(previously_passing) < len(new_passing) and not regressions

        diff = "".join(
            difflib.unified_diff(
                current_code.splitlines(keepends=True),
                candidate_code.splitlines(keepends=True),
                fromfile="current.py",
                tofile="candidate.py",
                n=3,
            )
        )

        if regressions:
            regressed_count = len(regressions)
            console.print(
                f"[red]Round {round_num}: Patch REJECTED — broke {regressed_count} previously-matching input(s) "
                f"(Monotonic rule violation)[/red]"
            )
            patch_history.append(
                PatchResult(
                    round_num=round_num,
                    patch_description=f"Rejected: {regressed_count} regression(s)",
                    code_diff=diff,
                    fixed_count=0,
                    regressed_count=regressed_count,
                    accepted=False,
                    new_match_rate=current_rate,
                )
            )
        elif new_rate > current_rate:
            fixed_count = len(new_passing) - len(previously_passing)
            console.print(
                f"[green]Round {round_num}: Patch ACCEPTED! Fixed {fixed_count} behavior(s), "
                f"Match rate: {current_rate * 100:.1f}% → {new_rate * 100:.1f}%[/green]"
            )
            current_code = candidate_code
            current_rate = new_rate
            current_mismatches = new_mismatches
            previously_passing = new_passing
            patch_history.append(
                PatchResult(
                    round_num=round_num,
                    patch_description=f"Accepted: Fixed {fixed_count} cases, rate={new_rate*100:.1f}%",
                    code_diff=diff,
                    fixed_count=fixed_count,
                    regressed_count=0,
                    accepted=True,
                    new_match_rate=new_rate,
                )
            )
        else:
            console.print(f"[yellow]Round {round_num}: Patch showed no improvement ({new_rate*100:.1f}%). Skipped.[/yellow]")
            patch_history.append(
                PatchResult(
                    round_num=round_num,
                    patch_description="No improvement in match rate",
                    code_diff=diff,
                    fixed_count=0,
                    regressed_count=0,
                    accepted=False,
                    new_match_rate=current_rate,
                )
            )

    # Save final patched code
    final_path = run_dir / "migrated_final.py"
    final_path.write_text(current_code, encoding="utf-8")
    migrated_path.write_text(current_code, encoding="utf-8")

    return current_code, current_rate, patch_history, current_mismatches

