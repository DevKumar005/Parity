"""Tests for Parity FastAPI Server endpoints."""

from fastapi.testclient import TestClient
from backend.server import app

client = TestClient(app)


def test_api_status():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "mock" in data["providers_status"]


def test_api_modules():
    response = client.get("/api/modules")
    assert response.status_code == 200
    modules = response.json()
    assert len(modules) >= 3
    names = [m["name"] for m in modules]
    assert "tiered_pricing" in names
    assert "invoice_total" in names
    assert "proration" in names


def test_api_run_tiered_pricing():
    response = client.post(
        "/api/run",
        json={"module_name": "tiered_pricing.c", "seed": 42, "skip_redteam": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["final_match_rate"] == 1.0
    assert "run_id" in data
    assert "migrated_code" in data

