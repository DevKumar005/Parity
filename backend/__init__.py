"""Parity — Verify that migrated billing code behaves exactly like the legacy original."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


__version__ = "0.1.0"




class AgentRole(str, Enum):
    """Roles for the LLM-powered agents in the pipeline."""
    ARCHAEOLOGIST = "archaeologist"
    FUZZER = "fuzzer"
    MIGRATOR = "migrator"
    DEBUGGER = "debugger"
    RED_TEAM = "red_team"
    QUIRK_TRIAGE = "quirk_triage"


class DiagnosisCategory(str, Enum):
    """Closed taxonomy for mismatch diagnosis."""
    ROUNDING = "rounding"
    INTEGER_OVERFLOW = "integer_overflow"
    INTEGER_DIVISION = "integer_division"
    NEGATIVE_MODULO = "negative_modulo"
    FLOAT_FORMATTING = "float_formatting"
    DATE_CALENDAR = "date_calendar"
    STRING_ENCODING = "string_encoding"
    OTHER = "other"


class QuirkLabel(str, Enum):
    """Labels for suspicious preserved behaviors."""
    LIKELY_BUG = "likely_bug"
    LIKELY_INTENTIONAL = "likely_intentional"
    UNCLEAR = "unclear"


@dataclass
class FunctionSignature:
    """Extracted function signature from legacy code."""
    name: str
    return_type: str
    params: list[tuple[str, str]]  # (type, name) pairs
    notes: str = ""  # Suspicious logic notes from archaeologist


@dataclass
class TestInput:
    """A single test input for a function."""
    __test__ = False  # Prevent pytest from treating this as a test class
    function_name: str
    args: list[Any]
    source: str = "boundary"  # boundary | model | mutation | redteam | heldout
    seed: int | None = None


@dataclass
class GoldenRecord:
    """Recorded behavior of the legacy code on a single input."""
    input: TestInput
    output: Any
    exit_status: int = 0
    error: str | None = None
    timed_out: bool = False


@dataclass
class GoldenFile:
    """Immutable collection of golden records with hash."""
    records: list[GoldenRecord]
    hash: str = ""
    module_name: str = ""
    timestamp: str = ""

    def compute_hash(self) -> str:
        """Compute SHA-256 hash of all records."""
        data = json.dumps(
            [
                {
                    "fn": r.input.function_name,
                    "args": r.input.args,
                    "output": r.output,
                    "exit_status": r.exit_status,
                }
                for r in self.records
            ],
            sort_keys=True,
        )
        self.hash = hashlib.sha256(data.encode()).hexdigest()
        return self.hash


@dataclass
class Mismatch:
    """A single mismatch between legacy and migrated behavior."""
    input: TestInput
    expected: Any
    actual: Any
    diagnosis: DiagnosisCategory | None = None
    cluster_id: int | None = None


@dataclass
class PatchResult:
    """Result of applying a debugger patch."""
    round_num: int
    patch_description: str
    code_diff: str
    fixed_count: int
    regressed_count: int
    accepted: bool
    new_match_rate: float


@dataclass
class QuirkEntry:
    """A suspicious behavior flagged during quirk triage."""
    behavior: str
    example_inputs: list[TestInput]
    label: QuirkLabel
    evidence: str
    recommended_action: str


@dataclass
class UsageLedgerEntry:
    """Per-call usage tracking."""
    provider: str
    model: str
    role: str  # AgentRole value
    purpose: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    timestamp: str = ""
    cached: bool = False


@dataclass
class PipelineResult:
    """Complete result of a Parity pipeline run."""
    module_name: str
    signatures: list[FunctionSignature] = field(default_factory=list)
    total_inputs: int = 0
    golden_hash: str = ""
    first_pass_match_rate: float = 0.0
    final_match_rate: float = 0.0
    held_out_match_rate: float = 0.0
    adversarial_breaks: int = 0
    adversarial_fixed: int = 0
    repair_rounds: int = 0
    mismatches: list[Mismatch] = field(default_factory=list)
    remaining_mismatches: list[Mismatch] = field(default_factory=list)
    patch_history: list[PatchResult] = field(default_factory=list)
    quirks: list[QuirkEntry] = field(default_factory=list)
    behavior_contract: list[str] = field(default_factory=list)
    usage_ledger: list[UsageLedgerEntry] = field(default_factory=list)
    wall_clock_seconds: float = 0.0
    total_cost_usd: float = 0.0
    migrated_code: str = ""
    legacy_code: str = ""
    run_dir: Path | None = None
    seeds: dict[str, int] = field(default_factory=dict)

