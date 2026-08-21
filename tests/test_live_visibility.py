"""Regression coverage for the "agents aren't live" root cause.

Real agent runs (heuristics, official-API lookups) routinely finish in well
under a second — far faster than any dashboard poll (~3-4s) or SSE cadence
(~2s) can observe. Previously the worker pool released a worker back to idle
the instant `fn()` returned, so `/api/v1/veridiq/workspace`,
`/api/v1/veridiq/agents`, and the workforce SSE stream would *always* render
every agent as idle/"Waiting for Assignment" — even immediately after a real,
successful run — because the busy window never outlived a single request.

These tests exercise the fix directly against `AIWorkerPool`: a run stays
visibly "busy" for a floor duration after finishing, and both the synchronous
(`run_agent_task`) and non-blocking (`start_agent_task`) execution paths are
covered, including via the live HTTP endpoint.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from veridiq.workforce import control as agent_control  # noqa: E402
from veridiq.workforce.pool import global_worker_pool  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def _restore_control() -> None:
    yield
    agent_control.set_status("decision", "running")


def test_sync_run_stays_visible_after_completion() -> None:
    """run_agent_task: caller gets the real result immediately, but the
    worker slot stays "busy" (observable via snapshot) for the floor."""

    def _fn():
        return {"ok": True, "confidence": 0.8}

    out = global_worker_pool.run_agent_task(
        agent_type="decision", fn=_fn, task="visibility unit test", min_visible_sec=0.35
    )
    assert out["ok"] is True

    snap = global_worker_pool.snapshot()
    assert snap["waiting_for_tasks"] is False, "worker should still be visibly busy right after completion"
    live = next(a for a in snap["assignments"] if a["agent_type"] == "decision")
    assert live["finished"] is True
    assert live["result_ok"] is True
    assert live["stage"] == "result_collection"

    # Poll instead of a single fixed sleep: under a loaded full test-suite run
    # the background delayed-release thread can legitimately land a bit later
    # than the floor itself (thread-pool/CPU contention), so give it a
    # generous deadline rather than asserting on one snapshot taken at a
    # single point in time.
    deadline = time.time() + 5
    released = False
    while time.time() < deadline:
        snap2 = global_worker_pool.snapshot()
        if not any(a["agent_type"] == "decision" for a in snap2["assignments"]):
            released = True
            break
        time.sleep(0.05)
    assert released, "should release after the floor elapses"


def test_async_run_starts_immediately_and_completes_in_background() -> None:
    started_flag = {"ran": False}

    def _fn():
        started_flag["ran"] = True
        return {"ok": True, "confidence": 0.5, "result": {"summary": "ok"}}

    out = global_worker_pool.start_agent_task(
        agent_type="decision", fn=_fn, task="async visibility unit test", min_visible_sec=0.3
    )
    assert out["status"] == "started"
    assert out["run_id"]

    # Non-blocking: returns before fn() necessarily executed.
    snap = global_worker_pool.snapshot()
    assert any(a["agent_type"] == "decision" for a in snap["assignments"])

    deadline = time.time() + 3
    while time.time() < deadline and not started_flag["ran"]:
        time.sleep(0.02)
    assert started_flag["ran"] is True

    # Give the background thread a moment to record history, then confirm
    # the run result is retrievable and the worker eventually releases.
    time.sleep(0.05)
    run = global_worker_pool.get_run(out["run_id"])
    assert run is not None
    assert run["envelope"]["ok"] is True

    deadline2 = time.time() + 5
    released = False
    while time.time() < deadline2:
        snap2 = global_worker_pool.snapshot()
        if not any(a["agent_type"] == "decision" for a in snap2["assignments"]):
            released = True
            break
        time.sleep(0.05)
    assert released, "should release after the floor elapses"


def test_run_endpoint_is_nonblocking_and_pollable() -> None:
    resp = client.post(
        "/api/v1/veridiq/agents/decision/run",
        json={"payload": {"truth_score": 0.8, "risk_analysis": {"risk_score": 0.2}}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "started"
    run_id = data["run_id"]

    deadline = time.time() + 5
    result = None
    while time.time() < deadline:
        poll = client.get(f"/api/v1/veridiq/agents/decision/runs/{run_id}")
        assert poll.status_code == 200
        if poll.json().get("status") in {"completed", "failed"}:
            result = poll.json()
            break
        time.sleep(0.05)
    assert result is not None, "run should complete within the poll window"
    assert result["status"] == "completed"
    assert result["envelope"]["ok"] is True


def test_run_endpoint_falls_back_to_sample_payload_when_empty() -> None:
    """fact_checking raises ValueError on an empty payload — the /run endpoint
    should use the same representative sample payload as Run Agent Test
    instead of guaranteeing failure on a bare click."""
    resp = client.post("/api/v1/veridiq/agents/fact_checking/run", json={})
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    # duckduckgo_instant has an internal 12s network timeout with a local
    # fallback on failure — give this plenty of headroom either way.
    deadline = time.time() + 20
    result = None
    while time.time() < deadline:
        poll = client.get(f"/api/v1/veridiq/agents/fact_checking/runs/{run_id}").json()
        if poll.get("status") in {"completed", "failed"}:
            result = poll
            break
        time.sleep(0.1)
    assert result is not None
    assert result["status"] == "completed"
    assert result["envelope"]["ok"] is True


def test_run_endpoint_respects_stopped_control() -> None:
    client.post("/api/v1/veridiq/agents/decision/control/stop")
    resp = client.post("/api/v1/veridiq/agents/decision/run", json={"payload": {}})
    assert resp.status_code == 409
    client.post("/api/v1/veridiq/agents/decision/control/start")
