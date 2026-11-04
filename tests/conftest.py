"""Pytest fixtures for Parity test suite."""

import tempfile
from pathlib import Path
import pytest

from backend import (
    DiagnosisCategory,
    FunctionSignature,
    GoldenFile,
    GoldenRecord,
    Mismatch,
    TestInput,
)


@pytest.fixture
def tmp_run_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for run artifacts."""
    run_dir = tmp_path / "test_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


@pytest.fixture
def sample_golden() -> GoldenFile:
    """Fixture with pre-defined golden records."""
    records = [
        GoldenRecord(
            input=TestInput(function_name="calculate_tier_price", args=[10, 500]),
            output=5000,
            exit_status=0,
        ),
        GoldenRecord(
            input=TestInput(function_name="calculate_tier_price", args=[0, 500]),
            output=0,
            exit_status=0,
        ),
        GoldenRecord(
            input=TestInput(function_name="apply_discount", args=[10000, 500]),
            output=9500,
            exit_status=0,
        ),
        GoldenRecord(
            input=TestInput(function_name="calculate_tier_price", args=[2147483647, 2]),
            output=-2,  # 32-bit signed integer overflow wrapping
            exit_status=0,
        ),
    ]
    gf = GoldenFile(records=records, module_name="tiered_pricing")
    gf.compute_hash()
    return gf


@pytest.fixture
def sample_mismatches() -> list[Mismatch]:
    """Fixture with representative mismatches."""
    return [
        Mismatch(
            input=TestInput(function_name="calculate_tier_price", args=[2147483647, 2]),
            expected=-2,
            actual=4294967294,
            diagnosis=DiagnosisCategory.INTEGER_OVERFLOW,
        ),
        Mismatch(
            input=TestInput(function_name="apply_discount", args=[-500, 1000]),
            expected=-450,
            actual=-451,
            diagnosis=DiagnosisCategory.INTEGER_DIVISION,
        ),
    ]
