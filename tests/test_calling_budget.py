"""Timed calling budget — per-call max + daily total."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("VERIDIQ_TEST_MODE", "1")
os.environ.setdefault("VERIDIQ_CALLING_WORKER", "0")  # tests drive ticks manually
os.environ["VERIDIQ_CALLING_MAX_SECONDS"] = "5"
os.environ["VERIDIQ_CALLING_DAILY_BUDGET_SECONDS"] = "8"


@pytest.fixture()
def unique_user():
    return f"test-{os.getpid()}-{time.time_ns()}"


def test_clamp_respects_per_call_and_daily(unique_user, monkeypatch):
    monkeypatch.setenv("VERIDIQ_CALLING_MAX_SECONDS", "5")
    monkeypatch.setenv("VERIDIQ_CALLING_DAILY_BUDGET_SECONDS", "8")
    from veridiq.calling import budget as calling_budget

    # Reload helpers pick env each call
    clamp = calling_budget.clamp_requested_seconds(120, agent_type="ai_calling", user_key=unique_user)
    assert clamp["ok"] is True
    assert clamp["allowed_seconds"] == 5  # per-call max wins over requested 120
    assert clamp["daily_budget_seconds"] == 8

    calling_budget.record_consumption(seconds=6, agent_type="ai_calling", user_key=unique_user)
    clamp2 = calling_budget.clamp_requested_seconds(5, agent_type="ai_calling", user_key=unique_user)
    assert clamp2["allowed_seconds"] == 2  # 8-6 remaining
    calling_budget.record_consumption(seconds=2, agent_type="ai_calling", user_key=unique_user)
    clamp3 = calling_budget.clamp_requested_seconds(5, agent_type="ai_calling", user_key=unique_user)
    assert clamp3["ok"] is False
    assert clamp3["allowed_seconds"] == 0


def test_timed_session_lifecycle_and_auto_expire(unique_user, monkeypatch):
    monkeypatch.setenv("VERIDIQ_CALLING_MAX_SECONDS", "2")
    monkeypatch.setenv("VERIDIQ_CALLING_DAILY_BUDGET_SECONDS", "10")
    from veridiq.calling.timed_calls import end_session, schedule_timed_call, start_session, tick_active_sessions

    scheduled = schedule_timed_call(
        purpose="unit test call",
        requested_seconds=30,
        agent_type="ai_calling",
        user_key=unique_user,
        record_chain=True,
    )
    assert scheduled["ok"] is True
    sid = scheduled["session"]["session_id"]
    assert scheduled["session"]["allowed_seconds"] == 2
    assert scheduled.get("chain", {}).get("ok") is True

    started = start_session(sid)
    assert started["ok"] is True
    assert started["session"]["status"] == "active"

    # Force timeout by ending with budget_timeout path via tick after sleeping past allowed
    time.sleep(2.2)
    tick = tick_active_sessions()
    assert tick["closed_count"] >= 1
    ended = end_session(sid)  # idempotent
    assert ended["session"]["status"] in {"expired", "completed"}
    assert float(ended["session"]["consumed_seconds"]) > 0


def test_calling_budget_api_endpoints(unique_user):
    # Import app after env is set
    from app import app

    client = TestClient(app)
    resp = client.get("/api/v1/veridiq/calling/budget", params={"user_key": unique_user})
    assert resp.status_code == 200
    data = resp.json()
    assert "daily_budget_seconds" in data
    assert "per_call_max_seconds" in data

    create = client.post(
        "/api/v1/veridiq/calling/timed",
        json={
            "purpose": "api timed call",
            "requested_seconds": 120,
            "user_key": unique_user,
            "auto_start": True,
            "record_chain": True,
        },
    )
    assert create.status_code == 200
    body = create.json()
    assert body.get("ok") is True
    session = body.get("session") or {}
    assert session.get("session_id")
    assert session.get("status") in {"active", "scheduled", "budget_blocked"}

    detail = client.get(f"/api/v1/veridiq/calling/timed/{session['session_id']}")
    assert detail.status_code == 200

    # Health + postings persona must stay up (smoke)
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    postings = client.get("/api/v1/veridiq/postings/agent")
    assert postings.status_code == 200


def test_budget_reset_and_cancel_uncharged(unique_user, monkeypatch):
    monkeypatch.setenv("VERIDIQ_CALLING_MAX_SECONDS", "5")
    monkeypatch.setenv("VERIDIQ_CALLING_DAILY_BUDGET_SECONDS", "8")
    from veridiq.calling import budget as calling_budget
    from veridiq.calling.timed_calls import end_session, schedule_timed_call

    calling_budget.record_consumption(seconds=8, agent_type="ai_calling", user_key=unique_user)
    assert calling_budget.remaining_budget_seconds(user_key=unique_user)["can_start_call"] is False

    reset = calling_budget.reset_daily_budget(agent_type="ai_calling", user_key=unique_user)
    assert reset["ok"] is True
    assert reset["remaining_seconds"] >= 8

    scheduled = schedule_timed_call(
        purpose="never connected",
        requested_seconds=5,
        agent_type="ai_calling",
        user_key=unique_user,
        record_chain=False,
    )
    assert scheduled["ok"] is True
    sid = scheduled["session"]["session_id"]
    cancelled = end_session(sid, reason="cancelled", consumed_override=0.0)
    assert cancelled["ok"] is True
    assert float(cancelled["consumed_seconds"]) == 0.0
    assert calling_budget.get_daily_consumed(user_key=unique_user) == 0.0

    from app import app

    client = TestClient(app)
    api_reset = client.post("/api/v1/veridiq/calling/budget/reset", params={"user_key": unique_user})
    assert api_reset.status_code == 200
    assert api_reset.json().get("ok") is True


def test_ai_calling_agent_schedule_action(unique_user, monkeypatch):
    monkeypatch.setenv("VERIDIQ_CALLING_MAX_SECONDS", "5")
    monkeypatch.setenv("VERIDIQ_CALLING_DAILY_BUDGET_SECONDS", "20")
    from veridiq.agents import get_agent

    out = get_agent("ai_calling").process(
        {
            "action": "schedule_timed_call",
            "purpose": "agent schedule",
            "user_key": unique_user,
            "requested_seconds": 5,
            "auto_start": True,
        }
    )
    assert out.get("budget")
    assert out.get("timed_result", {}).get("ok") is True
    assert "Timed budget" in (out.get("summary") or "")
