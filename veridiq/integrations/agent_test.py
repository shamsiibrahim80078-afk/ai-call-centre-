""""Run Agent Test" admin capability — a real end-to-end smoke test per agent.

Exercises five stages against the live architecture (never mocked/fabricated):
  1. Agent initialization      — resolve the agent class + identity/department
  2. Platform connection check — the real `integrations.registry.test_integration`
                                  call for whatever platform this agent's
                                  department depends on (skipped if none)
  3. Task execution            — a real `agent.run(...)` call through the
                                  worker pool with a small representative
                                  sample payload (honors start/stop/pause gating)
  4. Result collection         — captures the raw envelope, confidence, latency
  5. Error reporting           — any exception is captured as a failed step,
                                  never silently swallowed

When a platform is unconfigured, step 2 (and any downstream step that
genuinely requires it) is marked `configuration_required` — not a fabricated
pass and not a hard failure of the whole agent.
"""

from __future__ import annotations

import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import json  # noqa: E402

from database import db_session, initialize_database  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# Small, safe, representative payloads per agent so "Run Agent Test" exercises
# a real code path without requiring the operator to supply input.
SAMPLE_PAYLOADS: dict[str, dict[str, Any]] = {
    "lie_detection": {"text": "I was definitely, absolutely, one hundred percent home all night."},
    "face_analysis": {},
    "voice_analysis": {"text": "This is a calm, steady sample statement for a voice-proxy smoke test."},
    "emotion_detection": {"text": "I am thrilled and a little nervous about the launch."},
    "statement_verification": {"text": "The company was founded in 2010 and is headquartered in Berlin."},
    "fact_checking": {"claim": "The Eiffel Tower is located in Paris."},
    "news_verification": {"text": "central bank interest rate decision"},
    "web_search": {"query": "VERIDIQ truth verification platform"},
    "evidence_collection": {"text": "The bridge was completed in 1937 and spans the strait."},
    "source_credibility": {"sources": [{"url": "https://www.reuters.com/example"}]},
    "timeline_builder": {"text": "In 2020 the project started. Last week it shipped v2."},
    "meeting_analysis": {"text": "Alice: We agreed to ship on Friday. Bob: I will own the release notes."},
    "risk_analysis": {"lie_detection": {"deception_score": 0.2}, "credibility": {"average_credibility": 0.7}},
    "confidence_scoring": {"scores": [0.7, 0.8, 0.65]},
    "report_generator": {"title": "Smoke Test Report", "truth_score": 0.8},
    "citation": {"evidence": [{"claim": "Sample claim", "url": "https://example.com"}]},
    "conversation_memory": {"session_id": "agent-test-smoke"},
    "decision": {"truth_score": 0.8, "risk_analysis": {"risk_score": 0.2}},
    "orchestrator": {"text": "Sample orchestration input"},
    "market_research": {"coin_id": "bitcoin"},
    "onchain_analysis": {"coin_id": "bitcoin"},
    "news_correlation": {"coin_id": "bitcoin"},
    "sentiment_analysis": {"coin_id": "bitcoin"},
    "macro_trend": {"coin_id": "bitcoin"},
    "technical_analysis": {"coin_id": "bitcoin"},
    "market_risk": {"coin_id": "bitcoin"},
    "portfolio_intelligence": {"coin_id": "bitcoin"},
    "ai_calling": {},
    "linkedin_outreach": {},
    "sales_intelligence": {},
}


def _platform_for_agent(agent_type: str) -> Optional[str]:
    """Best-effort mapping from an agent's department to a single testable platform."""
    from veridiq.workforce.departments import department_for_agent
    from veridiq.workforce.workspace import _DEPT_PLATFORMS

    dept = department_for_agent(agent_type)
    if not dept:
        return None
    platforms = _DEPT_PLATFORMS.get(dept["id"]) or set()
    from veridiq.integrations.registry import TEST_FUNCS

    testable = sorted(p for p in platforms if p in TEST_FUNCS)
    if testable:
        return testable[0]
    if agent_type == "ai_calling":
        return "ai_calling"
    return None


def _step(name: str) -> dict[str, Any]:
    return {"step": name, "status": "pending", "message": None, "data": None, "started_at": _utc_now(), "finished_at": None, "duration_ms": None}


def _finish(step: dict[str, Any], *, status: str, message: str, data: Any = None) -> dict[str, Any]:
    step["status"] = status
    step["message"] = message
    step["data"] = data
    step["finished_at"] = _utc_now()
    try:
        started = datetime.fromisoformat(step["started_at"])
        finished = datetime.fromisoformat(step["finished_at"])
        step["duration_ms"] = round((finished - started).total_seconds() * 1000, 2)
    except Exception:
        step["duration_ms"] = None
    return step


def run_agent_test(agent_type: str, *, platform: Optional[str] = None, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    from veridiq.agents import AGENT_REGISTRY, get_agent
    from veridiq.workforce import control as agent_control
    from veridiq.workforce.departments import department_for_agent
    from veridiq.workforce.identities import identity_for

    run_uuid = str(uuid.uuid4())
    started_at = _utc_now()
    perf_start = time.perf_counter()
    steps: list[dict[str, Any]] = []
    logs: list[str] = []

    def log(msg: str) -> None:
        logs.append(f"[{_utc_now()}] {msg}")

    # Step 1 — Agent initialization
    step1 = _step("agent_initialization")
    if agent_type not in AGENT_REGISTRY:
        _finish(step1, status="failed", message=f"Unknown agent_type '{agent_type}'.")
        steps.append(step1)
        log(f"FAILED: unknown agent_type '{agent_type}'")
        return _persist_and_return(run_uuid, agent_type, platform, steps, logs, started_at, perf_start, overall="failed")

    try:
        agent = get_agent(agent_type)
        identity = identity_for(agent_type)
        dept = department_for_agent(agent_type)
        log(f"Initialized {identity.get('name')} ({agent_type}) — {identity.get('role')}")
        _finish(
            step1,
            status="passed",
            message=f"Agent '{agent.name}' initialized successfully.",
            data={"agent_id": agent.agent_id, "agent_name": agent.name, "identity": identity, "department": dept},
        )
    except Exception as exc:
        _finish(step1, status="failed", message=f"Initialization raised: {exc}", data={"traceback": traceback.format_exc(limit=3)})
        steps.append(step1)
        log(f"FAILED: initialization error — {exc}")
        return _persist_and_return(run_uuid, agent_type, platform, steps, logs, started_at, perf_start, overall="failed")
    steps.append(step1)

    # Step 2 — Platform connection check
    step2 = _step("platform_connection_check")
    resolved_platform = platform or _platform_for_agent(agent_type)
    if not resolved_platform:
        _finish(step2, status="skipped", message="This agent has no external platform dependency to check.")
        log("SKIPPED: no external platform dependency for this agent")
    else:
        try:
            from veridiq.integrations.registry import test_integration

            result = test_integration(resolved_platform)
            status = result.get("status")
            if status in {"ok", "configured", "public"}:
                _finish(step2, status="passed", message=result.get("message") or f"{resolved_platform} connection verified.", data=result)
                log(f"PASSED: {resolved_platform} connection check — {status}")
            elif status == "configuration_required":
                _finish(step2, status="configuration_required", message=result.get("message") or "Missing credentials.", data=result)
                log(f"CONFIGURATION_REQUIRED: {resolved_platform} — {result.get('message')}")
            else:
                _finish(step2, status="failed", message=result.get("message") or f"{resolved_platform} check failed.", data=result)
                log(f"FAILED: {resolved_platform} connection check — {result.get('message')}")
        except Exception as exc:
            _finish(step2, status="failed", message=f"Platform check raised: {exc}", data={"traceback": traceback.format_exc(limit=3)})
            log(f"FAILED: platform check exception — {exc}")
    steps.append(step2)

    # Step 3 — Task execution (real path; honors control gating)
    step3 = _step("task_execution")
    sample_payload = dict(payload or SAMPLE_PAYLOADS.get(agent_type, {}))
    try:
        agent_control.assert_runnable(agent_type)
        from veridiq.workforce.pool import global_worker_pool

        def _fn():
            return agent.run(sample_payload, job_id=f"agent-test-{run_uuid[:8]}")

        envelope = global_worker_pool.run_agent_task(
            agent_type=agent_type, fn=_fn, job_id=f"agent-test-{run_uuid[:8]}", task=f"Run Agent Test for {agent_type}"
        )
        ok = bool(envelope.get("ok")) if isinstance(envelope, dict) else True
        if ok:
            _finish(step3, status="passed", message="Task executed successfully through the live architecture.", data=envelope)
            log(f"PASSED: task execution — confidence={envelope.get('confidence')} latency={envelope.get('latency_ms')}ms")
        else:
            _finish(step3, status="failed", message=envelope.get("error") or "Task execution returned ok=false.", data=envelope)
            log(f"FAILED: task execution — {envelope.get('error')}")
    except agent_control.AgentStoppedError as exc:
        _finish(step3, status="skipped", message=f"Agent is {exc.status} — task execution skipped. Resume the agent to run this step.")
        log(f"SKIPPED: agent is {exc.status}")
    except Exception as exc:
        _finish(step3, status="failed", message=f"Task execution raised: {exc}", data={"traceback": traceback.format_exc(limit=3)})
        log(f"FAILED: task execution exception — {exc}")
    steps.append(step3)

    # Step 4 — Result collection
    step4 = _step("result_collection")
    task_data = step3.get("data") if isinstance(step3.get("data"), dict) else {}
    if step3["status"] == "passed":
        metrics = {
            "confidence": task_data.get("confidence"),
            "latency_ms": task_data.get("latency_ms"),
            "attempt": task_data.get("attempt"),
        }
        _finish(step4, status="passed", message="Response data and metrics collected.", data={"metrics": metrics, "response": task_data.get("result")})
        log("PASSED: result collected")
    elif step3["status"] == "skipped":
        _finish(step4, status="skipped", message="No result to collect — task execution was skipped.")
        log("SKIPPED: no result to collect")
    else:
        _finish(step4, status="skipped", message="No result to collect — task execution did not succeed.")
        log("SKIPPED: task execution did not produce a result")
    steps.append(step4)

    # Step 5 — Error reporting
    step5 = _step("error_reporting")
    failures = [s for s in steps if s["status"] == "failed"]
    if failures:
        _finish(
            step5,
            status="passed",
            message=f"{len(failures)} step(s) reported errors — captured below, not silently swallowed.",
            data={"failed_steps": [{"step": s["step"], "message": s["message"]} for s in failures]},
        )
        log(f"Reported {len(failures)} failing step(s)")
    else:
        _finish(step5, status="passed", message="No errors encountered during this run.")
        log("No errors encountered")
    steps.append(step5)

    overall = "failed" if any(s["status"] == "failed" for s in steps) else (
        "partial" if any(s["status"] == "configuration_required" for s in steps) else "passed"
    )
    return _persist_and_return(run_uuid, agent_type, resolved_platform, steps, logs, started_at, perf_start, overall=overall)


def _persist_and_return(
    run_uuid: str,
    agent_type: str,
    platform: Optional[str],
    steps: list[dict[str, Any]],
    logs: list[str],
    started_at: str,
    perf_start: float,
    *,
    overall: str,
) -> dict[str, Any]:
    finished_at = _utc_now()
    duration_ms = round((time.perf_counter() - perf_start) * 1000, 2)
    passed = sum(1 for s in steps if s["status"] == "passed")
    failed = sum(1 for s in steps if s["status"] == "failed")
    skipped = sum(1 for s in steps if s["status"] in {"skipped", "configuration_required"})
    metrics = {"passed": passed, "failed": failed, "skipped": skipped, "total": len(steps), "duration_ms": duration_ms}

    initialize_database()
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO veridiq_agent_test_runs
                (run_uuid, agent_type, platform, overall_status, steps_json, metrics_json, started_at, finished_at, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_uuid,
                agent_type,
                platform,
                overall,
                json.dumps(steps, default=str),
                json.dumps(metrics, default=str),
                started_at,
                finished_at,
                duration_ms,
            ),
        )
        conn.execute(
            "DELETE FROM veridiq_agent_test_runs WHERE id < (SELECT MAX(id) - 300 FROM veridiq_agent_test_runs)"
        )

    return {
        "run_uuid": run_uuid,
        "agent_type": agent_type,
        "platform": platform,
        "overall_status": overall,
        "steps": steps,
        "logs": logs,
        "metrics": metrics,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
    }


def list_test_runs(agent_type: Optional[str] = None, limit: int = 20) -> list[dict[str, Any]]:
    initialize_database()
    query = "SELECT * FROM veridiq_agent_test_runs"
    params: list[Any] = []
    if agent_type:
        query += " WHERE agent_type = ?"
        params.append(agent_type)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, limit))
    with db_session() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d.pop("id", None)
        d["steps"] = json.loads(d.pop("steps_json")) if d.get("steps_json") else []
        d["metrics"] = json.loads(d.pop("metrics_json")) if d.get("metrics_json") else {}
        out.append(d)
    return out
