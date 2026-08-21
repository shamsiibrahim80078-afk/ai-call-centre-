"""Tests for LangGraph orchestration, RAG, SSE, and brand architecture."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from veridiq.orchestration.langgraph_app import build_langgraph_app, run_langgraph  # noqa: E402
from veridiq.rag import EvidenceRAG, get_rag  # noqa: E402
from veridiq.rag.embeddings import embed_text  # noqa: E402


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_brand_exposes_host_intro_and_architecture(client: TestClient) -> None:
    resp = client.get("/api/v1/brand")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "VERIDIQ"
    assert "LangGraph" in data["host_intro"]
    assert data["architecture"]["orchestrator"] == "LangGraph"
    assert data["architecture"]["vector_db"] == "Qdrant"
    assert data["architecture"]["realtime"] == "SSE"


def test_langgraph_compiles_and_runs() -> None:
    graph = build_langgraph_app()
    assert graph is not None
    result = run_langgraph(
        {
            "text": "The central bank raised interest rates by 25 basis points yesterday.",
            "title": "LangGraph test",
            "session_id": "lg-test",
        }
    )
    assert result.get("orchestrator") == "LangGraph"
    assert 0 <= float(result["truth_score"]) <= 1
    assert result.get("decision")
    assert isinstance(result.get("rag_hits"), list)


def test_rag_upsert_and_retrieve() -> None:
    rag = EvidenceRAG()
    rag.upsert(
        "Vaccine trials showed a seventy percent reduction in hospitalizations.",
        metadata={"source": "test://vaccine", "title": "Vaccine trial"},
        doc_id="test-vaccine-doc",
    )
    hits = rag.query("hospitalization reduction vaccine effectiveness", top_k=3)
    assert len(hits) >= 1
    assert hits[0]["text"]
    assert embed_text("abc") != embed_text("xyz")
    status = get_rag().status()
    assert status["collection"] == "veridiq_evidence"


def test_async_verify_and_sse(client: TestClient) -> None:
    queued = client.post(
        "/api/v1/veridiq/verify",
        json={
            "text": "Markets closed higher after the Fed held rates steady.",
            "title": "SSE test",
            "async_mode": True,
        },
    )
    assert queued.status_code == 200
    body = queued.json()
    job_uuid = body["job_uuid"]
    assert body["async_mode"] is True

    stages = []
    with client.stream("GET", f"/api/v1/veridiq/jobs/{job_uuid}/events") as stream:
        assert stream.status_code == 200
        for line in stream.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            stages.append(event.get("stage"))
            if event.get("stage") in {"completed", "failed", "stream_end"}:
                break

    assert "orchestrator" in stages or "route" in stages or "pipeline_start" in stages or "queued" in stages
    assert any(s in stages for s in ("completed", "failed", "stream_end"))

    job = client.get(f"/api/v1/veridiq/jobs/{job_uuid}")
    assert job.status_code == 200
    assert job.json()["status"] in {"completed", "failed", "processing", "queued"}


def test_dashboard_architecture(client: TestClient) -> None:
    resp = client.get("/api/v1/veridiq/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["architecture"]["orchestrator"] == "LangGraph"
    assert "rag" in data
