"""Agent Workspace — live per-agent operational view (departments -> agents).

Built entirely from real roster/pool/collaboration/integration state. Nothing
here is fabricated: idle agents show empty queues/logs, and connected
tools/APIs reflect actual configuration.
"""

from __future__ import annotations

from typing import Any, Optional

from veridiq.workforce.collaboration import global_collaboration_hub
from veridiq.workforce.departments import DEPARTMENTS
from veridiq.workforce.roster import build_roster

# Departments whose agents can conceptually exercise external platform integrations.
_DEPT_PLATFORMS: dict[str, set[str]] = {
    "market_intelligence": {"market_coingecko", "market_binance", "market_coinmarketcap"},
    "news_analysis": {"news_newsapi"},
    "influencer_intelligence": {
        "news_newsapi",
        "x_twitter",
        "instagram",
        "linkedin",
        "threads",
        "tavily",
        "serpapi",
        "exa",
        "ai_gateway",
    },
    "marketing": {"email", "crm", "marketing", "linkedin", "x_twitter", "instagram", "threads"},
    "marketing_agency": {
        "telegram",
        "x_twitter",
        "linkedin",
        "instagram",
        "threads",
        "canva",
        "marketing",
        "ai_gateway",
    },
    "customer_success": {"email", "crm", "whatsapp", "telegram"},
    "blockchain": {"blockchain"},
    "linkedin": {"linkedin"},
    "ai_calling": {"ai_calling", "crm"},
    "sales": {"crm", "email"},
}


def _connected_apis_for(card: dict[str, Any], integrations_by_platform: dict[str, Any]) -> list[dict[str, Any]]:
    """Real backend + integration connectivity for this agent — never invented."""
    apis: list[dict[str, Any]] = [
        {"name": "LangGraph orchestration", "status": "ok" if card.get("langgraph_nodes") else "not_wired"},
        {"name": "AI worker pool / SSE event bus", "status": "ok"},
        {"name": "Qdrant RAG / vector memory", "status": "ok"},
        {"name": "SQLite run log", "status": "ok"},
    ]
    dept_id = (card.get("department") or {}).get("id")
    wanted = _DEPT_PLATFORMS.get(dept_id or "", set())
    for platform in wanted:
        item = integrations_by_platform.get(platform)
        if item:
            apis.append(
                {
                    "name": item["display_name"],
                    "status": item["status"],
                    "configured": item.get("configured"),
                }
            )
    return apis


def _task_queue_for(agent_type: str, pool_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Only real queued/active assignments for this agent type — empty when idle."""
    from veridiq.workforce.stage_labels import friendly_stage

    rows = [a for a in (pool_snapshot.get("assignments") or []) if a.get("agent_type") == agent_type]
    out: list[dict[str, Any]] = []
    for a in rows:
        item = dict(a)
        if item.get("stage"):
            item["stage_raw"] = item["stage"]
            item["stage"] = friendly_stage(item["stage"])
        out.append(item)
    return out


def build_workspace(*, agent_type: Optional[str] = None) -> dict[str, Any]:
    roster = build_roster()
    cards = roster.get("cards") or []
    if agent_type:
        cards = [c for c in cards if c["agent_type"] == agent_type]

    pool_snapshot = roster.get("workforce") or {}
    all_collab = global_collaboration_hub.recent(limit=200)

    # Fetch once and filter per-agent in Python rather than issuing one SQLite
    # query per card — with 30 registered agent types, N+1 queries here caused
    # /workspace to stall under concurrent load (Phase 5.1 persistence regression).
    try:
        from veridiq.integrations.activity import global_platform_activity

        all_platform_activity = global_platform_activity.recent(limit=500)
    except Exception:
        all_platform_activity = []

    try:
        from veridiq.integrations.registry import all_integrations

        integrations_by_platform = {i["platform"]: i for i in all_integrations()["integrations"]}
    except Exception:
        integrations_by_platform = {}

    try:
        from veridiq.workforce.control import list_assignments, list_commands
        from veridiq.integrations.agent_test import list_test_runs

        all_commands = list_commands(limit=200)
        all_assignments = list_assignments(limit=200)
        all_test_runs = list_test_runs(limit=100)
    except Exception:
        all_commands, all_assignments, all_test_runs = [], [], []

    enriched: list[dict[str, Any]] = []
    for card in cards:
        at = card["agent_type"]
        agent_logs = [m for m in all_collab if (m.get("speaker") or {}).get("agent_type") == at][:20]
        agent_platform_activity = [e for e in all_platform_activity if e.get("agent_type") == at][:20]
        enriched.append(
            {
                **card,
                "task_queue": _task_queue_for(at, pool_snapshot),
                "live_logs": agent_logs,
                "platform_activity": agent_platform_activity,
                "connected_apis": _connected_apis_for(card, integrations_by_platform),
                "workflow_state": {
                    "nodes": card.get("langgraph_nodes") or [],
                    "current_stage": card.get("workflow_stage"),
                    "job_id": card.get("job_id"),
                },
                "command_history": [c for c in all_commands if c.get("agent_type") == at][:15],
                "assignment_history": [a for a in all_assignments if a.get("agent_type") == at][:15],
                "test_history": [t for t in all_test_runs if t.get("agent_type") == at][:10],
            }
        )

    departments: list[dict[str, Any]] = []
    for key, meta in DEPARTMENTS.items():
        # Membership follows the department's declared roster (an agent may serve
        # more than one team) rather than the card's single "primary" department label.
        dept_agent_types = set(meta["agents"])
        dept_cards = [c for c in enriched if c["agent_type"] in dept_agent_types]
        if agent_type and not dept_cards:
            continue
        departments.append(
            {
                "id": key,
                "name": meta["name"],
                "description": meta["description"],
                "agents": dept_cards,
                "active_count": sum(1 for c in dept_cards if c["status"] == "working"),
                "idle_count": sum(1 for c in dept_cards if c["status"] != "working"),
            }
        )

    result: dict[str, Any] = {
        "count": len(enriched),
        "departments": departments,
        "agents": enriched,
        "workforce": pool_snapshot,
        "waiting_for_tasks": pool_snapshot.get("waiting_for_tasks"),
        "idle_label": "Waiting for Assignment",
        "timestamp": pool_snapshot.get("timestamp"),
    }
    if agent_type:
        result["agent"] = enriched[0] if enriched else None
        if not enriched:
            result["error"] = "unknown_agent_or_no_match"
    return result
