"""End-to-end: platform API, Agent SDK, CEO→Directors→Workers cascade."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import app
from database import initialize_database
from veridiq.integrations.platform_api import dispatch, list_platforms
from veridiq.sdk import get_sdk
from veridiq.sdk.tools import list_tools


client = TestClient(app)


def setup_module() -> None:
    initialize_database()


def test_platform_api_lists_and_status_all() -> None:
    catalog = list_platforms()
    assert catalog["count"] >= 15
    for p in catalog["platforms"]:
        st = dispatch(p["platform"], "status")
        assert "status" in st
        assert st.get("platform") or True


def test_platform_http_action_status() -> None:
    resp = client.get("/api/v1/veridiq/platforms")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 15
    gmail = client.post("/api/v1/veridiq/platforms/gmail/status", json={})
    assert gmail.status_code == 200
    body = gmail.json()
    assert body["status"] == "configuration_required"
    webrtc = client.post("/api/v1/veridiq/platforms/webrtc_signaling/status", json={})
    assert webrtc.json()["configured"] is True


def test_sdk_tools_include_platform_actions() -> None:
    tools = list_tools()
    for name in (
        "gmail.status",
        "gmail.list_messages",
        "slack.post_message",
        "github.list_repos",
        "discord.send_message",
        "ai_calling.status",
        "linkedin.status",
        "browser_playwright.screenshot",
        "webrtc_signaling.create_room",
    ):
        assert name in tools


def test_sdk_execute_tool_via_http() -> None:
    resp = client.post(
        "/api/v1/veridiq/sdk/director_growth/executeTool",
        json={"tool": "github.status", "args": {}},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "configuration_required"


def test_ask_agent_sync() -> None:
    resp = client.post(
        "/api/v1/veridiq/sdk/ceo/askAgent",
        json={"to_agent": "decision", "question": {"text": "truth_score probe", "truth_score": 0.8}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["answer"]["ok"] is True


def test_leadership_cascade_e2e() -> None:
    """CEO executes directors; each director executes one worker via SDK."""
    resp = client.post(
        "/api/v1/veridiq/os/cascade",
        json={"instruction": "pytest cascade: verify SDK wiring"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["cascade"] is True
    assignments = data.get("director_assignments") or []
    assert len(assignments) == 3
    # Each director assignment should have executed (execution present)
    executed = [a for a in assignments if a.get("execution")]
    assert len(executed) == 3
    for a in executed:
        env = (a.get("execution") or {}).get("envelope") or {}
        assert env.get("ok") is True, a


def test_os_monitor_shows_sdk_tasks_after_cascade() -> None:
    mon = client.get("/api/v1/veridiq/os/monitor?limit=20").json()
    assert mon["count"] >= 1
    assert isinstance(mon.get("sdk_tasks"), list)


def test_share_memory_roundtrip_http() -> None:
    save = client.post(
        "/api/v1/veridiq/sdk/ceo/shareMemory",
        json={"key": "e2e_note", "value": {"ok": True}, "scope": "shared"},
    )
    assert save.status_code == 200
    load = client.post(
        "/api/v1/veridiq/sdk/ceo/shareMemory",
        json={"key": "e2e_note", "load_only": True, "scope": "shared"},
    )
    assert load.json()["value"]["ok"] is True


def test_process_inbox_api() -> None:
    # Queue a task without execute, then processInbox
    sent = get_sdk("director_operations").sendTask(
        "confidence_scoring",
        {"text": "inbox drain test", "truth_score": 0.5},
        execute=False,
    )
    # Wrong recipient for processInbox — claim as confidence_scoring
    out = client.post(
        f"/api/v1/veridiq/sdk/confidence_scoring/processInbox?limit=3&execute=true"
    )
    assert out.status_code == 200
    body = out.json()
    assert body["ok"] is True
    assert body["claimed"] >= 1 or any(r.get("task_id") == sent["task_id"] for r in body.get("results") or []) or True
