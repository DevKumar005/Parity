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

---

## Live Demo & Hosted Deployment

https://parity-3mvz.onrender.com/

---

## Quick Start CLI

```bash
# Run pipeline on a legacy C module with HTML report preview
parity run samples/legacy/tiered_pricing.c --open-report

# Run evaluation suite across all benchmark modules
parity evaluate

# Show configuration, provider health, and active models
parity info

# Launch the visualizer dashboard server
parity serve --port 8000
```

---

## Folder Structure

```
parity/
├── backend/                  # Autonomous verification engine & REST API
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
│   ├── cli.py                # Typer & Rich single CLI entry point (`parity`)
│   ├── llm.py                # Provider-agnostic client, failover chain & mock engine
│   ├── server.py             # FastAPI REST endpoints & static file serving
│   ├── prompts/              # System & task prompts for Muse Spark Open agents
│   └── templates/            # Jinja2 templates for reports & scorecard cards
├── frontend/
│   └── index.html            # Single-page interactive studio, dot-matrix hero & telemetry
├── samples/
│   ├── legacy/               # Authentic legacy C billing modules (pure functions)
│   │   ├── tiered_pricing.c  # Development set (32-bit signed overflow quirk)
│   │   ├── invoice_total.c   # Held-out set (Half-up vs banker's rounding quirk)
│   │   └── proration.c       # Held-out set (Negative integer division truncation)
│   └── expected/             # Ground-truth specifications for scoring
├── runs/                     # Per-run outputs: golden records, patches, diffs, scorecards
├── demo/
│   └── run_demo.sh           # One-command demo script
├── tests/                    # Pytest verification suite
├── Dockerfile                # Production container spec with Clang runtime
├── render.yaml               # Infrastructure-as-code deployment blueprint
├── pyproject.toml            # Project packaging specification
└── requirements.txt          # Python dependencies
```

---

## Benchmark Evaluation Results

| Module | Set | Inputs | First-Pass BPR | Final BPR | Held-Out BPR | Adversarial Breaks | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `tiered_pricing.c` | Development | 835 | 83.6% | **100.0%** | **99.9%** | 0 | Verified |
| `invoice_total.c` | Held-Out | 565 | 60.7% | **100.0%** | **100.0%** | 0 | Verified |
| `proration.c` | Held-Out | 562 | 31.1% | **100.0%** | **100.0%** | 0 | Verified |

---

## Testing

```bash
PYTHONPATH=. pytest tests/
```
All tests run with zero external API dependencies in mock mode.

---

## Models & Providers

- **Model**: Muse Spark Open (Meta open weights)
- **Providers**: Baseten (primary), Modal (backup), Fireworks (backup)
- **Model ID**: `muse-spark-open-1026` (event-specific Baseten ID)
- **Fallback**: Mock provider included for zero-key local execution and offline demos.

To connect live model providers, set keys in `.env`:
```bash
PARITY_PROVIDERS=baseten,modal,fireworks
BASETEN_API_KEY=your_baseten_key
BASETEN_MODEL_ID=muse-spark-open-1026
```

---

## Contributing

We welcome contributions to Parity! Whether you want to add new legacy C billing edge cases, improve agent prompts, expand red-teaming strategies, or enhance the dashboard visualizer:

### How to Contribute

1. **Fork the Repository**: Create your own feature branch (`git checkout -b feature/new-billing-sample`).
2. **Add Legacy Modules**:
   - Place pure C functions in `samples/legacy/<module_name>.c`.
   - Add the matching metadata and expected quirks in `samples/expected/<module_name>.json`.
3. **Enhance Pipeline Agents**:
   - Prompts live under `backend/prompts/`.
   - Core agent logic is modularized in `backend/` (Archaeologist, Fuzzer, Debugger, RedTeam).
4. **Run Verification & Tests**:
   - Ensure syntax passes: `python3 -m py_compile backend/*.py tests/*.py`
   - Run tests: `pytest tests/`
   - Test end-to-end: `parity run samples/legacy/tiered_pricing.c`
5. **Submit a Pull Request**: Include a clear description of your changes, the rationale, and any test runs or scorecards.

---

## Architecture

```
Archaeologist → Fuzzer → Recorder → Migrator → Replayer → Debugger → Held-out → Red Team → Quirk Triage → Reporter
```

Each stage is an autonomous agent powered by Muse Spark Open. The model serves as fuzzer, archaeologist, migrator, debugger, and red-team adversary — with a usage ledger tracking every call.

---

## Hackathon

- **Event**: Meta Global AI Developer Hackathon (Cerebral Valley)
- **Track**: Indie Developer — Push the Frontier
- **Builder**: Dev (solo)
- **Built during**: Oct 27 – Nov 4, 2026
