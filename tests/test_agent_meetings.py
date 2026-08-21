"""Agent↔agent meetings — propose → approve → countdown → start state machine."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("VERIDIQ_LIVEKIT_URL", "wss://example.livekit.cloud")
os.environ.setdefault("VERIDIQ_LIVEKIT_API_KEY", "APItestkey")
os.environ.setdefault("VERIDIQ_LIVEKIT_API_SECRET", "testsecret_for_jwt_signing_only_32b")
os.environ.setdefault("VERIDIQ_AGENT_MEET_COUNTDOWN_SECONDS", "10")
os.environ.setdefault("VERIDIQ_AGENT_MEET_DURATION_SECONDS", "120")
os.environ.setdefault("VERIDIQ_AGENT_MEET_EXTENDED_SECONDS", "300")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "agent_meet_test.db"
    monkeypatch.setenv("VERIDIQ_LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("VERIDIQ_LIVEKIT_API_KEY", "APItestkey")
    monkeypatch.setenv("VERIDIQ_LIVEKIT_API_SECRET", "testsecret_for_jwt_signing_only_32b")
    monkeypatch.setenv("VERIDIQ_AGENT_MEET_COUNTDOWN_SECONDS", "10")
    monkeypatch.setenv("VERIDIQ_AGENT_MEET_DURATION_SECONDS", "120")
    monkeypatch.setenv("VERIDIQ_AGENT_MEET_EXTENDED_SECONDS", "300")
    monkeypatch.setenv("VERIDIQ_CALLING_BUDGET_RESET", "1")
    monkeypatch.delenv("VERIDIQ_TELEGRAM_BOT_TOKEN", raising=False)

    import database

    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.initialize_database(db_file)

    from veridiq.calling import agent_meetings as am
    from veridiq.calling import agent_presence as ap

    def _fake_tts(script, *, meeting_id, agent_type="ai_calling"):
        return {
            "clip_id": f"fake-{agent_type}",
            "meeting_id": meeting_id,
            "audio_url": f"/api/v1/veridiq/calling/agent-tts/fake-{agent_type}",
            "tts": {"ok": True, "status": "fake"},
            "script": script,
        }

    monkeypatch.setattr(ap, "synthesize_greeting", _fake_tts)

    from app import app

    return TestClient(app)


def test_propose_approve_countdown_start(client, monkeypatch):
    from veridiq.calling import agent_meetings as am

    proposed = client.post(
        "/api/v1/veridiq/calling/agent-meetings/propose",
        json={
            "proposer_agent": "x_twitter_voice",
            "invitee_agent": "influencer_relations",
            "topic": "Campaign sync",
            "countdown": 10,
        },
    )
    assert proposed.status_code == 200, proposed.text
    body = proposed.json()
    assert body["ok"] is True
    assert body["proposal"]["status"] == "proposed"
    pid = body["proposal"]["proposal_id"]

    approved = client.post(f"/api/v1/veridiq/calling/agent-meetings/{pid}/approve")
    assert approved.status_code == 200, approved.text
    ab = approved.json()
    assert ab["ok"] is True
    assert ab["proposal"]["status"] == "approved"
    assert ab["proposal"]["countdown_remaining_seconds"] is not None
    assert ab["proposal"]["countdown_remaining_seconds"] <= 10
    assert ab.get("meeting_id")

    # Still in countdown — start without force should 409
    early = client.post(f"/api/v1/veridiq/calling/agent-meetings/{pid}/start")
    assert early.status_code == 409

    # Rewind start_at so countdown elapsed
    past = (datetime.now(timezone.utc) - timedelta(seconds=2)).replace(microsecond=0).isoformat()
    with am._lock:
        from database import db_session

        with db_session() as conn:
            conn.execute(
                "UPDATE veridiq_agent_meetings SET start_at = ? WHERE proposal_id = ?",
                (past, pid),
            )

    started = client.post(f"/api/v1/veridiq/calling/agent-meetings/{pid}/start")
    assert started.status_code == 200, started.text
    sb = started.json()
    assert sb["ok"] is True
    assert sb["status"] == "live" or sb["proposal"]["status"] == "live"
    assert isinstance(sb.get("dialogue") or [], list)
    assert len(sb.get("agent_tokens") or []) >= 1

    # Spectator token
    spec = client.post(f"/api/v1/veridiq/calling/agent-meetings/{pid}/spectator")
    assert spec.status_code == 200, spec.text
    tok = spec.json()
    assert tok["ok"] is True
    assert tok.get("token")
    assert tok.get("role") == "spectator"
    assert tok.get("mute_defaults", {}).get("microphone") is True


def test_tick_advances_approved_to_live(client):
    from veridiq.calling import agent_meetings as am

    r = am.propose_meeting(
        proposer_agent="marketing_manager",
        invitee_agent="influencer_relations",
        topic="Tick test",
        countdown=5,
    )
    pid = r["proposal"]["proposal_id"]
    am.approve_proposal(proposal_id=pid)

    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).replace(microsecond=0).isoformat()
    from database import db_session

    with db_session() as conn:
        conn.execute(
            "UPDATE veridiq_agent_meetings SET start_at = ? WHERE proposal_id = ?",
            (past, pid),
        )

    tick = am.tick_agent_meetings()
    assert pid in tick.get("started", [])
    prop = am.get_proposal(pid)
    assert prop["status"] == "live"


def test_invite_agent_extends_to_300(client):
    from veridiq.calling import agent_meetings as am

    r = am.propose_meeting(
        proposer_agent="x_twitter_voice",
        invitee_agent="influencer_relations",
        topic="Extend test",
        countdown=1,
    )
    pid = r["proposal"]["proposal_id"]
    am.approve_proposal(proposal_id=pid)
    started = am.start_agent_meeting(proposal_id=pid, force=True)
    assert started.get("ok") is True

    inv = client.post(
        f"/api/v1/veridiq/calling/agent-meetings/{pid}/invite-agent",
        json={"agent_type": "marketing_manager"},
    )
    assert inv.status_code == 200, inv.text
    body = inv.json()
    assert body["ok"] is True
    assert body["max_duration_seconds"] == 300
    assert body["proposal"]["extended"] in (1, True)
    types = [p.get("agent_type") for p in body["proposal"]["participants"]]
    assert "marketing_manager" in types


def test_hub_compose_schedule_and_approve_intents(client):
    # Propose via natural language
    propose = client.post(
        "/api/v1/veridiq/calling/meetings/hub/messages",
        json={"body": "I need to schedule a meeting with you about influencers"},
    )
    assert propose.status_code == 200, propose.text
    pb = propose.json()
    assert pb.get("routed") == "agent_meet_propose"

    approve = client.post(
        "/api/v1/veridiq/calling/meetings/hub/messages",
        json={"body": "approved, let's meet"},
    )
    assert approve.status_code == 200, approve.text
    ab = approve.json()
    assert ab.get("routed") == "agent_meet_approve"


def test_external_meet_url_detection():
    from veridiq.calling.agent_meetings import extract_external_meet_url

    assert extract_external_meet_url(
        "go join this meeting: https://meet.google.com/abc-defg-hij"
    ) == "https://meet.google.com/abc-defg-hij"
    assert extract_external_meet_url("hello") is None


def test_force_start_api(client):
    proposed = client.post(
        "/api/v1/veridiq/calling/agent-meetings/propose",
        json={
            "proposer_agent": "ceo",
            "invitee_agent": "ai_calling",
            "topic": "Force start",
            "countdown": 120,
        },
    )
    pid = proposed.json()["proposal"]["proposal_id"]
    client.post(f"/api/v1/veridiq/calling/agent-meetings/{pid}/approve")
    forced = client.post(f"/api/v1/veridiq/calling/agent-meetings/{pid}/start?force=true")
    assert forced.status_code == 200, forced.text
    assert forced.json()["proposal"]["status"] == "live"
