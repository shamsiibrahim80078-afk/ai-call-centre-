"""Live agent monitoring — status, task, logs, progress, confidence, ETA."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from database import db_session, initialize_database
from veridiq.workforce.identities import identity_for
from veridiq.workforce.pool import global_worker_pool
from veridiq.workforce.stage_labels import friendly_stage


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def live_agent_monitor(*, agent_type: Optional[str] = None, limit: int = 40) -> dict[str, Any]:
    """Aggregate pool assignments + SDK tasks into a live monitoring feed."""
    initialize_database()
    pool = global_worker_pool.snapshot()
    assignments = pool.get("assignments") or []
    history = pool.get("recent_history") or []
    stats = pool.get("agent_stats") or {}

    with db_session() as conn:
        if agent_type:
            sdk_rows = conn.execute(
                """
                SELECT * FROM veridiq_sdk_tasks
                WHERE from_agent = ? OR to_agent = ?
                ORDER BY id DESC LIMIT ?
                """,
                (agent_type, agent_type, limit),
            ).fetchall()
            stream_rows = conn.execute(
                """
                SELECT stream_id, agent_type, task_id, chunk_json, done, created_at
                FROM veridiq_sdk_streams
                WHERE agent_type = ?
                ORDER BY id DESC LIMIT ?
                """,
                (agent_type, min(limit, 20)),
            ).fetchall()
        else:
            sdk_rows = conn.execute(
                """
                SELECT * FROM veridiq_sdk_tasks
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            stream_rows = conn.execute(
                """
                SELECT stream_id, agent_type, task_id, chunk_json, done, created_at
                FROM veridiq_sdk_streams
                ORDER BY id DESC LIMIT ?
                """,
                (min(limit, 20),),
            ).fetchall()

    agents_live = []
    for a in assignments:
        at = a.get("agent_type")
        if agent_type and at != agent_type:
            continue
        st = stats.get(at) or {}
        agents_live.append(
            {
                "agent_type": at,
                "identity": identity_for(at),
                "status": "working",
                "task": a.get("task"),
                "job_id": a.get("job_id"),
                "progress": a.get("progress"),
                "stage": friendly_stage(a.get("stage")),
                "stage_raw": a.get("stage"),
                "eta_sec": a.get("eta_sec"),
                "confidence": st.get("last_confidence"),
                "logs": [friendly_stage(a.get("stage")), a.get("task")],
                "metrics": {
                    "runs": st.get("runs", 0),
                    "success_rate": st.get("success_rate"),
                    "avg_latency_ms": st.get("avg_latency_ms"),
                },
            }
        )

    idle_types = set()
    if agent_type:
        idle_types = {agent_type} if not agents_live else set()
    else:
        from veridiq.agents import AGENT_REGISTRY

        busy = {a["agent_type"] for a in agents_live}
        idle_types = set(AGENT_REGISTRY.keys()) - busy

    for at in sorted(idle_types)[:60]:
        st = stats.get(at) or {}
        agents_live.append(
            {
                "agent_type": at,
                "identity": identity_for(at),
                "status": "idle",
                "task": None,
                "job_id": None,
                "progress": 0.0,
                "stage": "Waiting for Assignment",
                "eta_sec": None,
                "confidence": st.get("last_confidence"),
                "logs": ["Waiting for Assignment"],
                "metrics": {
                    "runs": st.get("runs", 0),
                    "success_rate": st.get("success_rate"),
                    "avg_latency_ms": st.get("avg_latency_ms"),
                },
            }
        )

    sdk_tasks = []
    for row in sdk_rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            item["payload"] = item.pop("payload_json", None)
        if item.get("result_json"):
            try:
                item["result"] = json.loads(item.pop("result_json"))
            except (json.JSONDecodeError, TypeError):
                item["result"] = item.pop("result_json")
        else:
            item.pop("result_json", None)
        sdk_tasks.append(item)

    streams = []
    for row in stream_rows:
        item = dict(row)
        try:
            item["chunk"] = json.loads(item.pop("chunk_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            item["chunk"] = item.pop("chunk_json", None)
        streams.append(item)

    return {
        "count": len(agents_live),
        "working": sum(1 for a in agents_live if a["status"] == "working"),
        "idle": sum(1 for a in agents_live if a["status"] == "idle"),
        "agents": agents_live,
        "sdk_tasks": sdk_tasks,
        "streams": streams,
        "recent_history": [
            h for h in history if (not agent_type or h.get("agent_type") == agent_type)
        ][:limit],
        "timestamp": _utc_now(),
    }
