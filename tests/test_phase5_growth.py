"""VERIDIQ Phase 5 — expanded departments, AI Calling, and Live Agent Runtime.

Honesty checks: no fabricated live activity, no auto-dialing, browser runtime
disabled unless explicitly enabled via env var.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from veridiq.agents import AGENT_REGISTRY, get_agent  # noqa: E402

client = TestClient(app)

NEW_DEPARTMENTS = {"ai_calling", "linkedin", "sales"}
NEW_AGENTS = {"ai_calling", "linkedin_outreach", "sales_intelligence"}


def test_new_agents_are_registered_and_runnable() -> None:
    for agent_type in NEW_AGENTS:
        assert agent_type in AGENT_REGISTRY
        agent = get_agent(agent_type)
        envelope = agent.run({})
        assert envelope["ok"] is True
        assert "status" in envelope["result"] or "summary" in envelope["result"]


def test_departments_endpoint_includes_new_departments() -> None:
    resp = client.get("/api/v1/veridiq/departments")
    assert resp.status_code == 200
    data = resp.json()
    ids = {d["id"] for d in data["departments"]}
    assert NEW_DEPARTMENTS.issubset(ids)


def test_workspace_populates_every_declared_department() -> None:
    """Regression guard: every department in DEPARTMENTS must show its real agent roster
    in the Agent Workspace view, not just departments that happen to be an agent's
    single 'primary' label."""
    resp = client.get("/api/v1/veridiq/workspace")
    assert resp.status_code == 200
    data = resp.json()
    from veridiq.workforce.departments import DEPARTMENTS

    by_id = {d["id"]: d for d in data["departments"]}
    for key, meta in DEPARTMENTS.items():
        dept = by_id.get(key)
        assert dept is not None, f"department {key} missing from workspace"
        agent_types = {a["agent_type"] for a in dept["agents"]}
        assert agent_types == set(meta["agents"]), f"department {key} agent mismatch: {agent_types}"


def test_ai_calling_department_and_agent_present_in_workspace() -> None:
    resp = client.get("/api/v1/veridiq/workspace/ai_calling")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent"]["agent_type"] == "ai_calling"
    assert data["agent"]["department"] is not None


def test_ai_calling_integration_reports_configuration_required_by_default() -> None:
    resp = client.get("/api/v1/veridiq/integrations/ai_calling")
    assert resp.status_code == 200
    data = resp.json()
    if not data["configured"]:
        assert data["status"] == "configuration_required"
        assert "VERIDIQ_TWILIO_ACCOUNT_SID" in data["message"] or any(
            "TWILIO" in v for v in data.get("env_vars", [])
        )


def test_calling_campaign_lifecycle_never_auto_dials() -> None:
    created = client.post(
        "/api/v1/veridiq/calling/campaigns",
        json={"to_number": "+15550001111", "purpose": "test", "script": "Hello from VERIDIQ.", "contact_name": "Test Co"},
    ).json()
    assert created["status"] == "queued_for_approval"
    campaign_id = created["campaign_id"]

    listed = client.get("/api/v1/veridiq/calling/campaigns").json()
    assert any(c["campaign_id"] == campaign_id for c in listed["campaigns"])

    detail = client.get(f"/api/v1/veridiq/calling/campaigns/{campaign_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "queued_for_approval"

    rejected = client.post(f"/api/v1/veridiq/calling/campaigns/{campaign_id}/approve", json={"approved": False}).json()
    assert rejected["campaign"]["status"] == "rejected_by_user"

    missing = client.get("/api/v1/veridiq/calling/campaigns/not-a-real-id")
    assert missing.status_code == 404


def test_calling_approval_without_twilio_never_fabricates_a_dial() -> None:
    twilio_status = client.get("/api/v1/veridiq/integrations/ai_calling").json()
    created = client.post(
        "/api/v1/veridiq/calling/campaigns",
        json={"to_number": "+15550002222", "purpose": "test", "script": "Hello.", "contact_name": "No Twilio"},
    ).json()
    approved = client.post(
        f"/api/v1/veridiq/calling/campaigns/{created['campaign_id']}/approve", json={"approved": True}
    ).json()
    if not twilio_status["configured"]:
        assert approved["campaign"]["status"] == "approved_pending_integration"
        assert approved["campaign"]["call_result"] is None


def test_calling_summary_crm_sync_is_honest_when_unconfigured() -> None:
    crm_status = client.get("/api/v1/veridiq/integrations/crm").json()
    created = client.post(
        "/api/v1/veridiq/calling/campaigns",
        json={"to_number": "+15550003333", "purpose": "test", "script": "Hello.", "contact_name": "CRM Test"},
    ).json()
    result = client.post(
        f"/api/v1/veridiq/calling/campaigns/{created['campaign_id']}/summary", json={"summary": "Call went well."}
    ).json()
    if not crm_status["configured"]:
        assert result["crm_sync"]["status"] == "configuration_required"


def test_calling_followup_uses_comms_approval_gate() -> None:
    created = client.post(
        "/api/v1/veridiq/calling/campaigns",
        json={"to_number": "+15550004444", "purpose": "test", "script": "Hello.", "contact_name": "Followup Test"},
    ).json()
    result = client.post(
        f"/api/v1/veridiq/calling/campaigns/{created['campaign_id']}/followup",
        json={"recipient_email": "person@example.com"},
    ).json()
    assert result["ok"] is True
    assert result["draft"]["requires_approval_before_send"] is True
    assert result["draft"]["external_action_status"] == "draft_only"


def test_runtime_status_disabled_by_default() -> None:
    resp = client.get("/api/v1/veridiq/runtime/status")
    assert resp.status_code == 200
    data = resp.json()
    import os

    if os.getenv("VERIDIQ_BROWSER_RUNTIME") != "1":
        assert data["enabled"] is False
        assert data["status"] == "disabled"


def test_runtime_browser_session_disabled_never_fabricates_a_capture() -> None:
    import os

    if os.getenv("VERIDIQ_BROWSER_RUNTIME") == "1":
        return
    resp = client.post("/api/v1/veridiq/runtime/browser-session", json={"url": "https://example.com"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "disabled"

    missing_image = client.get("/api/v1/veridiq/runtime/browser-session/not-a-real-session")
    assert missing_image.status_code == 404


def test_runtime_jobs_endpoint_shape() -> None:
    resp = client.get("/api/v1/veridiq/runtime/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["jobs"], list)
    assert data["count"] == len(data["jobs"])
