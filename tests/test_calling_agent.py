"""AI Calling command agent — Call → Marcus → marketing / influencer actions."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("VERIDIQ_TEST_MODE", "1")

from app import app  # noqa: E402
from veridiq.calling.agent import handle_command, parse_intent  # noqa: E402

client = TestClient(app)


def test_calling_agent_persona_endpoint():
    resp = client.get("/api/v1/veridiq/calling/agent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "command_agent"
    assert data["agent"]["name"] == "Marcus"
    assert data["agent"]["agent_type"] == "ai_calling"
    assert "llm" in data


def test_keyword_intent_marketing():
    parsed = parse_intent("Run marketing agencies")
    assert parsed["intent"] == "run_marketing"


def test_keyword_intent_influencer():
    parsed = parse_intent("Command influencer")
    assert parsed["intent"] == "run_influencer"


def test_keyword_intent_research():
    parsed = parse_intent("Research influencers in AI verification")
    assert parsed["intent"] == "influencer_research"
    assert "ai verification" in (parsed.get("query") or "").lower() or parsed.get("query")


def test_handle_command_help_offline():
    result = handle_command("what can you do")
    assert result["ok"] is True
    assert result["intent"] == "help"
    assert result["agent"]["name"] == "Marcus"
    assert any(l.get("href") == "/dashboard/runtime" for l in result.get("links") or [])


def test_post_run_marketing_via_calling_agent():
    """Marketing command must hit the real team-run path (started agents or honest skip)."""
    resp = client.post("/api/v1/veridiq/calling/agent", json={"message": "Run marketing agencies"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "run_marketing"
    assert data["action"] is not None
    assert data["action"]["action"] == "run_marketing"
    assert data["action"].get("campaign_id")
    # Either agents started or were skipped (stopped) — never a fake success without campaign
    assert data["action"]["status"] in {"started", "skipped"}
    hrefs = [l["href"] for l in data.get("links") or []]
    assert "/dashboard/runtime" in hrefs


def test_post_run_influencer_via_calling_agent():
    resp = client.post("/api/v1/veridiq/calling/agent", json={"message": "Command influencer"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "run_influencer"
    assert data["action"]["action"] == "run_influencer"
    assert data["action"].get("status") in {"started", "skipped", "queued", "running", "ok"} or data["action"].get("ok") is not None


def test_legacy_calling_campaigns_still_exist():
    """Twilio campaign API remains for tests/integrations; UI no longer surfaces it."""
    resp = client.get("/api/v1/veridiq/calling/campaigns")
    assert resp.status_code == 200
    assert "campaigns" in resp.json()
