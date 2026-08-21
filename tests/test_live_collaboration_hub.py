"""Live Collaboration Hub — threads, invites, personal meeting request."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("VERIDIQ_LIVEKIT_URL", "wss://example.livekit.cloud")
os.environ.setdefault("VERIDIQ_LIVEKIT_API_KEY", "APItestkey")
os.environ.setdefault("VERIDIQ_LIVEKIT_API_SECRET", "testsecret_for_jwt_signing_only_32b")
os.environ.setdefault("LIVEKIT_URL", os.environ["VERIDIQ_LIVEKIT_URL"])
os.environ.setdefault("LIVEKIT_API_KEY", os.environ["VERIDIQ_LIVEKIT_API_KEY"])
os.environ.setdefault("LIVEKIT_API_SECRET", os.environ["VERIDIQ_LIVEKIT_API_SECRET"])


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "live_hub_test.db"
    monkeypatch.setenv("VERIDIQ_LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("VERIDIQ_LIVEKIT_API_KEY", "APItestkey")
    monkeypatch.setenv("VERIDIQ_LIVEKIT_API_SECRET", "testsecret_for_jwt_signing_only_32b")
    monkeypatch.delenv("VERIDIQ_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("BOT_TOKEN", raising=False)

    import database

    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.initialize_database(db_file)

    from app import app

    return TestClient(app)


def test_hub_get_never_500_returns_live_threads(client):
    resp = client.get("/api/v1/veridiq/calling/meetings/hub")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("ok") is not False
    assert "live_threads" in data
    assert isinstance(data["live_threads"], list)
    assert data.get("user_can_chat") is False
    assert data.get("observer_mode") is True


def test_start_conversation_seeds_live_thread(client):
    resp = client.post("/api/v1/veridiq/calling/meetings/hub/start-conversation?force=true")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data.get("live_threads") or []) >= 1
    # Swarm should expose many rooms
    assert (data.get("swarm") or {}).get("live_threads_target", 24) >= 20 or len(data["live_threads"]) >= 8
    # Detail endpoint carries full messages
    tid = data["live_threads"][0]["thread_id"]
    detail = client.get(f"/api/v1/veridiq/calling/hub/threads/{tid}")
    assert detail.status_code == 200
    assert len(detail.json().get("messages") or []) >= 1


def test_hub_swarm_counts(client):
    resp = client.get("/api/v1/veridiq/calling/hub/threads")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 8
    swarm = data.get("swarm") or {}
    assert swarm.get("unique_agents", 0) >= 20 or swarm.get("unique_agents_online", 0) >= 10
    assert data.get("user_can_chat") is False
    assert data.get("poll_hint_ms") == 1000


def test_hub_compose_routes_guide_and_postings(client, monkeypatch):
    """Collab hub compose is allowed; creative intents bridge to postings HTTP."""
    from veridiq.calling import collab_postings_bridge as bridge

    def _fake_http(*, message: str, timeout_sec: float = 90.0):
        return {
            "ok": True,
            "status": "posted_via_http",
            "http_status": 200,
            "response": {
                "ok": True,
                "reply": f"Drafted a Verdiq post from: {message[:80]}",
                "image_url": "/media/fake-post.png",
            },
        }

    monkeypatch.setattr(bridge, "_http_postings_agent", _fake_http)

    # DM-first: bare compose opens Marcus DM and replies as the agent
    guide = client.post(
        "/api/v1/veridiq/calling/meetings/hub/messages",
        json={"body": "hello agents"},
    )
    assert guide.status_code == 200, guide.text
    gbody = guide.json()
    assert gbody["ok"] is True
    assert gbody.get("routed") in ("dm", "guide")
    assert gbody.get("thread_id")

    post = client.post(
        "/api/v1/veridiq/calling/meetings/hub/messages",
        json={"body": "create a post for my verdiq launch"},
    )
    assert post.status_code == 200, post.text
    pdata = post.json()
    assert pdata["ok"] is True
    assert pdata.get("routed") == "postings"
    assert pdata.get("reply", {}).get("sender_name") == "Mira" or "Mira" in (
        pdata.get("reply") or {}
    ).get("body", "")
    assert pdata.get("postings", {}).get("ok") is True


def test_hub_dms_list_and_open_separate_chats(client):
    """Each workforce agent gets a dedicated 1:1 DM thread."""
    listing = client.get("/api/v1/veridiq/calling/hub/dms")
    assert listing.status_code == 200, listing.text
    data = listing.json()
    assert data.get("dm_first") is True
    assert data.get("user_can_chat") is True
    agents = data.get("agents") or []
    assert len(agents) >= 10
    names = {a.get("name") for a in agents}
    assert {"Aurelia", "Marcus", "Mira"} <= names

    threads = {}
    for agent_type in ("ceo", "ai_calling", "posting_studio"):
        opened = client.post(
            "/api/v1/veridiq/calling/hub/dms/open",
            json={"agent_type": agent_type},
        )
        assert opened.status_code == 200, opened.text
        body = opened.json()
        assert body.get("ok") is True
        assert body.get("is_dm") is True
        tid = body["thread"]["thread_id"]
        threads[agent_type] = tid
        assert len(body.get("messages") or []) >= 1

    assert len(set(threads.values())) == 3

    for agent_type, tid in threads.items():
        msg = client.post(
            "/api/v1/veridiq/calling/meetings/hub/messages",
            json={"body": f"ping {agent_type}", "thread_id": tid},
        )
        assert msg.status_code == 200, msg.text
        assert msg.json().get("routed") == "dm"
        assert msg.json().get("thread_id") == tid

    # Re-open returns same thread ids
    for agent_type, tid in threads.items():
        again = client.post(
            "/api/v1/veridiq/calling/hub/dms/open",
            json={"agent_type": agent_type},
        )
        assert again.json()["thread"]["thread_id"] == tid


def test_personal_meeting_request_invite_accept(client):
    req = client.post(
        "/api/v1/veridiq/calling/hub/request-personal-meeting",
        json={"specialist_query": "canva daily posts", "topic": "Logo tweak session"},
    )
    assert req.status_code == 200, req.text
    body = req.json()
    assert body["ok"] is True
    invite = body["invite"]
    assert invite["status"] == "pending"
    assert invite["invite_id"]

    threads = client.get("/api/v1/veridiq/calling/hub/threads")
    assert threads.status_code == 200
    assert threads.json()["count"] >= 1

    acc = client.post(f"/api/v1/veridiq/calling/hub/invites/{invite['invite_id']}/accept")
    assert acc.status_code == 200, acc.text
    accepted = acc.json()
    assert accepted["ok"] is True
    meeting = accepted["meeting"]
    assert meeting["status"] == "live"
    assert meeting["join_gate_status"] == "admitted"
    assert accepted["join_path"].startswith("/dashboard/calling")
    assert accepted.get("auto_connect") is False

    # Admitted user can mint token — but must join explicitly (no auto LiveKit)
    tok = client.post(
        "/api/v1/veridiq/calling/livekit/token",
        json={"meeting_id": meeting["meeting_id"], "identity": "user-1", "name": "You", "role": "user"},
    )
    assert tok.status_code == 200, tok.text
    assert tok.json()["ok"] is True

    # Work chat in admitted meeting
    chat = client.post(
        "/api/v1/veridiq/calling/meetings/hub/messages",
        json={"body": "Please change the Canva post logo", "meeting_id": meeting["meeting_id"]},
    )
    assert chat.status_code == 200, chat.text
    assert chat.json()["ok"] is True
    assert "logo" in (chat.json().get("reply") or {}).get("body", "").lower() or chat.json().get("reply")


def test_calling_agent_personal_meeting_intent(client):
    resp = client.post(
        "/api/v1/veridiq/calling/agent",
        json={"message": "Please arrange a personal meeting with the Canva daily posts agent"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["intent"] == "request_personal_meeting"
    assert data["action"]["action"] == "request_personal_meeting"
    assert data["action"].get("invite")
