"""Backend API server for Parity.

Provides REST API endpoints to:
- Inspect configuration and provider statuses
- List available legacy C modules and ground-truth specs
- Trigger autonomous migration and verification runs
- Retrieve run histories, golden files, diffs, scorecards, and HTML reports
- Serve the interactive Frontend dashboard
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import PipelineResult
from .pipeline import run_pipeline

app = FastAPI(
    title="Parity API",
    description="Backend API for Autonomous Billing Logic Migration & Parity Verification",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = BASE_DIR / "samples"
RUNS_DIR = BASE_DIR / "runs"
FRONTEND_DIR = BASE_DIR / "frontend"


class RunRequest(BaseModel):
    module_name: str = "tiered_pricing.c"
    seed: int = 42
    skip_redteam: bool = False
    custom_c_code: Optional[str] = None


@app.get("/api/status")
def get_status() -> dict[str, Any]:
    """Return backend status and provider configuration."""
    providers = os.getenv("PARITY_PROVIDERS", "mock").split(",")
    return {
        "status": "online",
        "primary_model": os.getenv("BASETEN_MODEL_ID", "muse-spark-open-1026"),
        "providers": [p.strip() for p in providers],
        "mock_mode": "mock" in providers or not os.getenv("BASETEN_API_KEY"),
        "providers_status": {
            "mock": {"available": True, "note": "Always active fallback for local zero-API demo"},
            "baseten": {
                "available": bool(os.getenv("BASETEN_API_KEY")),
                "model": os.getenv("BASETEN_MODEL_ID", "muse-spark-open-1026"),
            },
            "modal": {
                "available": bool(os.getenv("MODAL_API_KEY")),
            },
            "fireworks": {
                "available": bool(os.getenv("FIREWORKS_API_KEY")),
            },
        },
    }


@app.get("/api/modules")
def list_modules() -> list[dict[str, Any]]:
    """List available legacy C modules with descriptions and ground truth."""
    legacy_dir = SAMPLES_DIR / "legacy"
    expected_dir = SAMPLES_DIR / "expected"

    modules = []
    if legacy_dir.exists():
        for c_file in sorted(legacy_dir.glob("*.c")):
            stem = c_file.stem
            exp_file = expected_dir / f"{stem}.json"
            expected_data = {}
            if exp_file.exists():
                try:
                    expected_data = json.loads(exp_file.read_text(encoding="utf-8"))
                except Exception:
                    pass

            code = c_file.read_text(encoding="utf-8")
            modules.append({
                "filename": c_file.name,
                "name": stem,
                "path": str(c_file),
                "set": expected_data.get("set", "unknown"),
                "planted_quirks": expected_data.get("planted_quirks", []),
                "functions": expected_data.get("functions", []),
                "code": code,
                "lines": len(code.splitlines()),
            })
    return modules


@app.post("/api/run")
def trigger_run(req: RunRequest) -> dict[str, Any]:
    """Execute pipeline run on chosen module or custom code."""
    temp_file: Optional[Path] = None
    try:
        if req.custom_c_code and req.custom_c_code.strip():
            temp_file = Path(tempfile.NamedTemporaryFile("w", suffix=".c", delete=False).name)
            temp_file.write_text(req.custom_c_code, encoding="utf-8")
            target_path = temp_file
        elif req.module_name in ("custom", "custom.c"):
            # Fall back to tiered_pricing.c if user selected custom with empty code
            target_path = SAMPLES_DIR / "legacy" / "tiered_pricing.c"
        else:
            module_name = req.module_name
            if not module_name.endswith(".c"):
                module_name = f"{module_name}.c"
            target_path = SAMPLES_DIR / "legacy" / module_name
            if not target_path.exists():
                matches = list((SAMPLES_DIR / "legacy").glob(f"*{req.module_name}*"))
                if matches:
                    target_path = matches[0]
                else:
                    raise HTTPException(status_code=404, detail=f"Module '{req.module_name}' not found")

        result: PipelineResult = run_pipeline(
            source_path=target_path,
            seed=req.seed,
            skip_redteam=req.skip_redteam,
        )

        run_id = result.run_dir.name if result.run_dir else "latest"

        return {
            "success": True,
            "run_id": run_id,
            "module_name": result.module_name,
            "first_pass_match_rate": result.first_pass_match_rate,
            "final_match_rate": result.final_match_rate,
            "held_out_match_rate": result.held_out_match_rate,
            "adversarial_breaks": result.adversarial_breaks,
            "total_inputs": result.total_inputs,
            "golden_hash": result.golden_hash,
            "repair_rounds": result.repair_rounds,
            "quirks": [
                {
                    "behavior": q.behavior,
                    "label": q.label.value,
                    "evidence": q.evidence,
                    "recommended_action": q.recommended_action,
                }
                for q in result.quirks
            ],
            "behavior_contract": result.behavior_contract,
            "migrated_code": result.migrated_code,
            "legacy_code": result.legacy_code,
            "wall_clock_seconds": result.wall_clock_seconds,
            "total_cost_usd": result.total_cost_usd,
            "report_url": f"/api/runs/{run_id}/report",
            "scorecard_url": f"/api/runs/{run_id}/scorecard",
        }
    finally:
        if temp_file and temp_file.exists():
            temp_file.unlink()


@app.post("/api/evaluate")
def evaluate_all(seed: int = 42) -> dict[str, Any]:
    """Execute evaluation across all sample modules and return summary."""
    legacy_dir = SAMPLES_DIR / "legacy"
    results = []
    for c_file in sorted(legacy_dir.glob("*.c")):
        try:
            res = run_pipeline(source_path=c_file, seed=seed)
            results.append({
                "module_name": c_file.name,
                "first_pass_match_rate": res.first_pass_match_rate,
                "final_match_rate": res.final_match_rate,
                "held_out_match_rate": res.held_out_match_rate,
                "adversarial_breaks": res.adversarial_breaks,
                "total_inputs": res.total_inputs,
                "repair_rounds": res.repair_rounds,
                "wall_clock_seconds": res.wall_clock_seconds,
                "run_id": res.run_dir.name if res.run_dir else "latest",
            })
        except Exception as e:
            results.append({
                "module_name": c_file.name,
                "error": str(e),
                "final_match_rate": 0.0,
            })
    return {
        "success": True,
        "results": results,
        "modules_evaluated": len(results),
        "mean_final_parity": sum(r.get("final_match_rate", 0) for r in results) / max(len(results), 1),
    }


@app.get("/api/runs")
def list_runs() -> list[dict[str, Any]]:
    """List previously executed runs."""
    if not RUNS_DIR.exists():
        return []

    runs = []
    for r_dir in sorted(RUNS_DIR.iterdir(), reverse=True):
        if not r_dir.is_dir() or r_dir.name.startswith("."):
            continue
        report_json = r_dir / "report.json"
        if report_json.exists():
            try:
                data = json.loads(report_json.read_text(encoding="utf-8"))
                runs.append({
                    "run_id": r_dir.name,
                    "module_name": data.get("module_name", r_dir.name),
                    "final_match_rate": data.get("final_match_rate", 0.0),
                    "first_pass_match_rate": data.get("first_pass_match_rate", 0.0),
                    "held_out_match_rate": data.get("held_out_match_rate", 0.0),
                    "total_inputs": data.get("total_inputs", 0),
                    "timestamp": r_dir.name.split("_")[0] if "_" in r_dir.name else "",
                })
            except Exception:
                pass
    return runs


@app.get("/api/runs/{run_id}/report")
def get_run_report(run_id: str):
    """Serve HTML report for a specific run."""
    report_file = RUNS_DIR / run_id / "report.html"
    if not report_file.exists():
        raise HTTPException(status_code=404, detail="Report HTML not found for run")
    return HTMLResponse(content=report_file.read_text(encoding="utf-8"))


@app.get("/api/runs/{run_id}/scorecard")
def get_run_scorecard(run_id: str):
    """Serve Scorecard HTML for a specific run."""
    scorecard_file = RUNS_DIR / run_id / "scorecard.html"
    if not scorecard_file.exists():
        raise HTTPException(status_code=404, detail="Scorecard HTML not found for run")
    return HTMLResponse(content=scorecard_file.read_text(encoding="utf-8"))


# Mount frontend static directory if exists
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
