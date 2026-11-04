#!/usr/bin/env bash
# Parity Demo Script — Autonomous Migration & Equivalence Verification
# Meta Global AI Developer Hackathon 2026

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

echo "============================================================"
echo "  Parity — Autonomous Billing Code Verification Demo"
echo "  Powered by Muse Spark Open (Meta Open Weights)"
echo "============================================================"
echo ""

# Ensure virtual environment is active if present
if [ -d ".venv" ]; then
    PYTHON_EXEC=".venv/bin/python3"
else
    PYTHON_EXEC="python3"
fi

# Run configuration check
PYTHONPATH=. "$PYTHON_EXEC" -m backend.cli info

echo ""
echo "▶ Running autonomous verification on development module: tiered_pricing.c..."
echo ""

# Run pipeline on tiered_pricing.c
PYTHONPATH=. "$PYTHON_EXEC" -m backend.cli run samples/legacy/tiered_pricing.c --seed 42

echo ""
echo "============================================================"
echo "✔ Demo run complete!"
echo "  - Check runs/ for latest artifacts, golden files, and HTML reports"
echo "  - Start the interactive dashboard anytime with: parity serve"
echo "============================================================"
