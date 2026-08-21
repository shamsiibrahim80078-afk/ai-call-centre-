"""Tests for VERIDIQ Agent SDK, leadership agents, connectors, and launchpad."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import app
from database import initialize_database
from veridiq.agents import AGENT_REGISTRY, get_agent
from veridiq.sdk import get_sdk
from veridiq.sdk.tools import list_tools
from veridiq.integrations import gmail, github, slack, webrtc_signaling


client = TestClient(app)


def setup_module() -> None:
    initialize_database()


def test_leadership_agents_registered() -> None:
    for key in ("ceo", "director_operations", "director_growth", "director_intelligence"):
        assert key in AGENT_REGISTRY


def test_sdk_send_receive_complete() -> None:
    sdk = get_sdk("ceo")
    sent = sdk.sendTask("director_operations", {"instruction": "ping"}, execute=False)
    assert sent["ok"] is True
    assert sent["task_id"]
    inbox = get_sdk("director_operations").receiveTask(limit=5, claim_only=True)
    assert inbox["ok"] is True
    assert any(t["task_id"] == sent["task_id"] for t in inbox["tasks"])
    done = get_sdk("director_operations").completeTask(
        sent["task_id"], result={"ack": True}, confidence=0.9
    )
    assert done["status"] == "completed"


def test_sdk_share_memory_and_tools() -> None:
    sdk = get_sdk("director_growth")
    saved = sdk.shareMemory("growth_note", {"ready": True}, scope="shared", tags=["test"])
    assert saved["ok"] is True
    loaded = sdk.shareMemory("growth_note", load_only=True, scope="shared")
    assert loaded["value"]["ready"] is True
    tools = list_tools()
    assert "gmail.status" in tools
    assert "webrtc.create_offer" in tools
    probe = sdk.executeTool("gmail.status")
    assert probe["platform"] == "gmail"
    assert probe["status"] == "configuration_required"


def test_ceo_agent_routes_directors() -> None:
    result = get_agent("ceo").run({"instruction": "Align teams on product launch", "execute_directors": False})
    assert result["ok"] is True
    body = result["result"]
    assert len(body["director_assignments"]) == 3
    assert body["confidence"] >= 0.5


def test_connectors_status_honest(monkeypatch) -> None:
    for key in (
        "VERIDIQ_GMAIL_ACCESS_TOKEN",
        "VERIDIQ_GMAIL_CLIENT_ID",
        "VERIDIQ_GMAIL_CLIENT_SECRET",
        "GMAIL_ACCESS_TOKEN",
        "VERIDIQ_GITHUB_TOKEN",
        "GITHUB_TOKEN",
        "VERIDIQ_SLACK_BOT_TOKEN",
        "SLACK_BOT_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
    assert gmail.status()["status"] == "configuration_required"
    assert github.status()["status"] == "configuration_required"
    assert slack.status()["status"] == "configuration_required"
    assert webrtc_signaling.status()["configured"] is True


def test_webrtc_room_api() -> None:
    room = client.post("/api/v1/veridiq/webrtc/rooms", json={"label": "test-voice"}).json()
    assert room["ok"] is True
    offer = client.post(
        "/api/v1/veridiq/webrtc/offer",
        json={"room_id": room["room_id"], "sdp": "v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\n", "from_peer": "agent"},
    ).json()
    assert offer["ok"] is True
    signals = client.get(f"/api/v1/veridiq/webrtc/rooms/{room['room_id']}/signals").json()
    assert signals["count"] >= 1


def test_sdk_api_send_task() -> None:
    resp = client.post(
        "/api/v1/veridiq/sdk/ceo/sendTask",
        json={"to_agent": "director_intelligence", "task": {"instruction": "scan"}, "execute": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["to_agent"] == "director_intelligence"


def test_os_monitor_api() -> None:
    resp = client.get("/api/v1/veridiq/os/monitor?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data
    assert data["count"] >= 1


def test_launchpad_api_and_launch() -> None:
    snap = client.get("/api/v1/veridiq/launchpad").json()
    assert "tokens" in snap
    assert "analytics" in snap
    assert "buy_sell_stream" in snap
    launched = client.post(
        "/api/v1/veridiq/launchpad/launch",
        json={"token_name": "Veridiq Test Token", "token_symbol": "VQT", "network": "Base"},
    )
    assert launched.status_code == 200
    body = launched.json()
    assert body.get("success") is True
    assert body.get("broadcast", {}).get("contract_address")


def test_integrations_include_new_connectors() -> None:
    data = client.get("/api/v1/veridiq/integrations").json()
    platforms = {i["platform"] for i in data.get("integrations") or []}
    for p in ("gmail", "github", "slack", "discord", "browser_playwright", "webrtc_signaling"):
        assert p in platforms


def test_connectivity_marks_leadership_standalone() -> None:
    data = client.get("/api/v1/veridiq/agents/connectivity").json()
    assert data["ok"] is True
    assert "ceo" in data["standalone_agents"]
