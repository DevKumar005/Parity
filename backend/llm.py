"""Provider-agnostic LLM client with ordered failover, mock provider, and usage ledger."""

from __future__ import annotations

import hashlib
import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import AgentRole, UsageLedgerEntry




@dataclass
class LLMResponse:
    """Standardized response from any provider."""
    content: str
    input_tokens: int
    output_tokens: int
    model: str
    provider: str
    latency_ms: float
    cached: bool = False


class Provider(ABC):
    """Abstract base for inference providers."""
    name: str

    @abstractmethod
    def complete(self, messages: list[dict], temperature: float = 0.0,
                 max_tokens: int = 4096, json_mode: bool = False) -> LLMResponse:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...




class MockProvider(Provider):
    """Returns deterministic, realistic responses keyed by agent role.

    This provider enables the full pipeline to run end-to-end without
    any API keys. Responses are crafted to produce demo-quality output.
    """
    name = "mock"

    def __init__(self):
        self._responses: dict[str, dict] = {}

    def is_available(self) -> bool:
        return True  # Always works

    def complete(self, messages: list[dict], temperature: float = 0.0,
                 max_tokens: int = 4096, json_mode: bool = False) -> LLMResponse:
        start = time.time()

        # Determine the agent role from system message
        system_msg = ""
        user_msg = ""
        for m in messages:
            if m.get("role") == "system":
                system_msg = m.get("content", "")
            elif m.get("role") == "user":
                user_msg = m.get("content", "")

        # Route to role-specific mock response
        content = self._route_response(system_msg, user_msg)

        elapsed = (time.time() - start) * 1000
        return LLMResponse(
            content=content,
            input_tokens=len(json.dumps(messages)) // 4,
            output_tokens=len(content) // 4,
            model="muse-spark-open-mock",
            provider="mock",
            latency_ms=elapsed,
            cached=False,
        )

    def _route_response(self, system_msg: str, user_msg: str) -> str:
        """Route to the correct mock response based on system prompt content."""
        sys_lower = system_msg.lower()

        if "archaeologist" in sys_lower:
            return self._archaeologist_response(user_msg)
        elif "fuzzer" in sys_lower or "edge case" in sys_lower or "test input" in sys_lower:
            return self._fuzzer_response(user_msg)
        elif "migrat" in sys_lower:
            return self._migrator_response(user_msg)
        elif "debug" in sys_lower or "diagnos" in sys_lower:
            return self._debugger_response(user_msg)
        elif "red.?team" in sys_lower or "adversar" in sys_lower:
            return self._redteam_response(user_msg)
        elif "quirk" in sys_lower or "triage" in sys_lower:
            return self._quirk_response(user_msg)
        else:
            return self._generic_response(user_msg)

    def _archaeologist_response(self, user_msg: str) -> str:
        """Mock archaeologist: extract signatures and probe notes."""
        if "tiered_pricing" in user_msg or "tiered" in user_msg:
            return json.dumps({
                "functions": [
                    {
                        "name": "calculate_tier_price",
                        "return_type": "int",
                        "params": [["int", "quantity"], ["int", "unit_price_cents"]],
                        "notes": "Uses 32-bit int multiplication for amount in cents. "
                                 "Large quantities * high unit prices will overflow INT_MAX (2147483647). "
                                 "The overflow wraps to negative values, which means large invoices "
                                 "could silently produce negative totals."
                    },
                    {
                        "name": "apply_discount",
                        "return_type": "int",
                        "params": [["int", "amount_cents"], ["int", "discount_bps"]],
                        "notes": "Discount in basis points (1/100 of a percent). Integer division "
                                 "truncates toward zero. Negative amounts with discounts may behave "
                                 "unexpectedly due to C's truncation-toward-zero rule for negative division."
                    },
                    {
                        "name": "total_with_tiers",
                        "return_type": "int",
                        "params": [["int", "quantities[]"], ["int", "prices[]"], ["int", "n_items"],
                                   ["int", "discount_bps"]],
                        "notes": "Accumulates tier totals then applies discount. Overflow can occur "
                                 "both in individual tier calculations and in the accumulation. "
                                 "The accumulator is a 32-bit int."
                    }
                ]
            })
        elif "invoice_total" in user_msg or "invoice" in user_msg:
            return json.dumps({
                "functions": [
                    {
                        "name": "compute_tax",
                        "return_type": "int",
                        "params": [["int", "amount_cents"], ["int", "tax_rate_bps"]],
                        "notes": "Tax computed as (amount * rate + 5000) / 10000 — this is "
                                 "integer-math half-up rounding. Python's round() uses banker's "
                                 "rounding (half-to-even), which will differ on exact halves."
                    },
                    {
                        "name": "invoice_total",
                        "return_type": "int",
                        "params": [["int", "subtotal_cents"], ["int", "tax_rate_bps"],
                                   ["int", "fee_cents"]],
                        "notes": "Adds subtotal + tax + fee. Tax uses the half-up rounding above. "
                                 "Overflow possible on very large subtotals."
                    }
                ]
            })
        elif "proration" in user_msg or "prorat" in user_msg:
            return json.dumps({
                "functions": [
                    {
                        "name": "days_in_month",
                        "return_type": "int",
                        "params": [["int", "year"], ["int", "month"]],
                        "notes": "Leap year check: divisible by 4, except centuries unless divisible by 400. "
                                 "Edge cases: year 1900 (not leap), 2000 (leap), negative years."
                    },
                    {
                        "name": "prorate_charge",
                        "return_type": "int",
                        "params": [["int", "monthly_cents"], ["int", "start_day"],
                                   ["int", "end_day"], ["int", "year"], ["int", "month"]],
                        "notes": "Calculates (monthly_cents * days_used) / days_in_month using integer "
                                 "division. Days used = end_day - start_day + 1. Integer division "
                                 "truncates, which differs from Python's floor division for negative values."
                    }
                ]
            })
        return json.dumps({"functions": []})

    def _fuzzer_response(self, user_msg: str) -> str:
        """Mock fuzzer: generate edge-case inputs."""
        if "tiered_pricing" in user_msg or "calculate_tier_price" in user_msg:
            return json.dumps({
                "edge_cases": [
                    {"function": "calculate_tier_price", "args": [2147483647, 2], "reason": "INT_MAX * 2 overflows"},
                    {"function": "calculate_tier_price", "args": [100000, 30000], "reason": "Large product near overflow boundary"},
                    {"function": "calculate_tier_price", "args": [-1, 100], "reason": "Negative quantity"},
                    {"function": "calculate_tier_price", "args": [0, 0], "reason": "Zero quantity and price"},
                    {"function": "apply_discount", "args": [-500, 1000], "reason": "Negative amount with discount"},
                    {"function": "apply_discount", "args": [999, 3333], "reason": "Non-even division producing truncation difference"},
                    {"function": "apply_discount", "args": [1, 5000], "reason": "Tiny amount, 50% discount rounds to zero"},
                    {"function": "total_with_tiers", "args": [[1000000, 2000000], [1000, 2000], 2, 500],
                     "reason": "Multiple tiers accumulating near overflow"},
                ]
            })
        elif "invoice_total" in user_msg or "compute_tax" in user_msg:
            return json.dumps({
                "edge_cases": [
                    {"function": "compute_tax", "args": [1000, 750], "reason": "Tax = 75 cents exactly — half-up matches"},
                    {"function": "compute_tax", "args": [1, 5000], "reason": "Tiny amount, 50% tax — rounding tie"},
                    {"function": "compute_tax", "args": [333, 1000], "reason": "33.3 cents tax — rounding difference"},
                    {"function": "compute_tax", "args": [2147483647, 1], "reason": "Overflow in amount * rate"},
                    {"function": "invoice_total", "args": [10000, 825, 500], "reason": "Standard invoice: subtotal + 8.25% tax + fee"},
                    {"function": "invoice_total", "args": [5, 5000, 0], "reason": "Half-up vs banker's rounding on exact half"},
                ]
            })
        elif "proration" in user_msg or "prorate" in user_msg:
            return json.dumps({
                "edge_cases": [
                    {"function": "days_in_month", "args": [2000, 2], "reason": "Leap century: 29 days"},
                    {"function": "days_in_month", "args": [1900, 2], "reason": "Non-leap century: 28 days"},
                    {"function": "days_in_month", "args": [2024, 2], "reason": "Regular leap year: 29 days"},
                    {"function": "prorate_charge", "args": [3100, 1, 15, 2024, 1], "reason": "Half-month proration, 31 days"},
                    {"function": "prorate_charge", "args": [2800, 1, 28, 2024, 2], "reason": "Full Feb leap year"},
                    {"function": "prorate_charge", "args": [3000, 10, 10, 2023, 4], "reason": "Single day proration"},
                    {"function": "prorate_charge", "args": [-1000, 1, 15, 2024, 6], "reason": "Negative monthly, integer div differs"},
                ]
            })
        return json.dumps({"edge_cases": []})

    def _migrator_response(self, user_msg: str) -> str:
        """Mock migrator: C to Python migration."""
        if "tiered_pricing" in user_msg or "calculate_tier_price" in user_msg:
            return json.dumps({
                "migrated_code": '''"""Tiered pricing module — migrated from C to Python by Parity."""
import ctypes


def calculate_tier_price(quantity: int, unit_price_cents: int) -> int:
    """Calculate price for a tier. Preserves 32-bit integer overflow semantics."""
    result = ctypes.c_int32(quantity * unit_price_cents).value
    return result


def apply_discount(amount_cents: int, discount_bps: int) -> int:
    """Apply discount in basis points. Preserves C truncation-toward-zero."""
    discount = int(amount_cents * discount_bps / 10000)
    return amount_cents - discount


def total_with_tiers(quantities: list[int], prices: list[int], n_items: int,
                     discount_bps: int) -> int:
    """Sum tier prices and apply discount. Preserves 32-bit accumulation."""
    total = ctypes.c_int32(0)
    for i in range(n_items):
        tier = calculate_tier_price(quantities[i], prices[i])
        total = ctypes.c_int32(total.value + tier)
    return apply_discount(total.value, discount_bps)
''',
                "notes": "Used ctypes.c_int32 to preserve 32-bit integer overflow wrapping. "
                         "Used int() truncation for C-style division toward zero."
            })
        elif "invoice_total" in user_msg or "compute_tax" in user_msg:
            return json.dumps({
                "migrated_code": '''"""Invoice total module — migrated from C to Python by Parity."""


def compute_tax(amount_cents: int, tax_rate_bps: int) -> int:
    """Compute tax with half-up rounding via integer math."""
    return (amount_cents * tax_rate_bps + 5000) // 10000


def invoice_total(subtotal_cents: int, tax_rate_bps: int, fee_cents: int) -> int:
    """Compute invoice total: subtotal + tax + fee."""
    tax = compute_tax(subtotal_cents, tax_rate_bps)
    return subtotal_cents + tax + fee_cents
''',
                "notes": "Python's // is floor division, not truncation-toward-zero. "
                         "For positive values this matches C, but for negative values "
                         "it will differ. The half-up rounding formula (+ 5000) // 10000 "
                         "may also differ from C's (+ 5000) / 10000 for negative amounts."
            })
        elif "proration" in user_msg or "prorate" in user_msg:
            return json.dumps({
                "migrated_code": '''"""Proration module — migrated from C to Python by Parity."""


def days_in_month(year: int, month: int) -> int:
    """Return the number of days in the given month/year."""
    if month == 2:
        if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
            return 29
        return 28
    if month in (4, 6, 9, 11):
        return 30
    return 31


def prorate_charge(monthly_cents: int, start_day: int, end_day: int,
                   year: int, month: int) -> int:
    """Prorate a monthly charge for a partial period."""
    days_used = end_day - start_day + 1
    total_days = days_in_month(year, month)
    return (monthly_cents * days_used) // total_days
''',
                "notes": "Python's // is floor division. For negative monthly_cents, "
                         "this gives a different result than C's / which truncates toward zero. "
                         "E.g., -7 // 2 = -4 in Python vs -7 / 2 = -3 in C."
            })
        return json.dumps({"migrated_code": "# No migration available", "notes": ""})

    def _debugger_response(self, user_msg: str) -> str:
        """Mock debugger: diagnose and patch with complete revised code."""
        if "tiered_pricing" in user_msg or "calculate_tier_price" in user_msg or "apply_discount" in user_msg:
            return json.dumps({
                "diagnosis": "integer_overflow",
                "explanation": "C uses 32-bit signed integers that wrap on overflow. The initial translation "
                               "omitted bounds guards on basis points and 32-bit wrapping in discount arithmetic. "
                               "Must replicate C 32-bit integer arithmetic and guards using ctypes.c_int32.",
                "patched_code": '''"""Tiered pricing module — migrated and verified by Parity."""
import ctypes


def calculate_tier_price(quantity: int, unit_price_cents: int) -> int:
    """Calculate price for a tier. Preserves 32-bit integer overflow semantics."""
    quantity = ctypes.c_int32(quantity).value
    unit_price_cents = ctypes.c_int32(unit_price_cents).value
    return ctypes.c_int32(quantity * unit_price_cents).value


def apply_discount(amount_cents: int, discount_bps: int) -> int:
    """Apply discount in basis points. Preserves C truncation-toward-zero and guards."""
    amount_cents = ctypes.c_int32(amount_cents).value
    discount_bps = ctypes.c_int32(discount_bps).value
    if discount_bps <= 0:
        return amount_cents
    if discount_bps >= 10000:
        return 0
    product = ctypes.c_int32(amount_cents * discount_bps).value
    discount = int(product / 10000)
    return ctypes.c_int32(amount_cents - discount).value


def total_with_tiers(quantities: list[int], prices: list[int], n_items: int,
                     discount_bps: int) -> int:
    """Sum tier prices and apply discount. Preserves 32-bit accumulation."""
    n_items = ctypes.c_int32(n_items).value
    discount_bps = ctypes.c_int32(discount_bps).value
    if n_items <= 0:
        return 0
    running_total = ctypes.c_int32(0)
    limit = min(n_items, len(quantities), len(prices))
    for i in range(limit):
        tier = calculate_tier_price(quantities[i], prices[i])
        running_total = ctypes.c_int32(running_total.value + tier)
    return apply_discount(running_total.value, discount_bps)
'''
            })
        elif "invoice_total" in user_msg or "compute_tax" in user_msg:
            return json.dumps({
                "diagnosis": "rounding",
                "explanation": "C's integer expression (amount * rate + 5000) / 10000 performs "
                               "half-up rounding via truncation. Python's // is floor division, "
                               "which differs on negative values. Also wrapped with ctypes.c_int32.",
                "patched_code": '''"""Invoice total module — migrated and verified by Parity."""
import ctypes


def compute_tax(amount_cents: int, tax_rate_bps: int) -> int:
    """Compute tax with half-up rounding via integer math."""
    amount_cents = ctypes.c_int32(amount_cents).value
    tax_rate_bps = ctypes.c_int32(tax_rate_bps).value
    val = ctypes.c_int32(amount_cents * tax_rate_bps + 5000).value
    return int(val / 10000)


def invoice_total(subtotal_cents: int, tax_rate_bps: int, fee_cents: int) -> int:
    """Compute invoice total: subtotal + tax + fee."""
    subtotal_cents = ctypes.c_int32(subtotal_cents).value
    tax_rate_bps = ctypes.c_int32(tax_rate_bps).value
    fee_cents = ctypes.c_int32(fee_cents).value
    tax = compute_tax(subtotal_cents, tax_rate_bps)
    return ctypes.c_int32(subtotal_cents + tax + fee_cents).value
'''
            })
        elif "proration" in user_msg or "prorate" in user_msg:
            return json.dumps({
                "diagnosis": "integer_division",
                "explanation": "Python's // operator performs floor division, while C's / operator "
                               "truncates toward zero. Also guarded out-of-range months.",
                "patched_code": '''"""Proration module — migrated and verified by Parity."""
import ctypes


def days_in_month(year: int, month: int) -> int:
    """Return the number of days in the given month/year."""
    year = ctypes.c_int32(year).value
    month = ctypes.c_int32(month).value
    if month < 1 or month > 12:
        return 30
    if month == 2:
        is_leap = (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
        return 29 if is_leap else 28
    if month in (4, 6, 9, 11):
        return 30
    return 31


def prorate_charge(monthly_cents: int, start_day: int, end_day: int,
                   year: int, month: int) -> int:
    """Prorate a monthly charge for a partial period with C truncation toward zero."""
    monthly_cents = ctypes.c_int32(monthly_cents).value
    start_day = ctypes.c_int32(start_day).value
    end_day = ctypes.c_int32(end_day).value
    year = ctypes.c_int32(year).value
    month = ctypes.c_int32(month).value
    total_days = days_in_month(year, month)
    if total_days <= 0:
        return 0
    days_used = end_day - start_day + 1
    product = ctypes.c_int32(monthly_cents * days_used).value
    return int(product / total_days)
'''
            })
        return json.dumps({
            "diagnosis": "other",
            "explanation": "Mismatch requires further investigation.",
            "patched_code": user_msg
        })

    def _redteam_response(self, user_msg: str) -> str:
        """Mock red team: adversarial inputs."""
        return json.dumps({
            "adversarial_inputs": [
                {"function": "calculate_tier_price", "args": [46341, 46341],
                 "reason": "46341^2 = 2147488281 > INT_MAX, barely overflows"},
                {"function": "apply_discount", "args": [-2147483648, 1],
                 "reason": "INT_MIN with tiny discount — edge of representable range"},
                {"function": "compute_tax", "args": [-1, 5000],
                 "reason": "Negative amount with 50% tax — rounding tie on negative"},
                {"function": "prorate_charge", "args": [-100, 1, 31, 2024, 1],
                 "reason": "Negative charge full month — tests sign handling"},
                {"function": "prorate_charge", "args": [1, 1, 29, 2100, 2],
                 "reason": "2100 is NOT a leap year — tests century rule"},
            ]
        })

    def _quirk_response(self, user_msg: str) -> str:
        """Mock quirk triage: label suspicious behaviors."""
        return json.dumps({
            "quirks": [
                {
                    "behavior": "32-bit integer overflow wraps large invoice totals to negative values",
                    "label": "likely_bug",
                    "evidence": "calculate_tier_price(2147483647, 2) returns -2 instead of 4294967294. "
                                "No billing system intentionally produces negative totals from positive inputs.",
                    "recommended_action": "Flag for human review. Consider upgrading to 64-bit integers."
                },
                {
                    "behavior": "Integer division truncates toward zero on negative amounts",
                    "label": "likely_intentional",
                    "evidence": "apply_discount(-500, 1000) truncates the discount calculation. "
                                "This is standard C behavior and consistent with how the module "
                                "handles all divisions.",
                    "recommended_action": "Preserve. Document that negative amounts use truncation."
                },
                {
                    "behavior": "Half-up rounding for tax instead of banker's rounding",
                    "label": "unclear",
                    "evidence": "compute_tax uses (amount * rate + 5000) / 10000 which rounds 0.5 up. "
                                "This may be intentional (traditional accounting) or incidental.",
                    "recommended_action": "Preserve and flag. Ask the domain expert which rounding rule the business requires."
                }
            ],
            "behavior_contract": [
                "RULE 1: Prices are computed in cents as 32-bit signed integers. Overflow wraps. "
                "Evidence: calculate_tier_price(2147483647, 2) → -2.",
                "RULE 2: Discounts use integer division truncating toward zero. "
                "Evidence: apply_discount(-500, 1000) → -450 (not -451).",
                "RULE 3: Tax is rounded half-up using (amount * rate + 5000) / 10000. "
                "Evidence: compute_tax(5, 5000) → 1 (not 0 as banker's rounding would give).",
                "RULE 4: Proration uses integer division of (monthly * days_used) / total_days, "
                "truncating toward zero. Evidence: prorate_charge(-1000, 1, 15, 2024, 6) → -500 (not -501).",
                "RULE 5: February has 29 days in years divisible by 4, except centuries not divisible by 400. "
                "Evidence: days_in_month(1900, 2) → 28, days_in_month(2000, 2) → 29."
            ]
        })

    def _generic_response(self, user_msg: str) -> str:
        return json.dumps({"response": "Mock response — configure a real provider for actual inference."})




class OpenAICompatibleProvider(Provider):
    """Provider for any OpenAI-compatible inference endpoint (Baseten, Modal, Fireworks)."""

    def __init__(self, name: str, base_url: str, api_key: str, model_id: str):
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_id = model_id

    def is_available(self) -> bool:
        return bool(self._api_key and self._base_url)

    def complete(self, messages: list[dict], temperature: float = 0.0,
                 max_tokens: int = 4096, json_mode: bool = False) -> LLMResponse:
        import httpx

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        start = time.time()
        resp = httpx.post(
            f"{self._base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=120.0,
        )
        elapsed = (time.time() - start) * 1000
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})

        return LLMResponse(
            content=choice["message"]["content"],
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            model=self._model_id,
            provider=self.name,
            latency_ms=elapsed,
        )




class ResponseCache:
    """Simple disk-backed cache for LLM responses. Keyed by message hash."""

    def __init__(self, cache_dir: Path):
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _key(self, messages: list[dict]) -> str:
        raw = json.dumps(messages, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, messages: list[dict]) -> LLMResponse | None:
        path = self._dir / f"{self._key(messages)}.json"
        if path.exists():
            data = json.loads(path.read_text())
            return LLMResponse(
                content=data["content"],
                input_tokens=data["input_tokens"],
                output_tokens=data["output_tokens"],
                model=data["model"],
                provider=data["provider"],
                latency_ms=0.0,
                cached=True,
            )
        return None

    def put(self, messages: list[dict], response: LLMResponse) -> None:
        path = self._dir / f"{self._key(messages)}.json"
        path.write_text(json.dumps({
            "content": response.content,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "model": response.model,
            "provider": response.provider,
        }))




class LLMClient:
    """Provider-agnostic LLM client with ordered failover, caching, and usage ledger."""

    def __init__(self, run_dir: Path | None = None):
        self._providers: list[Provider] = []
        self._ledger: list[UsageLedgerEntry] = []
        self._cache: ResponseCache | None = None

        if run_dir:
            self._cache = ResponseCache(run_dir / ".cache")

        self._init_providers()

    def _init_providers(self) -> None:
        """Initialize providers from environment configuration."""
        provider_order = os.getenv("PARITY_PROVIDERS", "mock").split(",")

        for name in provider_order:
            name = name.strip().lower()
            if name == "mock":
                self._providers.append(MockProvider())
            elif name == "baseten":
                self._providers.append(OpenAICompatibleProvider(
                    name="baseten",
                    base_url=os.getenv("BASETEN_BASE_URL", ""),
                    api_key=os.getenv("BASETEN_API_KEY", ""),
                    model_id=os.getenv("BASETEN_MODEL_ID", "muse-spark-open-1026"),
                ))
            elif name == "modal":
                self._providers.append(OpenAICompatibleProvider(
                    name="modal",
                    base_url=os.getenv("MODAL_BASE_URL", ""),
                    api_key=os.getenv("MODAL_API_KEY", ""),
                    model_id=os.getenv("MODAL_MODEL_ID", ""),
                ))
            elif name == "fireworks":
                self._providers.append(OpenAICompatibleProvider(
                    name="fireworks",
                    base_url=os.getenv("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1"),
                    api_key=os.getenv("FIREWORKS_API_KEY", ""),
                    model_id=os.getenv("FIREWORKS_MODEL_ID", ""),
                ))
            elif name == "meta":
                self._providers.append(OpenAICompatibleProvider(
                    name="meta",
                    base_url=os.getenv("META_BASE_URL", "https://api.meta.ai/v1"),
                    api_key=os.getenv("META_API_KEY", ""),
                    model_id=os.getenv("META_MODEL_ID", ""),
                ))

        # Always have mock as final fallback
        if not any(isinstance(p, MockProvider) for p in self._providers):
            self._providers.append(MockProvider())

    def complete(self, messages: list[dict], role: AgentRole, purpose: str,
                 temperature: float = 0.0, max_tokens: int = 4096,
                 json_mode: bool = False) -> LLMResponse:
        """Send a completion request with automatic failover across providers."""
        # Check cache first
        if self._cache:
            cached = self._cache.get(messages)
            if cached:
                self._record_usage(cached, role, purpose)
                return cached

        last_error: Exception | None = None

        for provider in self._providers:
            if not provider.is_available():
                continue
            try:
                response = provider.complete(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
                # Cache the response
                if self._cache and not isinstance(provider, MockProvider):
                    self._cache.put(messages, response)

                self._record_usage(response, role, purpose)
                return response

            except Exception as e:
                last_error = e
                continue

        # Should never reach here because MockProvider always works
        raise RuntimeError(f"All providers failed. Last error: {last_error}")

    def _record_usage(self, response: LLMResponse, role: AgentRole, purpose: str) -> None:
        """Record a usage ledger entry."""
        # Estimate cost based on hosted Muse Spark Open pricing
        input_cost = response.input_tokens * 1.25 / 1_000_000
        output_cost = response.output_tokens * 4.25 / 1_000_000
        cost = input_cost + output_cost if response.provider != "mock" else 0.0

        entry = UsageLedgerEntry(
            provider=response.provider,
            model=response.model,
            role=role.value,
            purpose=purpose,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=cost,
            latency_ms=response.latency_ms,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            cached=response.cached,
        )
        self._ledger.append(entry)

    @property
    def ledger(self) -> list[UsageLedgerEntry]:
        return self._ledger

    @property
    def total_cost(self) -> float:
        return sum(e.cost_usd for e in self._ledger)

    @property
    def total_tokens(self) -> tuple[int, int]:
        inp = sum(e.input_tokens for e in self._ledger)
        out = sum(e.output_tokens for e in self._ledger)
        return inp, out

