"""Tests for cinematic polish APIs and blockchain readiness layer."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from blockchain.integration import global_blockchain  # noqa: E402

client = TestClient(app)


def test_host_chat() -> None:
    resp = client.post("/api/v1/veridiq/host/chat", json={"question": "How does LangGraph work?"})
    assert resp.status_code == 200
    assert "LangGraph" in resp.json()["answer"]


def test_blockchain_status_modular() -> None:
    resp = client.get("/api/v1/blockchain/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    assert "contracts" in data
    assert "TruthAttestation" in data["contracts"]
    # No hardcoded required address
    assert data["contracts"]["TruthAttestation"]["address"] in (None, "") or isinstance(
        data["contracts"]["TruthAttestation"]["address"], str
    )


def test_blockchain_attest_dry_run() -> None:
    verify = client.post(
        "/api/v1/veridiq/verify",
        json={"text": "The committee approved the budget amendment yesterday.", "title": "attest-test"},
    )
    assert verify.status_code == 200
    job_id = verify.json()["job_id"]
    attest = client.post("/api/v1/blockchain/attest", json={"job_id": job_id})
    assert attest.status_code == 200
    body = attest.json()
    assert body["mode"] == "dry_run"
    assert body["report_hash"]


def test_system_includes_blockchain() -> None:
    resp = client.get("/api/v1/veridiq/system")
    assert resp.status_code == 200
    assert "blockchain" in resp.json()
    status = global_blockchain.status()
    assert status["ready"] is True
