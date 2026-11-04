"""Tests for replayer execution and comparison logic."""

from pathlib import Path
from backend import GoldenFile, GoldenRecord, TestInput
from backend.replayer import replay_and_compare


def test_replay_exact_match(tmp_path: Path):
    """Test that identical outputs result in 100% match rate."""
    py_code = """
def calculate_tier_price(q: int, p: int) -> int:
    return q * p
"""
    py_file = tmp_path / "migrated.py"
    py_file.write_text(py_code)

    golden = GoldenFile(
        records=[
            GoldenRecord(
                input=TestInput(function_name="calculate_tier_price", args=[10, 20]),
                output=200,
            ),
            GoldenRecord(
                input=TestInput(function_name="calculate_tier_price", args=[5, 10]),
                output=50,
            ),
        ],
        module_name="test_mod",
    )
    golden.compute_hash()

    rate, mismatches = replay_and_compare(py_file, golden, tmp_path)
    assert rate == 1.0
    assert len(mismatches) == 0


def test_replay_mismatch_detected(tmp_path: Path):
    """Test that differences in output are flagged strictly."""
    py_code = """
def compute_tax(amount: int, rate: int) -> int:
    return (amount * rate) // 10000  # missing + 5000 half-up rounding
"""
    py_file = tmp_path / "migrated.py"
    py_file.write_text(py_code)

    golden = GoldenFile(
        records=[
            # Half-up rounding expects 1
            GoldenRecord(
                input=TestInput(function_name="compute_tax", args=[5, 5000]),
                output=1,
            ),
        ],
        module_name="test_tax",
    )
    golden.compute_hash()

    rate, mismatches = replay_and_compare(py_file, golden, tmp_path)
    assert rate == 0.0
    assert len(mismatches) == 1
    assert mismatches[0].expected == 1
    assert mismatches[0].actual == 2
