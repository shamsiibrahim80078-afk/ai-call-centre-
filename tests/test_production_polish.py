"""Additional production polish tests."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from veridiq.agents import AGENT_REGISTRY  # noqa: E402


client = TestClient(app)


def test_connectivity_all_agents_wired() -> None:
    resp = client.get("/api/v1/veridiq/agents/connectivity")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    # Standalone growth specialists (AI Calling, LinkedIn, Sales) act through their own
    # integration + approval gates rather than the truth/market LangGraph pipelines.
    assert data["wired_count"] + len(data.get("standalone_agents", [])) == len(AGENT_REGISTRY)
    assert set(data["unwired"]) == set(data.get("standalone_agents", []))


def test_system_endpoint() -> None:
    resp = client.get("/api/v1/veridiq/system")
    assert resp.status_code == 200
    data = resp.json()
    assert data["database"] == "ok"
    assert data["architecture"]["orchestrator"] == "LangGraph"
    assert "rag" in data


def test_upload_rejects_bad_extension() -> None:
    resp = client.post(
        "/api/v1/veridiq/verify/upload",
        data={"title": "bad", "text": "hello"},
        files={"image": ("malware.exe", b"notanimage", "application/octet-stream")},
    )
    assert resp.status_code == 400
