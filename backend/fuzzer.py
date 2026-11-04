"""Fuzzer agent — generates comprehensive test inputs for legacy C functions.

Three-stage input generation:
  (a) Deterministic boundary seeds from a table (zero, one, INT_MAX, INT_MIN, etc.)
  (b) Model-generated edge cases targeting specific suspicious patterns
  (c) Mutations of boundary seeds for broader coverage

Target: 300+ inputs per function.
"""

from __future__ import annotations

import json
import random
from typing import Any

from rich.console import Console

from . import AgentRole, FunctionSignature, TestInput
from .llm import LLMClient

console = Console()


INT32_MAX = 2_147_483_647
INT32_MIN = -2_147_483_648

# Representative boundary values for integer parameters
_INT_BOUNDARIES: list[int] = [
    0, 1, -1, 2, -2,
    INT32_MAX, INT32_MIN, INT32_MAX - 1, INT32_MIN + 1,
    100, -100, 1000, -1000,
    10000, -10000, 9999, 10001,
    5000,  # common for basis points (50%)
    333, 500, 750, 825, 1000, 2500,  # common BPS / rate values
    31, 30, 29, 28, 27, 15, 14, 1,   # days
    12, 11, 6, 4, 2,                  # months
    2024, 2023, 2000, 1900, 1600, 2100,  # years
    46341,  # sqrt(INT32_MAX) + 1 — overflow boundary
    -46341,
]

# Small list sizes for array parameters
_ARRAY_SIZES: list[int] = [0, 1, 2, 3, 5, 10]


def _is_array_param(param_type: str, param_name: str) -> bool:
    """Check if a parameter represents a C array."""
    return "[]" in param_name or "[]" in param_type or "*" in param_type


def _is_size_param(param_name: str) -> bool:
    """Check if a parameter is likely a size/count parameter."""
    return any(kw in param_name.lower() for kw in ("n_", "num", "count", "size", "len"))


def _generate_boundary_seeds(
    sig: FunctionSignature, rng: random.Random
) -> list[TestInput]:
    """Stage (a): Generate deterministic boundary-value inputs."""
    inputs: list[TestInput] = []
    param_count = len(sig.params)

    if param_count == 0:
        inputs.append(TestInput(function_name=sig.name, args=[], source="boundary"))
        return inputs

    # Identify which params are arrays vs scalars
    array_indices: list[int] = []
    size_indices: list[int] = []
    scalar_indices: list[int] = []

    for i, (ptype, pname) in enumerate(sig.params):
        if _is_array_param(ptype, pname):
            array_indices.append(i)
        elif _is_size_param(pname):
            size_indices.append(i)
        else:
            scalar_indices.append(i)

    # For functions with array parameters, generate paired array + size inputs
    if array_indices:
        for arr_size in _ARRAY_SIZES[1:6]:  # 1..10 elements
            for _ in range(min(20, max(5, 60 // param_count))):
                args: list[Any] = [None] * param_count
                for ai in array_indices:
                    args[ai] = [rng.choice(_INT_BOUNDARIES[:20]) for _ in range(arr_size)]
                for si in size_indices:
                    args[si] = arr_size
                for sci in scalar_indices:
                    args[sci] = rng.choice(_INT_BOUNDARIES[:20])
                inputs.append(TestInput(
                    function_name=sig.name, args=args, source="boundary",
                ))
    else:
        # Pure scalar functions: systematic boundary combinations
        boundary_subset = _INT_BOUNDARIES[:25]

        # All-same-value sweep
        for val in boundary_subset[:15]:
            args = [val] * param_count
            inputs.append(TestInput(
                function_name=sig.name, args=args, source="boundary",
            ))

        # One-param-varied, others held at 1
        for i in range(param_count):
            for val in boundary_subset:
                args = [1] * param_count
                args[i] = val
                inputs.append(TestInput(
                    function_name=sig.name, args=args, source="boundary",
                ))

        # Random combinations from boundary table
        for _ in range(min(100, max(20, 200 // max(param_count, 1)))):
            args = [rng.choice(boundary_subset) for _ in range(param_count)]
            inputs.append(TestInput(
                function_name=sig.name, args=args, source="boundary",
            ))

    return inputs


def _generate_model_edge_cases(
    sig: FunctionSignature,
    source_code: str,
    llm: LLMClient,
) -> list[TestInput]:
    """Stage (b): Use the LLM to generate targeted edge-case inputs."""
    system_prompt = (
        "You are a fuzzer agent that generates edge case test inputs for C functions. "
        "Your goal is to find inputs that trigger behavioral differences between C and Python, "
        "including integer overflow, truncation-toward-zero division, rounding tie-breaks, "
        "and boundary conditions.\n\n"
        "Respond with a JSON object containing an 'edge_cases' array. Each element has:\n"
        '  - "function": string — function name\n'
        '  - "args": array of arguments (use arrays for array parameters)\n'
        '  - "reason": string — why this input is interesting\n'
    )

    user_msg = (
        f"Generate edge-case inputs for testing this C module:\n\n```c\n{source_code}\n```\n\n"
        f"Focus especially on function: {sig.name} with params: "
        f"{', '.join(f'{t} {n}' for t, n in sig.params)}\n"
        f"Notes from analysis: {sig.notes}"
    )

    response = llm.complete(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        role=AgentRole.FUZZER,
        purpose=f"Generate edge-case inputs for {sig.name}",
        json_mode=True,
    )

    inputs: list[TestInput] = []
    try:
        data = json.loads(response.content)
        for ec in data.get("edge_cases", []):
            fn_name = ec.get("function", sig.name)
            args = ec.get("args", [])
            inputs.append(TestInput(
                function_name=fn_name,
                args=args,
                source="model",
            ))
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        console.print(f"  [yellow][WARN] Edge case parse error: {exc}[/]")

    return inputs


def _mutate_seeds(
    seeds: list[TestInput], sig: FunctionSignature, rng: random.Random, target_count: int
) -> list[TestInput]:
    """Stage (c): Mutate existing seeds to generate additional inputs."""
    if not seeds:
        return []

    mutations: list[TestInput] = []

    # Small perturbation table
    perturbations = [0, 1, -1, 2, -2, 10, -10, 100, -100, 1000, -1000]

    while len(mutations) < target_count:
        seed = rng.choice(seeds)
        new_args: list[Any] = []
        for arg in seed.args:
            if isinstance(arg, list):
                # Mutate array elements
                new_arr = []
                for elem in arg:
                    if isinstance(elem, int):
                        delta = rng.choice(perturbations)
                        new_arr.append(elem + delta)
                    else:
                        new_arr.append(elem)
                # Occasionally add or remove an element
                if rng.random() < 0.1 and len(new_arr) > 1:
                    new_arr.pop(rng.randint(0, len(new_arr) - 1))
                elif rng.random() < 0.1:
                    new_arr.append(rng.choice(_INT_BOUNDARIES[:15]))
                new_args.append(new_arr)
            elif isinstance(arg, int):
                delta = rng.choice(perturbations)
                new_args.append(arg + delta)
            else:
                new_args.append(arg)

        # If function has array and size params, ensure size does not exceed array bounds
        for i, (ptype, pname) in enumerate(sig.params):
            if _is_size_param(pname) and i < len(new_args):
                # Find matching array
                arr_lens = [len(new_args[j]) for j, (pj_t, pj_n) in enumerate(sig.params)
                            if _is_array_param(pj_t, pj_n) and j < len(new_args) and isinstance(new_args[j], list)]
                if arr_lens:
                    new_args[i] = min(arr_lens)

        mutations.append(TestInput(
            function_name=seed.function_name,
            args=new_args,
            source="mutation",
        ))

    return mutations


def _dedup_inputs(inputs: list[TestInput]) -> list[TestInput]:
    """Remove duplicate inputs (same function + args)."""
    seen: set[str] = set()
    unique: list[TestInput] = []
    for inp in inputs:
        key = f"{inp.function_name}:{json.dumps(inp.args, sort_keys=True)}"
        if key not in seen:
            seen.add(key)
            unique.append(inp)
    return unique




def generate_inputs(
    signatures: list[FunctionSignature],
    source_code: str,
    llm: LLMClient,
    seed: int = 42,
) -> list[TestInput]:
    """Generate comprehensive test inputs for all functions.

    Args:
        signatures: Function signatures from the archaeologist.
        source_code: Raw C source code.
        llm: LLM client for model-generated edge cases.
        seed: Random seed for deterministic generation.

    Returns:
        Deduplicated list of test inputs (target: 300+ per function).
    """
    console.rule("[bold cyan]Fuzzer — Generating Test Inputs[/]")
    rng = random.Random(seed)
    all_inputs: list[TestInput] = []

    for sig in signatures:
        console.print(f"\n  Function: [bold green]{sig.name}[/]")

        # Stage (a): Boundary seeds
        boundary = _generate_boundary_seeds(sig, rng)
        console.print(f"    (a) Boundary seeds:     {len(boundary):>4}")

        # Stage (b): Model edge cases
        model = _generate_model_edge_cases(sig, source_code, llm)
        console.print(f"    (b) Model edge cases:   {len(model):>4}")

        # Stage (c): Mutations
        combined_seeds = boundary + model
        target_mutations = max(0, 300 - len(combined_seeds))
        mutations = _mutate_seeds(combined_seeds, sig, rng, target_mutations)
        console.print(f"    (c) Mutations:          {len(mutations):>4}")

        func_inputs = boundary + model + mutations
        all_inputs.extend(func_inputs)

    # Deduplicate
    before = len(all_inputs)
    all_inputs = _dedup_inputs(all_inputs)
    console.print(f"\n  Total inputs: {len(all_inputs)} (deduped from {before})")

    # Summary per function
    from collections import Counter
    fn_counts = Counter(inp.function_name for inp in all_inputs)
    for fn, count in fn_counts.items():
        console.print(f"    {fn}: {count}")

    source_counts = Counter(inp.source for inp in all_inputs)
    console.print(f"  By source: {dict(source_counts)}")
    console.print(f"  [green][OK] Generated {len(all_inputs)} total inputs[/]")

    return all_inputs
