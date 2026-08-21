"""'Run Agent Test' admin capability — agent init, platform check, task
execution, result collection, error reporting. Verifies steps are honest
(configuration_required, not fabricated success) and history is retrievable.

Agents used here never make a live outbound HTTP call during task execution
(no network dependency), so this suite stays fast and deterministic.
`fact_checking` / `web_search` / market-data agents genuinely call official
public APIs and are covered by the pre-existing `tests/test_veridiq.py`
integration-style checks instead.
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
from veridiq.workforce import control as agent_control  # noqa: E402

client = TestClient(app)

_TEST_AGENTS = ("decision", "lie_detection", "ai_calling", "voice_analysis", "orchestrator", "confidence_scoring")


@pytest.fixture(autouse=True)
def _reset_controls():
    for agent_type in _TEST_AGENTS:
        agent_control.set_status(agent_type, "running")
    yield
    for agent_type in _TEST_AGENTS:
        agent_control.set_status(agent_type, "running")


def test_unknown_agent_returns_404() -> None:
    resp = client.post("/api/v1/veridiq/agents/not_a_real_agent/test", json={})
    assert resp.status_code == 404


def test_run_agent_test_has_five_steps_with_expected_shape() -> None:
    resp = client.post("/api/v1/veridiq/agents/decision/test", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_type"] == "decision"
    step_names = [s["step"] for s in data["steps"]]
    assert step_names == [
        "agent_initialization",
        "platform_connection_check",
        "task_execution",
        "result_collection",
        "error_reporting",
    ]
    for step in data["steps"]:
        assert step["status"] in {"passed", "failed", "skipped", "configuration_required"}
        assert "message" in step
        assert "duration_ms" in step
    assert data["overall_status"] in {"passed", "partial", "failed"}
    assert data["steps"][0]["status"] == "passed"
    assert data["steps"][2]["status"] == "passed"  # task_execution: decision.process() is purely local
    assert isinstance(data["logs"], list) and len(data["logs"]) > 0
    assert data["metrics"]["total"] == 5


def test_agent_init_step_passes_for_every_sampled_agent() -> None:
    for agent_type in _TEST_AGENTS:
        resp = client.post(f"/api/v1/veridiq/agents/{agent_type}/test", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["steps"][0]["status"] == "passed", f"{agent_type} init failed: {data['steps'][0]}"


def test_unconfigured_platform_reports_configuration_required_honestly() -> None:
    resp = client.post("/api/v1/veridiq/agents/ai_calling/test", json={})
    data = resp.json()
    platform_step = next(s for s in data["steps"] if s["step"] == "platform_connection_check")
    integration = client.get("/api/v1/veridiq/integrations/ai_calling").json()
    if not integration["configured"]:
        assert platform_step["status"] == "configuration_required"
        assert data["overall_status"] in {"partial", "failed"}
    # ai_calling's process() only reads local status/campaign state — safe, no network.
    exec_step = next(s for s in data["steps"] if s["step"] == "task_execution")
    assert exec_step["status"] == "passed"


def test_stopped_agent_skips_task_execution_step() -> None:
    agent_type = "decision"
    client.post(f"/api/v1/veridiq/agents/{agent_type}/control/stop")
    resp = client.post(f"/api/v1/veridiq/agents/{agent_type}/test", json={})
    data = resp.json()
    exec_step = next(s for s in data["steps"] if s["step"] == "task_execution")
    assert exec_step["status"] == "skipped"
    assert "stopped" in exec_step["message"].lower()
    result_step = next(s for s in data["steps"] if s["step"] == "result_collection")
    assert result_step["status"] == "skipped"
    client.post(f"/api/v1/veridiq/agents/{agent_type}/control/start")


def test_explicit_platform_override_is_honored() -> None:
    resp = client.post("/api/v1/veridiq/agents/voice_analysis/test", json={"platform": "linkedin"})
    data = resp.json()
    assert data["platform"] == "linkedin"
    platform_step = next(s for s in data["steps"] if s["step"] == "platform_connection_check")
    # Unconfigured in this environment -> honest configuration_required, never fabricated.
    integration = client.get("/api/v1/veridiq/integrations/linkedin").json()
    if not integration["configured"]:
        assert platform_step["status"] == "configuration_required"


def test_history_endpoints_return_recorded_runs() -> None:
    client.post("/api/v1/veridiq/agents/decision/test", json={})
    history = client.get("/api/v1/veridiq/agents/decision/test/history").json()
    assert history["count"] >= 1
    assert history["runs"][0]["agent_type"] == "decision"

    recent = client.get("/api/v1/veridiq/agent-tests").json()
    assert recent["count"] >= 1
