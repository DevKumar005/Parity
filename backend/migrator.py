"""Migrator agent — translates legacy C code to Python using LLM.

Sends the C source to the LLM with a migration system prompt, extracts
the migrated Python code, saves it to disk, and creates a baseline copy
for diff tracking.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from rich.console import Console

from . import AgentRole, FunctionSignature
from .llm import LLMClient

console = Console()


def _extract_code_from_response(response_text: str) -> str:
    """Extract Python code from an LLM response.

    Handles:
      - JSON with a "migrated_code" field
      - Markdown code blocks (```python ... ```)
      - Raw Python code
    """
    # Try JSON first
    try:
        data = json.loads(response_text)
        if isinstance(data, dict) and "migrated_code" in data:
            return data["migrated_code"].strip()
    except (json.JSONDecodeError, TypeError):
        pass

    # Try markdown code blocks
    pattern = r"```(?:python)?\s*\n(.*?)```"
    matches = re.findall(pattern, response_text, re.DOTALL)
    if matches:
        # Return the longest match (most likely the full migration)
        return max(matches, key=len).strip()

    # Fallback: return the raw response as-is
    return response_text.strip()


def migrate_module(
    source_path: Path,
    signatures: list[FunctionSignature],
    llm: LLMClient,
    run_dir: Path,
) -> tuple[str, Path]:
    """Migrate a legacy C module to Python.

    Args:
        source_path: Path to the legacy C source file.
        signatures: Extracted function signatures with analysis notes.
        llm: LLM client for migration.
        run_dir: Directory for output artifacts.

    Returns:
        Tuple of (migrated_code_string, path_to_migrated_file).
    """
    console.rule("[bold cyan]🔄 Migrator — C → Python Migration[/]")

    source_code = source_path.read_text(encoding="utf-8", errors="replace")
    module_name = source_path.stem

    # Build a signature summary for the prompt
    sig_summary = "\n".join(
        f"  - {s.return_type} {s.name}({', '.join(f'{t} {n}' for t, n in s.params)})"
        + (f"\n    Notes: {s.notes}" if s.notes else "")
        for s in signatures
    )

    system_prompt = (
        "You are a migrator agent that translates legacy C billing code to Python. "
        "Your migration MUST preserve exact behavioral equivalence, including:\n\n"
        "1. **Integer overflow**: C uses 32-bit signed integers that wrap. Use ctypes.c_int32 "
        "   to replicate wrapping behavior in Python.\n"
        "2. **Integer division**: C truncates toward zero (int division). Python's // floors "
        "   toward negative infinity. Use int(a / b) or math.trunc(a / b) for C semantics.\n"
        "3. **Rounding**: C's (a + 5000) / 10000 is half-up rounding via truncation. "
        "   Python's // differs for negative values.\n"
        "4. **Array parameters**: Convert C arrays to Python lists. The n_items/size parameter "
        "   may be omitted if Python can use len().\n"
        "5. **All function signatures must be preserved** (same names, same parameter order).\n\n"
        "Respond with a JSON object containing:\n"
        '  - "migrated_code": string — complete Python module\n'
        '  - "notes": string — migration notes\n'
    )

    user_msg = (
        f"Migrate this C module ({module_name}.c) to Python:\n\n"
        f"```c\n{source_code}\n```\n\n"
        f"Extracted signatures:\n{sig_summary}\n\n"
        f"Requirements:\n"
        f"- Preserve EXACT behavioral equivalence with the C code\n"
        f"- Handle 32-bit integer overflow if present\n"
        f"- Handle C-style truncation-toward-zero division if present\n"
        f"- Keep function names and parameter names identical\n"
        f"- For array parameters (e.g., quantities[], prices[]), accept Python lists\n"
    )

    response = llm.complete(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        role=AgentRole.MIGRATOR,
        purpose=f"Migrate {module_name}.c to Python",
        json_mode=True,
    )

    # Extract the Python code
    migrated_code = _extract_code_from_response(response.content)

    if not migrated_code or migrated_code == "# No migration available":
        console.print("  [red]✗ Migration produced no code![/]")
        migrated_code = f'"""Migration stub for {module_name} — manual migration required."""\n'

    # Save migrated code
    run_dir.mkdir(parents=True, exist_ok=True)
    migrated_path = run_dir / "migrated.py"
    migrated_path.write_text(migrated_code, encoding="utf-8")

    # Save baseline copy for future diffing
    baseline_path = run_dir / "migrated_baseline.py"
    baseline_path.write_text(migrated_code, encoding="utf-8")

    # Display summary
    line_count = len(migrated_code.splitlines())
    console.print(f"  Module:    [bold]{module_name}[/]")
    console.print(f"  Output:    [dim]{migrated_path}[/]")
    console.print(f"  Baseline:  [dim]{baseline_path}[/]")
    console.print(f"  Lines:     {line_count}")
    console.print(f"  [green]✓ Migration complete[/]")

    return migrated_code, migrated_path
