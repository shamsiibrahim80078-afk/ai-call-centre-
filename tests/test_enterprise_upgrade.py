"""Enterprise upgrade: live workforce, ops center, connectors, agent profiles."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from veridiq.workforce.pool import global_worker_pool  # noqa: E402


client = TestClient(app)


def test_workforce_idle_waiting_for_tasks() -> None:
    snap = global_worker_pool.snapshot()
    assert snap["waiting_for_tasks"] is True
    assert snap["status_label"] == "Waiting for Tasks"
    assert snap["active_workers"] == 0
    assert snap["max_workers"] >= 50

    resp = client.get("/api/v1/veridiq/workforce")
    assert resp.status_code == 200
    data = resp.json()
    assert data["waiting_for_tasks"] is True
    assert data["assignments"] == []


def test_agents_report_idle_not_fake_working() -> None:
    resp = client.get("/api/v1/veridiq/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    for agent in data["agents"]:
        assert agent["status"] in {"idle", "working"}
        assert "identity" in agent
        assert agent["identity"].get("name")
        if agent["status"] == "idle":
            assert agent["current_assignment"] is None
    assert data["workforce"]["waiting_for_tasks"] is True


def test_agent_detail_and_connectivity() -> None:
    conn = client.get("/api/v1/veridiq/agents/connectivity")
    assert conn.status_code == 200
    assert conn.json()["ok"] is True

    agents = client.get("/api/v1/veridiq/agents").json()["agents"]
    sample = agents[0]["agent_type"]
    detail = client.get(f"/api/v1/veridiq/agents/{sample}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "idle"
    assert body["identity"]["name"]
    assert "metrics" in body
    assert "langgraph_nodes" in body


def test_ops_center_live_shape() -> None:
    resp = client.get("/api/v1/veridiq/ops")
    assert resp.status_code == 200
    data = resp.json()
    assert "workforce" in data
    assert "workflows" in data
    assert "langgraph" in data
    assert "system" in data
    assert data["status_label"] == "Waiting for Tasks"
    assert data["active_ai_workers"] == 0


def test_page_metrics_unique() -> None:
    verify = client.get("/api/v1/veridiq/pages/verify-metrics").json()
    news = client.get("/api/v1/veridiq/pages/news-metrics").json()
    meeting = client.get("/api/v1/veridiq/pages/meeting-metrics").json()
    reports = client.get("/api/v1/veridiq/pages/reports-metrics").json()
    assert "running_verifications" in verify
    assert "active_news_analyses" in news
    assert "live_meetings" in meeting
    assert "reports_generated" in reports
    assert verify["waiting_for_tasks"] is True
    assert news["waiting_for_tasks"] is True
    assert meeting["waiting_for_tasks"] is True


def test_connectors_no_fabricated_news_without_key() -> None:
    resp = client.get("/api/v1/veridiq/connectors")
    assert resp.status_code == 200
    data = resp.json()
    assert "news" in data and "jobs" in data
    news = data["news"]
    if news["status"] == "configuration_required":
        assert news["count"] == 0


def test_dashboard_control_center_shape() -> None:
    resp = client.get("/api/v1/veridiq/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    for key in (
        "workforce",
        "verification",
        "news",
        "meeting",
        "reports",
        "quick_actions",
        "jobs",
        "rag",
        "blockchain",
        "system",
    ):
        assert key in data
    assert data["workforce"]["waiting_for_tasks"] is True
    assert data["agents"]["langgraph"]["ok"] is True


def test_worker_pool_run_marks_activity() -> None:
    def _fn():
        return {"ok": True, "confidence": 0.9}

    out = global_worker_pool.run_agent_task(agent_type="fact_checking", fn=_fn, task="unit test")
    assert out["ok"] is True
    snap = global_worker_pool.snapshot()
    assert snap["waiting_for_tasks"] is True  # completed and released
    assert "fact_checking" in snap["agent_stats"]
    assert snap["agent_stats"]["fact_checking"]["runs"] >= 1
