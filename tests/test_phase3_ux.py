"""Phase 3: roster cards, departments expansion, market enrichment."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402


client = TestClient(app)


def test_workforce_roster_idle_label() -> None:
    resp = client.get("/api/v1/veridiq/workforce/roster")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 19
    assert data["idle_label"] == "Waiting for Assignment"
    for card in data["cards"]:
        assert card["status"] in {"idle", "working"}
        if card["status"] == "idle":
            assert card["status_label"] == "Waiting for Assignment"
            assert card["current_task"] is None
            assert card["tokens_processed"] is None


def test_departments_include_new_teams() -> None:
    data = client.get("/api/v1/veridiq/departments").json()
    ids = {d["id"] for d in data["departments"]}
    assert "marketing" in ids
    assert "customer_success" in ids
    assert "influencer_intelligence" in ids


def test_agent_profile_has_department_and_bio() -> None:
    agents = client.get("/api/v1/veridiq/agents").json()["agents"]
    sample = agents[0]["agent_type"]
    detail = client.get(f"/api/v1/veridiq/agents/{sample}").json()
    assert detail["status_label"] in {"Waiting for Assignment", "Working"}
    assert "biography" in detail
    assert "backend_services" in detail


def test_market_enrichment_fields() -> None:
    data = client.get("/api/v1/veridiq/market").json()
    assert "connectors" in data
    if data.get("status") == "ok":
        assert "dominance" in data
        assert "volatility" in data
        assert "liquidity" in data
        assert "binance_public" in data
