"""Tests for debugger monotonic repair and anti-hardcoding checks."""

from pathlib import Path
from backend import (
    DiagnosisCategory,
    GoldenFile,
    GoldenRecord,
    Mismatch,
    TestInput,
)
from backend.debugger import _anti_hardcoding_check, _heuristic_diagnose, _test_candidate_code


def test_anti_hardcoding_rejects_literal_cheats():
    """Anti-hardcoding must catch patches that return hardcoded values for specific inputs."""
    failing = [
        Mismatch(
            input=TestInput(function_name="calculate_tier_price", args=[2147483647, 2]),
            expected=-2,
            actual=4294967294,
        )
    ]

    cheat_code = """
def calculate_tier_price(quantity, unit_price):
    if quantity == 2147483647:
        return -2
    return quantity * unit_price
"""
    assert _anti_hardcoding_check(cheat_code, failing) is False

    valid_code = """
import ctypes
def calculate_tier_price(quantity, unit_price):
    return ctypes.c_int32(quantity * unit_price).value
"""
    assert _anti_hardcoding_check(valid_code, failing) is True


def test_heuristic_diagnose():
    """Diagnoser correctly attributes overflow and division signs."""
    overflow_m = Mismatch(
        input=TestInput(function_name="calculate_tier_price", args=[2147483647, 2]),
        expected=-2,
        actual=4294967294,
    )
    assert _heuristic_diagnose(overflow_m) == DiagnosisCategory.INTEGER_OVERFLOW

    div_m = Mismatch(
        input=TestInput(function_name="apply_discount", args=[-500, 1000]),
        expected=-450,
        actual=-451,
    )
    assert _heuristic_diagnose(div_m) == DiagnosisCategory.INTEGER_DIVISION


def test_candidate_test_pass_and_fail(tmp_path: Path):
    """Ensure candidate evaluation counts correctly."""
    golden = GoldenFile(
        records=[
            GoldenRecord(
                input=TestInput(function_name="fn", args=[1]),
                output=2,
            ),
            GoldenRecord(
                input=TestInput(function_name="fn", args=[2]),
                output=4,
            ),
        ]
    )

    code = "def fn(x):\n    return x * 2\n"
    rate, mismatches, passing = _test_candidate_code(code, golden, tmp_path)
    assert rate == 1.0
    assert len(mismatches) == 0
    assert len(passing) == 2
