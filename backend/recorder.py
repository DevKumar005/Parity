"""Recorder — compiles legacy C code and records golden output for all test inputs.

Generates a C test driver that calls each function with each input, printing
results as JSON lines. Compiles with clang, runs it in a subprocess, and
parses the output into GoldenRecord objects. The resulting golden file is
immutable after creation.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import textwrap
import time
from pathlib import Path
from typing import Any

from rich.console import Console

from . import FunctionSignature, GoldenFile, GoldenRecord, TestInput

console = Console()




def _c_literal(value: Any) -> str:
    """Convert a Python value to a C literal string."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        # Handle values outside 32-bit range by casting
        if value > 2_147_483_647 or value < -2_147_483_648:
            return f"(int){value}LL"
        return str(value)
    if isinstance(value, float):
        return f"{value}"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return str(value)


def _generate_driver(
    source_path: Path,
    inputs: list[TestInput],
    signatures: list[FunctionSignature],
    run_dir: Path,
) -> Path:
    """Generate a C test driver that exercises all inputs and prints JSON output."""
    sig_map = {s.name: s for s in signatures}
    module_name = source_path.stem

    # Build the driver source
    lines: list[str] = []
    lines.append('#include <stdio.h>')
    lines.append('#include <stdlib.h>')
    lines.append('#include <string.h>')
    lines.append('')
    # Include the legacy module directly
    lines.append(f'#include "{source_path.resolve()}"')
    lines.append('')
    lines.append('int main(void) {')

    for idx, inp in enumerate(inputs):
        sig = sig_map.get(inp.function_name)
        if sig is None:
            continue

        # Build declarations and call
        call_args: list[str] = []
        declarations: list[str] = []

        arg_idx = 0
        for pi, (ptype, pname) in enumerate(sig.params):
            is_array = "[]" in pname or "[]" in ptype or "*" in ptype
            if is_array:
                if arg_idx < len(inp.args) and isinstance(inp.args[arg_idx], list):
                    arr = inp.args[arg_idx]
                elif arg_idx < len(inp.args):
                    arr = [inp.args[arg_idx]]
                else:
                    arr = [0]
                arr_var = f"arr_{idx}_{pi}"
                base_type = ptype.replace("*", "").replace("[]", "").strip()
                if not base_type:
                    base_type = "int"
                init_vals = ", ".join(_c_literal(v) for v in arr) if arr else "0"
                declarations.append(f"    {base_type} {arr_var}[] = {{{init_vals}}};")
                call_args.append(arr_var)
                arg_idx += 1
            elif arg_idx < len(inp.args):
                call_args.append(_c_literal(inp.args[arg_idx]))
                arg_idx += 1
            else:
                call_args.append("0")

        lines.append(f"    /* Test {idx}: {inp.function_name} */")
        lines.append("    {")
        for decl in declarations:
            lines.append(decl)

        call_str = f"{inp.function_name}({', '.join(call_args)})"

        # Determine format specifier
        ret_type = sig.return_type.strip()
        if ret_type in ("long long", "int64_t"):
            fmt = "%lld"
            cast = "(long long)"
        elif ret_type in ("unsigned int", "unsigned", "uint32_t", "size_t"):
            fmt = "%u"
            cast = "(unsigned int)"
        elif ret_type in ("double", "float"):
            fmt = "%.17g"
            cast = ""
        elif ret_type == "void":
            lines.append(f"        {call_str};")
            args_json = json.dumps(inp.args)
            lines.append(
                f'        printf("{{\\"fn\\":\\"{inp.function_name}\\",\\"idx\\":{idx},'
                f'\\"args\\":{_c_str_escape(args_json)},\\"out\\":null}}\\n");'
            )
            lines.append("    }")
            continue
        else:
            fmt = "%d"
            cast = "(int)"

        result_var = f"r_{idx}"
        lines.append(f"        {ret_type} {result_var} = {call_str};")
        args_json = json.dumps(inp.args)
        lines.append(
            f'        printf("{{\\"fn\\":\\"{inp.function_name}\\",\\"idx\\":{idx},'
            f'\\"args\\":{_c_str_escape(args_json)},\\"out\\":{fmt}}}\\n", '
            f'{cast}{result_var});'
        )
        lines.append("    }")

    lines.append("    return 0;")
    lines.append("}")

    driver_path = run_dir / "driver.c"
    driver_path.write_text("\n".join(lines), encoding="utf-8")
    return driver_path


def _c_str_escape(s: str) -> str:
    """Escape a string for embedding in a C string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")




def _compile_driver(driver_path: Path, run_dir: Path) -> Path:
    """Compile the C driver with clang or gcc."""
    binary_path = run_dir / "driver"
    compiler = os.environ.get("CC") or shutil.which("clang") or shutil.which("gcc") or shutil.which("cc") or "clang"
    cmd = [
        compiler,
        "-fwrapv",                     # defined signed integer overflow
        "-o", str(binary_path),
        str(driver_path),
        "-lm",                         # link math library just in case
    ]
    console.print(f"  Compiling: [dim]{' '.join(cmd)}[/]")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        console.print(f"  [red]Compilation failed:[/]\n{result.stderr}")
        raise RuntimeError(f"Compilation failed:\n{result.stderr}")

    console.print("  [green]✓ Compilation succeeded[/]")
    return binary_path


def _run_driver(binary_path: Path, timeout: int = 30) -> list[dict]:
    """Run the compiled driver and parse JSON line output."""
    console.print(f"  Running driver (timeout={timeout}s)...")

    result = subprocess.run(
        [str(binary_path)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    records: list[dict] = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            console.print(f"  [yellow]⚠ Skipping unparseable line: {line[:80]}[/]")

    console.print(f"  [green]✓ Driver produced {len(records)} records[/]")
    return records




def record_golden(
    source_path: Path,
    inputs: list[TestInput],
    run_dir: Path,
    signatures: list[FunctionSignature] | None = None,
) -> GoldenFile:
    """Record golden output by compiling and running the legacy C code.

    Args:
        source_path: Path to the legacy C source file.
        inputs: Test inputs to exercise.
        run_dir: Directory for build artifacts and output.
        signatures: Function signatures (needed for driver generation).

    Returns:
        Immutable GoldenFile with all recorded behaviors.
    """
    console.rule("[bold cyan]📼 Recorder — Recording Golden Output[/]")

    run_dir.mkdir(parents=True, exist_ok=True)

    if signatures is None:
        # Minimal fallback — extract from inputs
        from .archaeologist import analyze_module
        from .llm import LLMClient
        llm = LLMClient(run_dir=run_dir)
        signatures = analyze_module(source_path, llm)

    # Generate, compile, and run the driver
    driver_path = _generate_driver(source_path, inputs, signatures, run_dir)
    binary_path = _compile_driver(driver_path, run_dir)
    raw_records = _run_driver(binary_path)

    # Build a fast lookup from inputs
    input_by_idx: dict[int, TestInput] = {}
    for i, inp in enumerate(inputs):
        input_by_idx[i] = inp

    # Convert to GoldenRecord objects
    golden_records: list[GoldenRecord] = []
    for rec in raw_records:
        idx = rec.get("idx", -1)
        test_input = input_by_idx.get(idx)
        if test_input is None:
            # Build from the raw record
            test_input = TestInput(
                function_name=rec.get("fn", "unknown"),
                args=rec.get("args", []),
                source="recorded",
            )
        golden_records.append(GoldenRecord(
            input=test_input,
            output=rec.get("out"),
            exit_status=0,
        ))

    # Mark inputs that didn't produce output (crash/timeout)
    seen_indices = {rec.get("idx") for rec in raw_records}
    for i, inp in enumerate(inputs):
        if i not in seen_indices:
            golden_records.append(GoldenRecord(
                input=inp,
                output=None,
                exit_status=-1,
                error="No output (possible crash or skip)",
            ))

    # Build golden file
    golden = GoldenFile(
        records=golden_records,
        module_name=source_path.stem,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    golden.compute_hash()

    # Persist
    golden_path = run_dir / "golden.json"
    golden_data = {
        "module_name": golden.module_name,
        "hash": golden.hash,
        "timestamp": golden.timestamp,
        "records": [
            {
                "function_name": r.input.function_name,
                "args": r.input.args,
                "source": r.input.source,
                "output": r.output,
                "exit_status": r.exit_status,
                "error": r.error,
            }
            for r in golden.records
        ],
    }
    golden_path.write_text(json.dumps(golden_data, indent=2), encoding="utf-8")
    console.print(f"  Golden file: [dim]{golden_path}[/]")
    console.print(f"  SHA-256:     [dim]{golden.hash[:16]}…[/]")
    console.print(f"  Records:     {len(golden.records)}")
    console.print(f"  [green]✓ Golden recording complete (immutable)[/]")

    return golden
