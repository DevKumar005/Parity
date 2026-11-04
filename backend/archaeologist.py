"""Archaeologist agent — extracts function signatures from legacy C source code.

Reads a C source file, sends it to the LLM for deep analysis, and extracts
function signatures along with notes about suspicious patterns (overflow,
truncation, undefined behavior).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import AgentRole, FunctionSignature
from .llm import LLMClient

console = Console()


# Matches C function definitions like: int foo(int a, char *b)
_FUNC_RE = re.compile(
    r"""
    ^                               # start of line
    \s*                             # optional leading whitespace
    (?P<ret>                        # return type
        (?:(?:static|inline|extern|const|unsigned|signed|long|short)\s+)*
        \w+                         # base type
        \s*\**                      # optional pointer stars
    )
    \s+
    (?P<name>[a-zA-Z_]\w*)          # function name
    \s*\(                           # open paren
    (?P<params>[^)]*)               # parameter list
    \)                              # close paren
    \s*\{                           # opening brace
    """,
    re.MULTILINE | re.VERBOSE,
)

_PARAM_RE = re.compile(
    r"""
    \s*
    (?P<type>
        (?:(?:const|unsigned|signed|long|short|struct|enum)\s+)*
        \w+
        \s*\**
    )
    \s+
    (?P<name>[a-zA-Z_]\w*(?:\[\])?)  # name, optionally with []
    \s*
    """,
    re.VERBOSE,
)


def _regex_extract(source: str) -> list[FunctionSignature]:
    """Fallback: extract function signatures using regex when LLM response is invalid."""
    results: list[FunctionSignature] = []
    for m in _FUNC_RE.finditer(source):
        ret_type = m.group("ret").strip()
        name = m.group("name")
        params_str = m.group("params").strip()

        params: list[tuple[str, str]] = []
        if params_str and params_str != "void":
            for pm in _PARAM_RE.finditer(params_str):
                ptype = pm.group("type").strip()
                pname = pm.group("name").strip()
                params.append((ptype, pname))

        results.append(FunctionSignature(
            name=name,
            return_type=ret_type,
            params=params,
            notes="(extracted via regex fallback)",
        ))
    return results




def analyze_module(source_path: Path, llm: LLMClient) -> list[FunctionSignature]:
    """Analyze a legacy C source file and extract function signatures.

    Args:
        source_path: Path to the C source file.
        llm: LLM client for deep analysis.

    Returns:
        List of extracted function signatures with analysis notes.
    """
    console.rule("[bold cyan]Archaeologist — Analyzing Legacy Module[/]")
    source_code = source_path.read_text(encoding="utf-8", errors="replace")
    module_name = source_path.stem

    console.print(f"  Module: [bold]{module_name}[/]")
    console.print(f"  Lines:  {len(source_code.splitlines())}")

    system_prompt = (
        "You are an archaeologist agent specializing in legacy C code analysis for billing systems. "
        "Your task is to extract every function signature from the given C source file and "
        "identify suspicious patterns that could cause behavioral differences when migrating to Python.\n\n"
        "Look for:\n"
        "- Integer overflow (32-bit wrapping)\n"
        "- Integer division truncation toward zero (differs from Python's floor division)\n"
        "- Signed/unsigned conversion issues\n"
        "- Rounding patterns (half-up vs banker's rounding)\n"
        "- Date/calendar edge cases\n"
        "- Macro or preprocessor tricks\n\n"
        "Respond with a JSON object containing a 'functions' array. Each element has:\n"
        '  - "name": string — function name\n'
        '  - "return_type": string — C return type\n'
        '  - "params": array of [type, name] pairs\n'
        '  - "notes": string — suspicious logic notes\n'
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Analyze this C source file ({module_name}.c):\n\n```c\n{source_code}\n```"},
    ]

    response = llm.complete(
        messages=messages,
        role=AgentRole.ARCHAEOLOGIST,
        purpose=f"Extract function signatures from {module_name}.c",
        json_mode=True,
    )

    signatures: list[FunctionSignature] = []
    try:
        data = json.loads(response.content)
        for fn in data.get("functions", []):
            params = [(p[0], p[1]) for p in fn.get("params", [])]
            signatures.append(FunctionSignature(
                name=fn["name"],
                return_type=fn.get("return_type", "int"),
                params=params,
                notes=fn.get("notes", ""),
            ))
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        console.print(f"  [yellow][WARN] LLM response parse error: {exc}. Falling back to regex.[/]")

    regex_sigs = _regex_extract(source_code)

    if not signatures:
        console.print("  [yellow]Using regex-extracted signatures as fallback.[/]")
        signatures = regex_sigs
    else:
        # Augment: add any regex-found functions that the LLM missed
        llm_names = {s.name for s in signatures}
        for rs in regex_sigs:
            if rs.name not in llm_names:
                console.print(f"  [dim]Adding regex-found function: {rs.name}[/]")
                signatures.append(rs)

    if not signatures:
        console.print("  [red][ERROR] No functions found![/]")
        return signatures

    table = Table(title="Extracted Signatures", show_lines=True)
    table.add_column("Function", style="bold green")
    table.add_column("Return Type", style="cyan")
    table.add_column("Parameters")
    table.add_column("Notes", style="yellow", max_width=60)

    for sig in signatures:
        param_str = ", ".join(f"{t} {n}" for t, n in sig.params)
        table.add_row(sig.name, sig.return_type, param_str, sig.notes or "—")

    console.print(table)
    console.print(f"  [green][OK] Found {len(signatures)} function(s)[/]")

    return signatures
