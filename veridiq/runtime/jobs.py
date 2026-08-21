"""Unified Live Agent Runtime job listing — merges persisted verification jobs
with in-flight jobs that only exist in the worker pool (e.g. market
intelligence / comms runs), so the runtime page can find any live job.
Nothing here is fabricated: an in-flight entry only appears while a real
worker assignment references its job_id.
"""

from __future__ import annotations

from typing import Any


def list_runtime_jobs(limit: int = 20) -> list[dict[str, Any]]:
    from veridiq.pipeline.truth_pipeline import global_pipeline
    from veridiq.workforce.pool import global_worker_pool

    jobs = global_pipeline.list_jobs(limit=limit)
    for j in jobs:
        j["mode"] = "truth_verification"
    known_ids = {j["job_uuid"] for j in jobs}

    pool = global_worker_pool.snapshot()
    live_entries: list[dict[str, Any]] = []
    seen_live: set[str] = set()
    for a in pool.get("assignments") or []:
        jid = a.get("job_id")
        if not jid or jid in known_ids or jid in seen_live:
            continue
        seen_live.add(jid)
        live_entries.append(
            {
                "job_uuid": jid,
                "title": a.get("task") or f"Live {a.get('agent_type', 'agent')} job",
                "status": "processing",
                "truth_score": None,
                "risk_level": None,
                "created_at": a.get("started_at"),
                "updated_at": None,
                "completed_at": None,
                "mode": "live_assignment",
                "agent_type": a.get("agent_type"),
                "stage": a.get("stage"),
                "progress": a.get("progress"),
            }
        )
    return live_entries + jobs
