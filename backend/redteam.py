"""Red-team verifier — adversarial agent designed to break equivalence.

Reads both the original legacy C codebase and the migrated Python codebase,
then crafts adversarial inputs specifically targeting subtle language divergences:
- Truncation vs floor division on negative dividends
- Integer boundary wrap-arounds and signed bit overflows
- Month length & calendar leap day edge cases
- Rounding ties & half-way point precision
"""

from __future__ import annotations

import json
from pathlib import Path
from rich.console import Console

from . import (
    AgentRole,
    FunctionSignature,
    Mismatch,
    TestInput,
)
from .llm import LLMClient
from .recorder import record_golden
from .replayer import replay_and_compare

console = Console()


def red_team_check(
    legacy_code: str,
    migrated_code: str,
    signatures: list[FunctionSignature],
    llm: LLMClient,
    run_dir: Path,
    source_path: Path,
    rounds: int = 2,
) -> tuple[int, int, list[TestInput]]:
    """Execute red-team adversarial evaluation.

    Args:
        legacy_code: Source of legacy C module.
        migrated_code: Source of migrated Python module.
        signatures: List of function signatures.
        llm: LLM client.
        run_dir: Directory for test artifacts.
        source_path: Path to C source file.
        rounds: Number of adversarial generation rounds (default: 2).

    Returns:
        (breaks_found, breaks_fixed, list_of_adversarial_inputs)
    """
    console.print("[bold magenta]── Red-Team Adversarial Verifier ──[/bold magenta]")
    redteam_dir = run_dir / "redteam"
    redteam_dir.mkdir(parents=True, exist_ok=True)

    sig_names = [s.name for s in signatures]
    adversarial_inputs: list[TestInput] = []

    for round_num in range(1, rounds + 1):
        prompt = (
            f"You are the Parity Red-Team Verifier Agent. Your goal is to BREAK behavioral equivalence "
            f"between this legacy C code and the migrated Python code.\n\n"
            f"LEGACY C CODE:\n```c\n{legacy_code}\n```\n\n"
            f"MIGRATED PYTHON CODE:\n```python\n{migrated_code}\n```\n\n"
            f"Available functions: {', '.join(sig_names)}\n\n"
            f"Generate adversarial test inputs designed to expose subtle discrepancies like:\n"
            f"- C integer truncation vs Python // floor division on negative numbers\n"
            f"- 32-bit signed integer overflow wrapping (INT_MAX: 2147483647, INT_MIN: -2147483648)\n"
            f"- Rounding half-up ties\n"
            f"- Boundary days and leap years\n\n"
            f"Return JSON:\n"
            f'{{\n  "adversarial_inputs": [\n'
            f'    {{"function": "fn_name", "args": [arg1, arg2], "reason": "why this breaks equivalence"}}\n'
            f"  ]\n}}"
        )

        response = llm.complete(
            messages=[
                {
                    "role": "system",
                    "content": "You are the Parity red team adversarial verifier. You generate harsh edge case inputs designed to uncover behavioral differences between C and Python implementations.",
                },
                {"role": "user", "content": prompt},
            ],
            role=AgentRole.RED_TEAM,
            purpose=f"adversarial edge cases round {round_num}",
            temperature=0.3,
            json_mode=True,
        )

        try:
            data = json.loads(response.content)
            for item in data.get("adversarial_inputs", []):
                fn = item.get("function")
                args = item.get("args", [])
                if fn in sig_names and isinstance(args, list):
                    adversarial_inputs.append(
                        TestInput(function_name=fn, args=args, source="redteam")
                    )
        except Exception:
            pass

    # Ensure baseline fallback adversarial inputs if LLM produced none
    if not adversarial_inputs:
        for sig in signatures:
            if sig.name == "calculate_tier_price":
                adversarial_inputs.append(
                    TestInput(function_name=sig.name, args=[46341, 46341], source="redteam")
                )
                adversarial_inputs.append(
                    TestInput(function_name=sig.name, args=[2147483647, 2], source="redteam")
                )
            elif sig.name == "total_with_tiers":
                adversarial_inputs.append(
                    TestInput(function_name=sig.name, args=[[46341, 100], [46341, 200], 2, 0], source="redteam")
                )
            elif "discount" in sig.name:
                adversarial_inputs.append(
                    TestInput(function_name=sig.name, args=[-500, 1000], source="redteam")
                )
            elif "tax" in sig.name:
                adversarial_inputs.append(
                    TestInput(function_name=sig.name, args=[5, 5000], source="redteam")
                )
            elif "invoice_total" in sig.name:
                adversarial_inputs.append(
                    TestInput(function_name=sig.name, args=[10000, 825, 500], source="redteam")
                )
            elif "prorate" in sig.name:
                adversarial_inputs.append(
                    TestInput(function_name=sig.name, args=[-1000, 1, 15, 2024, 6], source="redteam")
                )
            elif "days_in_month" in sig.name:
                adversarial_inputs.append(
                    TestInput(function_name=sig.name, args=[1900, 2], source="redteam")
                )
                adversarial_inputs.append(
                    TestInput(function_name=sig.name, args=[2000, 2], source="redteam")
                )

    console.print(f"[dim]Testing {len(adversarial_inputs)} adversarial edge cases...[/dim]")

    # Record golden outputs for adversarial inputs
    golden = record_golden(
        source_path=source_path,
        inputs=adversarial_inputs,
        run_dir=redteam_dir,
    )

    # Replay against migrated code
    migrated_path = run_dir / "migrated_final.py"
    if not migrated_path.exists():
        migrated_path = run_dir / "migrated.py"

    match_rate, mismatches = replay_and_compare(
        migrated_path=migrated_path,
        golden=golden,
        run_dir=redteam_dir,
    )

    breaks_found = len(mismatches)
    breaks_fixed = 0  # In current flow, breaks found after convergence

    if breaks_found == 0:
        console.print("[bold green][OK] Red team found 0 equivalence breaks! Migrated code holds under attack.[/bold green]")
    else:
        console.print(f"[bold red][WARN] Red team uncovered {breaks_found} equivalence break(s)![/bold red]")
        for m in mismatches[:3]:
            console.print(f"  [red]• {m.input.function_name}{m.input.args}: C returned {m.expected!r}, Python returned {m.actual!r}[/red]")

    return breaks_found, breaks_fixed, adversarial_inputs
