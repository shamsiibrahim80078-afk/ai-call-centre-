"""Automated tests for VERIDIQ agents, orchestration, auth, and APIs."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from veridiq.agents import AGENT_REGISTRY, get_agent  # noqa: E402
from veridiq.orchestration.graph import VeridiqOrchestrator  # noqa: E402
from veridiq.pipeline.truth_pipeline import TruthPipeline  # noqa: E402


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_brand_and_health(client: TestClient) -> None:
    brand = client.get("/api/v1/brand")
    assert brand.status_code == 200
    data = brand.json()
    assert data["name"] == "VERIDIQ"
    assert "Truth" in data["tagline"]
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["service"] == "VERIDIQ"


def test_all_agents_registered() -> None:
    expected = {
        "lie_detection",
        "face_analysis",
        "voice_analysis",
        "emotion_detection",
        "statement_verification",
        "fact_checking",
        "news_verification",
        "web_search",
        "evidence_collection",
        "source_credibility",
        "timeline_builder",
        "meeting_analysis",
        "risk_analysis",
        "confidence_scoring",
        "report_generator",
        "citation",
        "conversation_memory",
        "decision",
        "orchestrator",
    }
    assert expected.issubset(set(AGENT_REGISTRY.keys()))


def test_each_agent_returns_structured_json() -> None:
    sample = {
        "text": "I absolutely never said that revenue grew 40% last quarter according to our CEO.",
        "claim": "Revenue grew 40% last quarter",
        "query": "revenue growth verification",
        "session_id": "test-session",
        "truth_score": 0.62,
        "risk_analysis": {"risk_score": 0.4, "risk_level": "medium"},
        "title": "Unit test report",
        "evidence": [{"claim": "x", "url": "https://example.com"}],
        "sources": [{"url": "https://reuters.com/article"}],
        "key_findings": ["unit"],
        "citations": [],
        "lie_detection": {"result": {"deception_score": 0.3}, "confidence": 0.7},
        "fact_checking": {"result": {"support_score": 0.5}, "confidence": 0.6},
        "news_verification": {"confidence": 0.5},
        "source_credibility": {"result": {"average_credibility": 0.6}, "confidence": 0.6},
        "turn": {"note": "hello"},
    }
    for agent_type in AGENT_REGISTRY:
        out = get_agent(agent_type).run(sample, job_id="unit-agent")
        assert out["ok"] is True
        assert out["agent_type"] == agent_type
        assert 0 <= out["confidence"] <= 1
        assert isinstance(out["result"], dict)


def test_orchestrator_end_to_end() -> None:
    orch = VeridiqOrchestrator(max_workers=3)
    result = orch.execute(
        {
            "text": "Officials confirmed the treaty was signed on Monday in Geneva.",
            "title": "Orchestration test",
            "session_id": "orch-test",
        }
    )
    assert "truth_score" in result
    assert 0 <= result["truth_score"] <= 1
    assert result["decision"]
    assert result["report"]


def test_pipeline_text_and_pdf() -> None:
    pipe = TruthPipeline()
    result = pipe.run(
        title="Pipeline test",
        text="Researchers published peer-reviewed evidence that the vaccine reduced hospitalizations by 70%.",
    )
    assert result["status"] == "completed"
    assert Path(result["report_path"]).exists()
    job = pipe.get_job(result["job_id"])
    assert job is not None
    assert job["status"] == "completed"


def test_auth_login_and_me(client: TestClient) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@veridiq.ai", "password": "VeridiqAdmin!23"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "admin@veridiq.ai"


def test_verify_api(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/veridiq/verify",
        json={"text": "The central bank raised interest rates by 25 basis points yesterday.", "title": "API verify"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["job_id"]
    report = client.get(f"/api/v1/veridiq/jobs/{body['job_id']}/report")
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("application/pdf")


def test_veridiq_dashboard_api(client: TestClient) -> None:
    resp = client.get("/api/v1/veridiq/dashboard")
    assert resp.status_code == 200
    assert resp.json()["brand"]["name"] == "VERIDIQ"
    assert resp.json()["agents"]["count"] >= 19
