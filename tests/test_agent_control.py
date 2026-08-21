"""Agent control/runtime layer — start/stop/pause/resume, commands, campaign
assignment, and execution-gating tests. Uses dedicated agent types per test
and always restores 'running' afterward so state never leaks into other
test modules that share the same in-process app/database.

Agents chosen for run_task/assign exercises are ones whose `process()` never
makes a live outbound HTTP call (e.g. `lie_detection`, `decision`), so this
suite stays fast and deterministic regardless of network availability —
`fact_checking` / `web_search` / market agents are exercised elsewhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from veridiq.agents import AGENT_REGISTRY  # noqa: E402
from veridiq.workforce import control as agent_control  # noqa: E402

client = TestClient(app)

# Only the agent types this suite touches — reset directly (bypassing HTTP/
# TestClient overhead) so setup/teardown stays fast across many tests.
_TEST_AGENTS = ("decision", "lie_detection", "ai_calling", "timeline_builder", "confidence_scoring", "citation")


@pytest.fixture(autouse=True)
def _reset_controls():
    """Ensure the agents used by this suite start and end each test as 'running'."""
    for agent_type in _TEST_AGENTS:
        agent_control.set_status(agent_type, "running")
    yield
    for agent_type in _TEST_AGENTS:
        agent_control.set_status(agent_type, "running")


def test_control_defaults_to_running_for_unknown_history() -> None:
    resp = client.get("/api/v1/veridiq/agents/citation/control")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_type"] == "citation"
    assert data["control"]["status"] == "running"
    assert isinstance(data["commands"], list)
    assert isinstance(data["assignments"], list)


def test_unknown_agent_control_returns_404() -> None:
    for path in ("control", "control/start", "control/stop", "control/pause", "control/resume"):
        method = client.get if path == "control" else client.post
        resp = method(f"/api/v1/veridiq/agents/not_a_real_agent/{path}")
        assert resp.status_code == 404


def test_start_stop_pause_resume_lifecycle() -> None:
    agent_type = "decision"

    stopped = client.post(f"/api/v1/veridiq/agents/{agent_type}/control/stop").json()
    assert stopped["ok"] is True
    assert stopped["control"]["status"] == "stopped"
    assert stopped["control"]["status_label"] == "Stopped"

    paused = client.post(f"/api/v1/veridiq/agents/{agent_type}/control/pause").json()
    assert paused["control"]["status"] == "paused"

    resumed = client.post(f"/api/v1/veridiq/agents/{agent_type}/control/resume").json()
    assert resumed["control"]["status"] == "running"

    started = client.post(f"/api/v1/veridiq/agents/{agent_type}/control/start").json()
    assert started["control"]["status"] == "running"


def test_stopped_agent_rejects_run_endpoint() -> None:
    agent_type = "confidence_scoring"
    client.post(f"/api/v1/veridiq/agents/{agent_type}/control/stop")
    resp = client.post(f"/api/v1/veridiq/agents/{agent_type}/run", json={"payload": {"scores": [0.7, 0.8]}})
    assert resp.status_code == 409
    assert "stopped" in resp.json()["detail"].lower()
    client.post(f"/api/v1/veridiq/agents/{agent_type}/control/start")

    resp2 = client.post(f"/api/v1/veridiq/agents/{agent_type}/run", json={"payload": {"scores": [0.7, 0.8]}})
    assert resp2.status_code == 200


def test_paused_agent_rejects_command_and_assign() -> None:
    agent_type = "timeline_builder"
    client.post(f"/api/v1/veridiq/agents/{agent_type}/control/pause")

    cmd = client.post(
        f"/api/v1/veridiq/agents/{agent_type}/control/command", json={"command": "run_task", "payload": {}}
    ).json()
    assert cmd["ok"] is False
    assert cmd["status"] == "rejected_agent_paused"

    assign = client.post(
        f"/api/v1/veridiq/agents/{agent_type}/control/assign", json={"campaign_type": "run_task", "payload": {}}
    ).json()
    assert assign["ok"] is False
    assert assign["status"] == "rejected_agent_paused"


def test_ping_and_run_task_commands() -> None:
    agent_type = "lie_detection"
    ping = client.post(
        f"/api/v1/veridiq/agents/{agent_type}/control/command", json={"command": "ping"}
    ).json()
    assert ping["ok"] is True
    assert ping["status"] == "completed"
    assert ping["result"]["pong"] is True

    run = client.post(
        f"/api/v1/veridiq/agents/{agent_type}/control/command",
        json={"command": "run_task", "payload": {"text": "I absolutely definitely never said that."}},
    ).json()
    assert run["ok"] is True
    assert run["status"] == "completed"

    unsupported = client.post(
        f"/api/v1/veridiq/agents/{agent_type}/control/command", json={"command": "not_a_real_command"}
    ).json()
    assert unsupported["ok"] is False
    assert unsupported["status"] == "unsupported"


def test_assign_campaign_run_task_and_unsupported() -> None:
    agent_type = "confidence_scoring"
    result = client.post(
        f"/api/v1/veridiq/agents/{agent_type}/control/assign",
        json={"campaign_type": "run_task", "payload": {"scores": [0.6, 0.9]}},
    ).json()
    assert result["ok"] is True
    assert result["assignment"]["campaign_type"] == "run_task"
    assert result["assignment"]["status"] == "completed"

    unsupported = client.post(
        f"/api/v1/veridiq/agents/{agent_type}/control/assign",
        json={"campaign_type": "not_a_real_campaign", "payload": {}},
    ).json()
    assert unsupported["ok"] is False
    assert unsupported["status"] == "unsupported"


def test_assign_ai_calling_campaign_only_valid_for_ai_calling_agent() -> None:
    resp = client.post(
        "/api/v1/veridiq/agents/decision/control/assign",
        json={"campaign_type": "ai_calling", "payload": {"to_number": "+15550001111", "script": "hello"}},
    ).json()
    assert resp["ok"] is False
    assert resp["status"] == "failed"

    ok = client.post(
        "/api/v1/veridiq/agents/ai_calling/control/assign",
        json={"campaign_type": "ai_calling", "payload": {"to_number": "+15550001111", "script": "hello there"}},
    ).json()
    assert ok["ok"] is True
    assert ok["assignment"]["status"] == "queued_for_approval"
    assert ok["assignment"]["result"]["status"] == "queued_for_approval"


def test_control_overview_lists_every_registered_agent() -> None:
    resp = client.get("/api/v1/veridiq/control")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == len(AGENT_REGISTRY)
    for agent_type in AGENT_REGISTRY:
        assert agent_type in data["controls"]


def test_command_and_assignment_history_recorded() -> None:
    agent_type = "lie_detection"
    client.post(f"/api/v1/veridiq/agents/{agent_type}/control/command", json={"command": "ping"})
    overview = client.get(f"/api/v1/veridiq/agents/{agent_type}/control").json()
    assert len(overview["commands"]) >= 1
    assert overview["commands"][0]["agent_type"] == agent_type
