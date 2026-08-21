"""Agent control / runtime layer — start, stop, pause, resume, send commands,
assign campaigns, and monitor execution for every registered VERIDIQ agent.

Builds on the existing worker pool / roster / departments / workspace
primitives instead of introducing a parallel agent model. State (control
status, command log, assignment log) is persisted to SQLite so it survives a
backend restart, following the same pattern as `veridiq/integrations/activity.py`
and `veridiq/calling/campaigns.py`.

Honesty policy (unchanged from the rest of the platform):
  - Stopping/pausing an agent is real — subsequent run/test/assign calls for
    that agent are rejected until it is resumed, never silently ignored.
  - Commands and campaign assignments that require missing credentials report
    `configuration_required` — they are never marked as fabricated successes.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import db_session, initialize_database  # noqa: E402

VALID_STATUSES = ("running", "paused", "stopped")
STATUS_LABELS = {
    "running": "Running",
    "paused": "Paused",
    "stopped": "Stopped",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure() -> None:
    initialize_database()


def _known_agent(agent_type: str) -> bool:
    from veridiq.agents import AGENT_REGISTRY

    return agent_type in AGENT_REGISTRY


class UnknownAgentError(LookupError):
    pass


class AgentStoppedError(RuntimeError):
    def __init__(self, agent_type: str, status: str) -> None:
        self.agent_type = agent_type
        self.status = status
        super().__init__(f"agent '{agent_type}' is {status}")


# ---------------------------------------------------------------------------
# Control status
# ---------------------------------------------------------------------------

def get_control(agent_type: str) -> dict[str, Any]:
    """Return the control record for an agent (default: running, never started)."""
    _ensure()
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM veridiq_agent_control WHERE agent_type = ?", (agent_type,)
        ).fetchone()
    if row is None:
        return {
            "agent_type": agent_type,
            "status": "running",
            "status_label": STATUS_LABELS["running"],
            "updated_at": None,
            "updated_by": None,
            "note": "No explicit control action taken yet — agent accepts assignments by default.",
        }
    d = dict(row)
    d["status_label"] = STATUS_LABELS.get(d["status"], d["status"].title())
    return d


def list_controls(agent_types: Optional[list[str]] = None) -> dict[str, dict[str, Any]]:
    """Bulk control lookup — one query for every agent, used by roster/workspace."""
    _ensure()
    with db_session() as conn:
        rows = conn.execute("SELECT * FROM veridiq_agent_control").fetchall()
    by_type = {r["agent_type"]: dict(r) for r in rows}
    from veridiq.agents import AGENT_REGISTRY

    types = agent_types if agent_types is not None else sorted(AGENT_REGISTRY.keys())
    out: dict[str, dict[str, Any]] = {}
    for at in types:
        existing = by_type.get(at)
        if existing:
            existing["status_label"] = STATUS_LABELS.get(existing["status"], existing["status"].title())
            out[at] = existing
        else:
            out[at] = {
                "agent_type": at,
                "status": "running",
                "status_label": STATUS_LABELS["running"],
                "updated_at": None,
                "updated_by": None,
            }
    return out


def set_status(agent_type: str, status: str, *, actor: Optional[str] = None) -> dict[str, Any]:
    if not _known_agent(agent_type):
        raise UnknownAgentError(agent_type)
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}")
    _ensure()
    stamped = _utc_now()
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO veridiq_agent_control (agent_type, status, updated_at, updated_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(agent_type) DO UPDATE SET status = excluded.status,
                updated_at = excluded.updated_at, updated_by = excluded.updated_by
            """,
            (agent_type, status, stamped, actor),
        )
    record_command(agent_type, command=f"set_status:{status}", status="completed", actor=actor)
    return get_control(agent_type)


def assert_runnable(agent_type: str) -> None:
    """Raise AgentStoppedError if the agent has been explicitly stopped/paused."""
    control = get_control(agent_type)
    if control["status"] in {"stopped", "paused"}:
        raise AgentStoppedError(agent_type, control["status"])


# ---------------------------------------------------------------------------
# Command log
# ---------------------------------------------------------------------------

def _row_to_command(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d.pop("id", None)
    payload_json = d.pop("payload_json", None)
    result_json = d.pop("result_json", None)
    d["payload"] = json.loads(payload_json) if payload_json else None
    d["result"] = json.loads(result_json) if result_json else None
    return d


def record_command(
    agent_type: str,
    *,
    command: str,
    payload: Optional[dict[str, Any]] = None,
    status: str = "completed",
    result: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
    actor: Optional[str] = None,
) -> dict[str, Any]:
    _ensure()
    command_uuid = str(uuid.uuid4())
    created = _utc_now()
    # All commands recorded here execute synchronously, so they are always
    # terminal by the time this row is written.
    finished = _utc_now()
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO veridiq_agent_commands
                (command_uuid, agent_type, command, payload_json, status, result_json, error, created_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                command_uuid,
                agent_type,
                f"{command}" + (f" (by {actor})" if actor else ""),
                json.dumps(payload, default=str) if payload is not None else None,
                status,
                json.dumps(result, default=str) if result is not None else None,
                error,
                created,
                finished,
            ),
        )
        conn.execute(
            "DELETE FROM veridiq_agent_commands WHERE id < (SELECT MAX(id) - 500 FROM veridiq_agent_commands)"
        )
    return {
        "command_uuid": command_uuid,
        "agent_type": agent_type,
        "command": command,
        "payload": payload,
        "status": status,
        "result": result,
        "error": error,
        "created_at": created,
        "finished_at": finished,
    }


def list_commands(agent_type: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
    _ensure()
    query = "SELECT * FROM veridiq_agent_commands"
    params: list[Any] = []
    if agent_type:
        query += " WHERE agent_type = ?"
        params.append(agent_type)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, limit))
    with db_session() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [_row_to_command(r) for r in rows]


# ---------------------------------------------------------------------------
# Campaign / task assignment log
# ---------------------------------------------------------------------------

def _row_to_assignment(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d.pop("id", None)
    payload_json = d.pop("payload_json", None)
    result_json = d.pop("result_json", None)
    d["payload"] = json.loads(payload_json) if payload_json else None
    d["result"] = json.loads(result_json) if result_json else None
    return d


def _insert_assignment(
    agent_type: str, campaign_type: str, payload: Optional[dict[str, Any]]
) -> str:
    _ensure()
    assignment_uuid = str(uuid.uuid4())
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO veridiq_agent_assignments
                (assignment_uuid, agent_type, campaign_type, payload_json, status, created_at)
            VALUES (?, ?, ?, ?, 'running', ?)
            """,
            (assignment_uuid, agent_type, campaign_type, json.dumps(payload, default=str) if payload else None, _utc_now()),
        )
        conn.execute(
            "DELETE FROM veridiq_agent_assignments WHERE id < (SELECT MAX(id) - 500 FROM veridiq_agent_assignments)"
        )
    return assignment_uuid


def _finish_assignment(assignment_uuid: str, *, status: str, result: Optional[dict[str, Any]], error: Optional[str]) -> None:
    with db_session() as conn:
        conn.execute(
            """
            UPDATE veridiq_agent_assignments
            SET status = ?, result_json = ?, error = ?, finished_at = ?
            WHERE assignment_uuid = ?
            """,
            (status, json.dumps(result, default=str) if result is not None else None, error, _utc_now(), assignment_uuid),
        )


def list_assignments(agent_type: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
    _ensure()
    query = "SELECT * FROM veridiq_agent_assignments"
    params: list[Any] = []
    if agent_type:
        query += " WHERE agent_type = ?"
        params.append(agent_type)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, limit))
    with db_session() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [_row_to_assignment(r) for r in rows]


# ---------------------------------------------------------------------------
# Command execution — real dispatch through existing systems
# ---------------------------------------------------------------------------

def _execute_run_task(agent_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    from veridiq.agents import get_agent
    from veridiq.workforce.pool import global_worker_pool

    agent = get_agent(agent_type)
    # An empty payload would deterministically fail agents that require input
    # (fact_checking, web_search, ...) — fall back to the same representative
    # sample payload "Run Agent Test" uses, so a bare Start/Run click always
    # exercises a real, meaningful code path instead of a guaranteed error.
    effective_payload = payload
    if not effective_payload:
        from veridiq.integrations.agent_test import SAMPLE_PAYLOADS

        effective_payload = dict(SAMPLE_PAYLOADS.get(agent_type, {}))

    def _fn():
        return agent.run(effective_payload, job_id=payload.get("job_id"))

    return global_worker_pool.run_agent_task(
        agent_type=agent_type,
        fn=_fn,
        job_id=payload.get("job_id"),
        task=payload.get("task") or f"Admin command run for {agent_type}",
    )


def send_command(
    agent_type: str, command: str, payload: Optional[dict[str, Any]] = None, *, actor: Optional[str] = None
) -> dict[str, Any]:
    """Execute an admin command against a live agent. Real dispatch — never fabricated."""
    if not _known_agent(agent_type):
        raise UnknownAgentError(agent_type)
    payload = payload or {}

    try:
        assert_runnable(agent_type)
    except AgentStoppedError as exc:
        rejection_status = f"rejected_agent_{exc.status}"
        rec = record_command(
            agent_type,
            command=command,
            payload=payload,
            status=rejection_status,
            error=f"agent is {exc.status}",
            actor=actor,
        )
        return {**rec, "ok": False, "status": rejection_status}

    if command == "ping":
        from veridiq.workforce.identities import identity_for

        result = {"pong": True, "identity": identity_for(agent_type)}
        rec = record_command(agent_type, command=command, payload=payload, status="completed", result=result, actor=actor)
        return {"ok": True, "status": "completed", **rec}

    if command == "run_task":
        try:
            result = _execute_run_task(agent_type, payload)
            ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
            rec = record_command(
                agent_type,
                command=command,
                payload=payload,
                status="completed" if ok else "failed",
                result=result,
                error=None if ok else (result or {}).get("error"),
                actor=actor,
            )
            return {"ok": ok, "status": rec["status"], **rec}
        except Exception as exc:  # pragma: no cover - defensive
            rec = record_command(agent_type, command=command, payload=payload, status="failed", error=str(exc)[:400], actor=actor)
            return {"ok": False, "status": "failed", **rec}

    rec = record_command(
        agent_type,
        command=command,
        payload=payload,
        status="unsupported",
        error=f"Unknown command '{command}'. Supported: ping, run_task.",
        actor=actor,
    )
    return {"ok": False, "status": "unsupported", **rec}


# ---------------------------------------------------------------------------
# Campaign assignment — routes into existing pipelines/integrations
# ---------------------------------------------------------------------------

SUPPORTED_CAMPAIGN_TYPES = ("run_task", "verify", "market_intelligence", "comms", "ai_calling", "marketing")


def assign_campaign(
    agent_type: str, campaign_type: str, payload: Optional[dict[str, Any]] = None, *, actor: Optional[str] = None
) -> dict[str, Any]:
    """Assign a campaign/task to an agent through the real pipeline it belongs to."""
    if not _known_agent(agent_type):
        raise UnknownAgentError(agent_type)
    payload = payload or {}

    try:
        assert_runnable(agent_type)
    except AgentStoppedError as exc:
        return {"ok": False, "status": f"rejected_agent_{exc.status}", "agent_type": agent_type, "campaign_type": campaign_type}

    assignment_uuid = _insert_assignment(agent_type, campaign_type, payload)

    try:
        if campaign_type == "run_task":
            result = _execute_run_task(agent_type, payload)
            ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
            status = "completed" if ok else "failed"
            _finish_assignment(assignment_uuid, status=status, result=result, error=None if ok else (result or {}).get("error"))

        elif campaign_type == "verify":
            from veridiq.pipeline.truth_pipeline import global_pipeline

            text = str(payload.get("text") or "").strip()
            if not text:
                raise ValueError("payload.text is required for a verify campaign")
            result = global_pipeline.run_async(title=payload.get("title") or f"Assigned via {agent_type}", text=text)
            _finish_assignment(assignment_uuid, status="queued", result=result, error=None)

        elif campaign_type == "market_intelligence":
            from veridiq.orchestration.market_graph import run_market_intelligence
            from veridiq.orchestration.task_router import new_job_id

            text = str(payload.get("text") or "Market snapshot request").strip()
            job_id = new_job_id()
            result = run_market_intelligence(text, job_id=job_id, coin_id=payload.get("coin_id", "bitcoin"))
            _finish_assignment(assignment_uuid, status="completed", result=result, error=None)

        elif campaign_type == "comms":
            from veridiq.comms import draft_communication

            context = str(payload.get("context") or payload.get("text") or "").strip()
            if not context:
                raise ValueError("payload.context is required for a comms campaign")
            result = draft_communication(
                kind=payload.get("kind", "email"), context=context, recipient_hint=payload.get("recipient_hint", "")
            )
            _finish_assignment(assignment_uuid, status="draft_ready", result=result, error=None)

        elif campaign_type == "marketing":
            from veridiq.marketing.campaigns import generate_daily_pack

            marketing_campaign_id = str(payload.get("campaign_id") or "")
            if not marketing_campaign_id:
                raise ValueError("payload.campaign_id is required for a marketing campaign assignment")
            result = generate_daily_pack(
                marketing_campaign_id,
                channels=payload.get("channels"),
                features=payload.get("features"),
                created_by_agent=agent_type,
            )
            ok = bool(result.get("ok"))
            _finish_assignment(
                assignment_uuid,
                status="drafts_queued" if ok else "failed",
                result=result,
                error=None if ok else result.get("error"),
            )

        elif campaign_type == "ai_calling":
            if agent_type != "ai_calling":
                raise ValueError("ai_calling campaigns can only be assigned to the ai_calling agent")
            from veridiq.calling.campaigns import create_campaign

            result = create_campaign(
                to_number=str(payload.get("to_number") or ""),
                purpose=payload.get("purpose", "AI calling campaign"),
                script=str(payload.get("script") or ""),
                contact_name=payload.get("contact_name", ""),
            )
            _finish_assignment(assignment_uuid, status="queued_for_approval", result=result, error=None)

        else:
            _finish_assignment(
                assignment_uuid,
                status="unsupported",
                result=None,
                error=f"Unknown campaign_type '{campaign_type}'. Supported: {', '.join(SUPPORTED_CAMPAIGN_TYPES)}.",
            )
            return {
                "ok": False,
                "status": "unsupported",
                "assignment_uuid": assignment_uuid,
                "message": f"Unknown campaign_type '{campaign_type}'. Supported: {', '.join(SUPPORTED_CAMPAIGN_TYPES)}.",
            }

    except Exception as exc:
        _finish_assignment(assignment_uuid, status="failed", result=None, error=str(exc)[:400])
        record_command(agent_type, command=f"assign_campaign:{campaign_type}", payload=payload, status="failed", error=str(exc)[:400], actor=actor)
        return {"ok": False, "status": "failed", "assignment_uuid": assignment_uuid, "error": str(exc)[:400]}

    record_command(agent_type, command=f"assign_campaign:{campaign_type}", payload=payload, status="completed", actor=actor)
    assignment = next((a for a in list_assignments(agent_type, limit=1) if a["assignment_uuid"] == assignment_uuid), None)
    return {"ok": True, "assignment": assignment}


def agent_runtime_overview(agent_type: str) -> dict[str, Any]:
    """Combined control + command history + assignment history for one agent."""
    return {
        "agent_type": agent_type,
        "control": get_control(agent_type),
        "commands": list_commands(agent_type, limit=30),
        "assignments": list_assignments(agent_type, limit=30),
    }
