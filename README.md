# Parity

**Verify that migrated billing code behaves exactly like the legacy original — and show the evidence.**

Built with Muse Spark Open · Meta Global AI Developer Hackathon · Indie Developer Track

---

## What Parity Does

Parity is an autonomous agent that migrates legacy C billing logic to Python and produces **measured evidence** of behavioral equivalence. It doesn't just translate code — it:

1. **Records** what the original actually does on hundreds of edge-case inputs
2. **Migrates** the code using Muse Spark Open
3. **Replays** the same inputs and finds every mismatch
4. **Diagnoses** root causes (rounding, overflow, integer division, calendar math)
5. **Repairs** mismatches without breaking anything that already worked
6. **Verifies** on held-out and adversarial inputs the agent never saw
7. **Reports** what was verified identical, what still differs, and which legacy quirks look like bugs

## Quick Start

```bash
# 1. Setup virtual environment & dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
# or if using uv: uv sync

# 2. Configure environment (zero-key demo mode works by default)
cp .env.example .env

# 3. Run the one-command demo on development module
./demo/run_demo.sh

# 4. Or run any module directly via CLI
python3 -m parity.cli run samples/legacy/tiered_pricing.c --open-report

# 5. Run evaluation across all 3 benchmark modules
python3 -m parity.cli evaluate

# 6. Launch the interactive Web Dashboard & Visualizer
python3 -m parity.cli serve
# Then open http://127.0.0.1:8000 in your browser!
```

## Folder Structure

```
parity/
├── backend/
│   └── server.py             # FastAPI REST endpoints & runner service
├── frontend/
│   └── index.html            # Interactive visual dashboard & code comparator
├── parity/                   # Core autonomous verification engine
│   ├── __init__.py           # Shared data contracts (PipelineResult, GoldenFile, etc.)
│   ├── archaeologist.py      # Stage 1: Signature extraction & logic probe notes
│   ├── fuzzer.py             # Stage 2: Hypothesis boundary fuzzing & edge cases
│   ├── recorder.py           # Stage 3: Clang compile (-fwrapv) & immutable SHA-256 golden file
│   ├── migrator.py           # Stage 4: Muse Spark Open C-to-Python translation
│   ├── replayer.py           # Stage 5: Strict differential replay & mismatch detection
│   ├── debugger.py           # Stage 6: Monotonic repair loop & anti-hardcoding check
│   ├── heldout.py            # Stage 7: Generalization check on fresh unseen seeds
│   ├── redteam.py            # Stage 8: Adversarial verifier exploiting semantic divergences
│   ├── quirks.py             # Stage 9: Quirk triage & evidence-backed behavior contract
│   ├── report.py             # Stage 10: HTML report & Parity Score card generation
│   ├── cli.py                # Typer & Rich single CLI entry point
│   └── llm.py                # Provider-agnostic client, failover chain & mock engine
├── samples/
│   ├── legacy/               # Authentic legacy C billing modules (pure functions)
│   │   ├── tiered_pricing.c  # Development set (32-bit signed overflow quirk)
│   │   ├── invoice_total.c   # Held-out set (Half-up vs banker's rounding quirk)
│   │   └── proration.c       # Held-out set (Negative integer division truncation)
│   └── expected/             # Ground-truth specifications for scoring
├── runs/                     # Per-run outputs: golden records, patches, diffs, reports
├── demo/
│   └── run_demo.sh           # One-command demo script
└── tests/                    # Pytest verification suite (8/8 passing)
```

## Benchmark Evaluation Results

| Module | Set | Inputs | First-Pass BPR | Final BPR | Held-Out BPR | Adversarial Breaks | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `tiered_pricing.c` | Development | 835 | 83.6% | **100.0%** | **99.9%** | 0 | Verified |
| `invoice_total.c` | Held-Out | 565 | 60.7% | **100.0%** | **100.0%** | 0 | Verified |
| `proration.c` | Held-Out | 562 | 31.1% | **100.0%** | **100.0%** | 0 | Verified |

## Testing

```bash
PYTHONPATH=. pytest tests/
```
All tests pass in < 0.1s.

## Demo Mode

Parity works out of the box with `PARITY_PROVIDERS=mock` — no API keys needed. The mock provider returns realistic, deterministic responses so you can see the full pipeline in action.

When you have API access, just update `.env`:
```
PARITY_PROVIDERS=baseten,modal,fireworks
BASETEN_API_KEY=your-key-here
```

## Models & Providers

- **Model**: Muse Spark Open (Meta open weights)
- **Providers**: Baseten (primary), Modal (backup), Fireworks (backup)
- **Model ID**: `muse-spark-open-1026` (event-specific Baseten ID)

## Architecture

```
Archaeologist → Fuzzer → Recorder → Migrator → Replayer → Debugger → Held-out → Red Team → Quirk Triage → Reporter
```

Each stage is an autonomous agent powered by Muse Spark Open. The model serves as fuzzer, archaeologist, migrator, debugger, and red-team adversary — with a usage ledger tracking every call.

## Hackathon

- **Event**: Meta Global AI Developer Hackathon (Cerebral Valley)
- **Track**: Indie Developer — Push the Frontier
- **Builder**: Dev (solo)
- **Built during**: Oct 27 – Nov 4, 2026

