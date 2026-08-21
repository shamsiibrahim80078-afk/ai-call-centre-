"""Workforce roster — live persona cards driven by pool + identities (no fake activity)."""

from __future__ import annotations

from typing import Any, Optional

from veridiq.agents import AGENT_REGISTRY
from veridiq.orchestration.graph_map import nodes_for_agent
from veridiq.workforce.departments import DEPARTMENTS, department_for_agent
from veridiq.workforce.identities import identity_for
from veridiq.workforce.pool import global_worker_pool
from veridiq.workforce.stage_labels import friendly_stage

BIOS = {
    "evidence_collection": "Packages corroborating material and claim linkages for downstream verification.",
    "statement_verification": "Structures claims and maps them to supporting or conflicting evidence.",
    "fact_checking": "Cross-checks statements against retrieved sources and support scores.",
    "face_analysis": "Estimates presence and inconsistency cues when imagery is available.",
    "voice_analysis": "Derives energy and stress proxies from audio waveforms.",
    "news_verification": "Scans news-oriented corroboration signals for claim support.",
    "meeting_analysis": "Decomposes meeting transcripts into speakers, topics, and actions.",
    "market_research": "Assembles official market snapshots and evidence packages.",
    "orchestrator": "Plans LangGraph stage routing and specialist assignment.",
    "ai_calling": "Queues Twilio Voice campaigns and reports readiness; never auto-dials without approval.",
    "linkedin_outreach": "Drafts LinkedIn outreach via the official OAuth API, gated by comms approval.",
    "sales_intelligence": "Reviews CRM/email readiness and frames pipeline context without inventing deal data.",
    "marketing_manager": "Renata orchestrates campaigns and keeps the queue honest — every post is drafted in her voice, then waits for your approval.",
    "content_creator": "Jasper writes feature stories with a human arc — LinkedIn-first, no generic AI filler.",
    "social_poster": "Lena shapes Instagram and feed copy — punchy captions that read like a real social lead wrote them.",
    "telegram_community": "Theo runs community tone on Telegram — casual replies and education posts, not bot spam.",
    "x_twitter_voice": "Nova drafts X posts with wit and short lines — variants that don't all sound identical.",
    "influencer_relations": "Adrian brings first-person influencer hooks across X, Telegram, LinkedIn, Instagram, and Threads — plus public creator research — always draft-first until you approve.",
}


def _system_resources() -> dict[str, Any]:
    try:
        import psutil

        proc = psutil.Process()
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.0),
            "memory_mb": round(proc.memory_info().rss / (1024 * 1024), 2),
            "scope": "process",
            "note": "Process-level resources — not fabricated per-worker counters.",
        }
    except Exception:
        return {"cpu_percent": None, "memory_mb": None, "scope": "unavailable"}


def build_roster(*, department: Optional[str] = None, q: Optional[str] = None) -> dict[str, Any]:
    from veridiq.workforce.control import list_controls

    pool = global_worker_pool.snapshot()
    assignments = {a["agent_type"]: a for a in pool.get("assignments") or []}
    stats = pool.get("agent_stats") or {}
    history = pool.get("recent_history") or []
    resources = _system_resources()
    controls = list_controls()

    cards = []
    for agent_type in sorted(AGENT_REGISTRY.keys()):
        dept = department_for_agent(agent_type)
        if department and (not dept or dept["id"] != department):
            continue
        ident = identity_for(agent_type)
        if q:
            blob = f"{ident.get('name')} {ident.get('role')} {agent_type} {(dept or {}).get('name', '')}".lower()
            if q.lower() not in blob:
                continue
        assignment = assignments.get(agent_type)
        st = stats.get(agent_type) or {}
        agent_history = [h for h in history if h.get("agent_type") == agent_type]
        last = agent_history[0] if agent_history else None
        working = assignment is not None
        last_status = None
        if not working and last is not None:
            last_status = "completed" if last.get("ok") else "failed"
        control = controls.get(agent_type) or {"status": "running", "status_label": "Running"}
        controlled_off = control["status"] in {"stopped", "paused"}
        status_label = "Working" if working else "Waiting for Assignment"
        if controlled_off:
            status_label = control["status_label"]
        cards.append(
            {
                "agent_type": agent_type,
                "name": ident.get("name"),
                "role": ident.get("role"),
                "specialty": ident.get("specialty"),
                "email": ident.get("internal_email"),
                "biography": BIOS.get(agent_type)
                or f"{ident.get('name')} is a VERIDIQ AI persona specializing in {ident.get('specialty')}. Not a real person.",
                "skills": ident.get("skills") or [],
                "avatar_hue": ident.get("avatar_hue"),
                "department": dept,
                "status": "working" if working else "idle",
                "status_label": status_label,
                "control_status": control["status"],
                "control_status_label": control["status_label"],
                "last_status": last_status,
                "current_task": (assignment or {}).get("task"),
                "progress": (assignment or {}).get("progress"),
                "queue_position": None if not working else 1,
                "confidence": (assignment or {}).get("confidence"),
                "workflow_stage": friendly_stage((assignment or {}).get("stage")),
                "workflow_stage_raw": (assignment or {}).get("stage"),
                "started_at": (assignment or {}).get("started_at"),
                "estimated_completion_sec": (assignment or {}).get("eta_sec"),
                "elapsed_sec": (assignment or {}).get("elapsed_sec"),
                "job_id": (assignment or {}).get("job_id"),
                "worker_id": (assignment or {}).get("worker_id"),
                "cpu_percent": resources.get("cpu_percent") if working else None,
                "memory_mb": resources.get("memory_mb") if working else None,
                "tokens_processed": None,  # not tracked — never fabricate
                "last_completed_task": (last or {}).get("task"),
                "last_completed_at": (last or {}).get("finished_at"),
                "activity_history": agent_history[:10],
                "langgraph_nodes": nodes_for_agent(agent_type),
                "metrics": {
                    "runs": st.get("runs", 0),
                    "success_rate": st.get("success_rate"),
                    "avg_latency_ms": st.get("avg_latency_ms"),
                    "reliability_score": st.get("success_rate"),
                },
                "assigned_models": ["VERIDIQ specialist heuristics", "LangGraph orchestration"],
                "connected_tools": ["SSE event bus", "Qdrant RAG", "SQLite run log", "Worker pool"],
            }
        )

    return {
        "count": len(cards),
        "cards": cards,
        "workforce": pool,
        "resources": resources,
        "departments": [{"id": k, "name": v["name"]} for k, v in DEPARTMENTS.items()],
        "filters": {"department": department, "q": q},
        "idle_label": "Waiting for Assignment",
    }
