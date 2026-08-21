"""Agent Workspace + Platform Integrations — shape, honesty, and no-fabrication checks."""

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

# Platforms that require credentials we never set in the test environment.
UNCONFIGURED_BY_DEFAULT = {"linkedin", "x_twitter", "instagram", "threads", "whatsapp", "crm", "marketing"}


def test_workspace_returns_departments_with_agents() -> None:
    resp = client.get("/api/v1/veridiq/workspace")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 19
    assert data["idle_label"] == "Waiting for Assignment"
    assert isinstance(data["departments"], list) and data["departments"]
    assert isinstance(data["agents"], list) and data["agents"]

    dept = next(d for d in data["departments"] if d["id"] == "market_intelligence")
    assert dept["name"] == "Market Intelligence"
    assert isinstance(dept["agents"], list)
    for agent in dept["agents"]:
        assert agent["department"]["id"] == "market_intelligence"

    sample = data["agents"][0]
    for field in (
        "agent_type",
        "name",
        "department",
        "role",
        "email",
        "avatar_hue",
        "status",
        "status_label",
        "current_task",
        "task_queue",
        "live_logs",
        "platform_activity",
        "connected_apis",
        "activity_history",
        "langgraph_nodes",
        "workflow_state",
        "metrics",
        "last_completed_task",
    ):
        assert field in sample, f"missing field {field}"

    # Never fabricate — idle agents must show empty/None operational fields.
    for agent in data["agents"]:
        if agent["status"] == "idle":
            assert agent["current_task"] is None
            assert agent["task_queue"] == []
            assert agent["status_label"] == "Waiting for Assignment"


def test_workspace_single_agent_detail_and_unknown_agent() -> None:
    sample_type = sorted(AGENT_REGISTRY.keys())[0]
    resp = client.get(f"/api/v1/veridiq/workspace/{sample_type}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["agent"]["agent_type"] == sample_type
    assert len(data["departments"]) <= 1

    missing = client.get("/api/v1/veridiq/workspace/not_a_real_agent")
    assert missing.status_code == 404


def test_integrations_status_board_shape() -> None:
    resp = client.get("/api/v1/veridiq/integrations")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 15
    platforms = {i["platform"] for i in data["integrations"]}
    for expected in (
        "linkedin",
        "x_twitter",
        "instagram",
        "threads",
        "telegram",
        "whatsapp",
        "email",
        "crm",
        "marketing",
        "news_newsapi",
        "jobs_remotive",
        "market_coingecko",
        "market_binance",
        "blockchain",
    ):
        assert expected in platforms, f"missing platform {expected}"

    for item in data["integrations"]:
        assert item["status"] in {
            "ok",
            "configured",
            "configuration_required",
            "unavailable",
            "error",
            "public",
        }
        assert isinstance(item.get("env_vars"), list)
        if item["status"] == "configuration_required":
            assert item["configured"] is False
            assert item.get("message"), "configuration_required must explain which env vars to set"


def test_unconfigured_platforms_report_configuration_required() -> None:
    data = client.get("/api/v1/veridiq/integrations").json()
    by_platform = {i["platform"]: i for i in data["integrations"]}
    for platform in UNCONFIGURED_BY_DEFAULT:
        item = by_platform[platform]
        # Only assert configuration_required when credentials are genuinely absent
        # (keeps the test honest if a developer's shell happens to export one).
        if not item["configured"]:
            assert item["status"] == "configuration_required"


def test_integration_detail_and_unknown_platform() -> None:
    resp = client.get("/api/v1/veridiq/integrations/telegram")
    assert resp.status_code == 200
    assert resp.json()["platform"] == "telegram"

    missing = client.get("/api/v1/veridiq/integrations/not_a_real_platform")
    assert missing.status_code == 404


def test_test_endpoint_never_fabricates_success_when_unconfigured() -> None:
    resp = client.post("/api/v1/veridiq/integrations/linkedin/test")
    assert resp.status_code == 200
    data = resp.json()
    status_data = client.get("/api/v1/veridiq/integrations/linkedin").json()
    if not status_data["configured"]:
        assert data["status"] == "configuration_required"

    activity = client.get("/api/v1/veridiq/integrations/activity", params={"platform": "linkedin"}).json()
    if activity["count"] and not status_data["configured"]:
        assert activity["activity"][0]["completion_status"] != "completed"


def test_integrations_activity_never_simulated_when_empty() -> None:
    resp = client.get("/api/v1/veridiq/integrations/activity", params={"platform": "a_platform_with_no_events"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0
    assert data["activity"] == []
    assert "never simulated" in data["note"].lower() or "not simulated" in data["note"].lower()


def test_comms_approval_still_works_without_smtp_configured() -> None:
    draft = client.post(
        "/api/v1/veridiq/comms/draft",
        json={"kind": "email", "context": "Workspace integration smoke test", "recipient_hint": "person@example.com"},
    ).json()
    approved = client.post(
        "/api/v1/veridiq/comms/approve",
        json={"draft_id": draft["draft_id"], "approved": True, "channel": "email"},
    ).json()
    assert approved["ok"] is True
    email_status = client.get("/api/v1/veridiq/integrations/email").json()
    if not email_status["configured"]:
        assert approved["status"] == "approved_pending_integration"
