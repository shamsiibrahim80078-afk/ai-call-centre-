"""Phase 2: command center, collaboration, departments, market, requests, comms."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from veridiq.agents import AGENT_REGISTRY  # noqa: E402


client = TestClient(app)


def test_connectivity_includes_market_agents() -> None:
    resp = client.get("/api/v1/veridiq/agents/connectivity")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    # Standalone growth specialists (AI Calling, LinkedIn, Sales) act through their own
    # integration + approval gates rather than the truth/market LangGraph pipelines.
    assert data["wired_count"] + len(data.get("standalone_agents", [])) == len(AGENT_REGISTRY)
    assert "market_research" in data["wired_to_langgraph"]


def test_command_center_and_departments() -> None:
    cc = client.get("/api/v1/veridiq/command-center").json()
    assert "workforce" in cc
    assert "departments" in cc
    assert cc["status_label"] == "Waiting for Tasks"
    depts = client.get("/api/v1/veridiq/departments").json()
    assert depts["count"] >= 8
    assert any(d["id"] == "market_intelligence" for d in depts["departments"])


def test_collaboration_hub_records_real_events() -> None:
    before = client.get("/api/v1/veridiq/collaboration").json()["count"]
    plan = client.get("/api/v1/veridiq/orchestrator/plan", params={"text": "Verify this speech claim"}).json()
    assert plan["intent"] == "verify"
    # market run generates collaboration messages
    req = client.post(
        "/api/v1/veridiq/requests",
        json={"text": "Analyze today's crypto market", "async_mode": False},
    )
    assert req.status_code == 200
    body = req.json()
    assert body["mode"] == "market"
    assert "disclaimer" in (body.get("result") or {})
    after = client.get("/api/v1/veridiq/collaboration").json()
    assert after["count"] >= before
    assert after["messages"]
    assert "fabricated" not in (after.get("note") or "").lower() or "not fabricated" in (after.get("note") or "").lower()


def test_market_endpoint_official_or_unavailable() -> None:
    resp = client.get("/api/v1/veridiq/market")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "CoinGecko"
    assert data["status"] in {"ok", "unavailable"}
    if data["status"] != "ok":
        assert data["count"] == 0


def test_comms_requires_approval() -> None:
    draft = client.post(
        "/api/v1/veridiq/comms/draft",
        json={"kind": "email", "context": "Introduce VERIDIQ diligence follow-up"},
    ).json()
    assert draft["requires_approval_before_send"] is True
    assert draft["external_action_status"] == "draft_only"
    approved = client.post(
        "/api/v1/veridiq/comms/approve",
        json={"draft_id": draft["draft_id"], "approved": True},
    ).json()
    assert approved["ok"] is True
    assert approved["status"] == "approved_pending_integration"
