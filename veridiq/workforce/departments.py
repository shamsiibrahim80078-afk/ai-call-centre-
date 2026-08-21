"""Department taxonomy for VERIDIQ AI teams."""

from __future__ import annotations

from typing import Any, Optional

from veridiq.workforce.identities import identity_for
from veridiq.workforce.pool import global_worker_pool

DEPARTMENTS: dict[str, dict[str, Any]] = {
    "verification": {
        "name": "Verification",
        "description": "Claim extraction, fact-checking, and disposition",
        "agents": ["statement_verification", "fact_checking", "decision", "confidence_scoring"],
    },
    "investigation": {
        "name": "Investigation",
        "description": "Evidence packaging, timelines, and risk",
        "agents": ["evidence_collection", "timeline_builder", "risk_analysis", "citation"],
    },
    "research": {
        "name": "Research",
        "description": "Open-web research and source credibility",
        "agents": ["web_search", "source_credibility", "orchestrator"],
    },
    "market_intelligence": {
        "name": "Market Intelligence",
        "description": "Crypto/market analysis and probabilistic scenarios",
        "agents": [
            "market_research",
            "onchain_analysis",
            "news_correlation",
            "sentiment_analysis",
            "macro_trend",
            "technical_analysis",
            "market_risk",
            "portfolio_intelligence",
        ],
    },
    "marketing": {
        "name": "Marketing",
        "description": "Narrative framing plus agency content/social specialists (SEO/content/social map here)",
        "agents": [
            "report_generator",
            "conversation_memory",
            "content_creator",
            "social_poster",
            "x_twitter_voice",
        ],
    },
    "influencer_intelligence": {
        "name": "Influencer Intelligence",
        "description": "Public narrative, creator research, and influencer engagement (via marketing agency Adrian)",
        "agents": [
            "sentiment_analysis",
            "news_correlation",
            "web_search",
            "influencer_relations",
        ],
    },
    "news_analysis": {
        "name": "News",
        "description": "News corroboration and media signals",
        "agents": ["news_verification", "web_search"],
    },
    "meeting_analysis": {
        "name": "Meeting",
        "description": "Transcript decomposition and chronology",
        "agents": ["meeting_analysis", "timeline_builder"],
    },
    "voice_intelligence": {
        "name": "Voice",
        "description": "Audio energy and stress proxies",
        "agents": ["voice_analysis", "lie_detection"],
    },
    "vision_intelligence": {
        "name": "Vision",
        "description": "Face presence and visual inconsistency cues",
        "agents": ["face_analysis"],
    },
    "blockchain": {
        "name": "Blockchain",
        "description": "Attestation readiness and on-chain preparation",
        "agents": ["report_generator"],
    },
    "reporting": {
        "name": "Reporting",
        "description": "Truth reports, memory, and emotion context",
        "agents": ["report_generator", "conversation_memory", "emotion_detection"],
    },
    "customer_success": {
        "name": "Customer Success",
        "description": "Session memory and explainable outcomes for operators",
        "agents": ["conversation_memory", "confidence_scoring", "decision"],
    },
    "ai_calling": {
        "name": "AI Calling",
        "description": "Twilio-backed call campaigns with approval-gated dialing and CRM follow-up",
        "agents": ["ai_calling"],
    },
    "linkedin": {
        "name": "LinkedIn",
        "description": "Official LinkedIn API outreach and profile connectivity",
        "agents": ["linkedin_outreach"],
    },
    "sales": {
        "name": "Sales",
        "description": "CRM-backed pipeline readiness and outreach framing",
        "agents": ["sales_intelligence", "report_generator"],
    },
    "marketing_agency": {
        "name": "Marketing Agency",
        "description": "Campaign management, daily content, social posting, and influencer engagement for VeriDiQ",
        "agents": [
            "marketing_manager",
            "content_creator",
            "social_poster",
            "telegram_community",
            "x_twitter_voice",
            "influencer_relations",
        ],
    },
    "executive": {
        "name": "Executive",
        "description": "CEO and Directors that coordinate all agent teams through the VERIDIQ Agent SDK",
        "agents": ["ceo", "director_operations", "director_growth", "director_intelligence"],
    },
}


def department_for_agent(agent_type: str) -> Optional[dict[str, Any]]:
    # Prefer home departments when an agent is multi-homed (e.g. influencer_relations
    # sits on Marketing Agency and Influencer Intelligence).
    preferred = (
        "marketing_agency",
        "executive",
        "market_intelligence",
        "verification",
        "investigation",
        "ai_calling",
        "linkedin",
        "sales",
    )
    for key in preferred:
        meta = DEPARTMENTS.get(key)
        if meta and agent_type in meta["agents"]:
            return {"id": key, "name": meta["name"], "description": meta["description"]}
    for key, meta in DEPARTMENTS.items():
        if agent_type in meta["agents"]:
            return {"id": key, "name": meta["name"], "description": meta["description"]}
    return None


def department_snapshot() -> dict[str, Any]:
    pool = global_worker_pool.snapshot()
    assignments = pool.get("assignments") or []
    stats = pool.get("agent_stats") or {}
    history = pool.get("recent_history") or []
    departments = []
    for key, meta in DEPARTMENTS.items():
        agents = meta["agents"]
        active = [a for a in assignments if a.get("agent_type") in agents]
        agent_stats = [stats.get(a, {}) for a in agents if a in stats]
        runs = sum(int(s.get("runs") or 0) for s in agent_stats)
        ok = sum(int(s.get("ok") or 0) for s in agent_stats)
        success = round(ok / runs, 4) if runs else None
        recent_jobs = [h for h in history if h.get("agent_type") in agents][:8]
        departments.append(
            {
                "id": key,
                "name": meta["name"],
                "description": meta["description"],
                "agents": [
                    {
                        "agent_type": a,
                        "identity": identity_for(a),
                        "status": "working" if any(x["agent_type"] == a for x in active) else "idle",
                    }
                    for a in agents
                ],
                "live_worker_count": len(active),
                "workload": {
                    "active_workers": len(active),
                    "queue": len(active),
                    "success_rate": success,
                    "runs": runs,
                    "performance": {
                        "avg_latency_ms": round(
                            sum(float(s.get("avg_latency_ms") or 0) for s in agent_stats if s.get("avg_latency_ms"))
                            / max(1, sum(1 for s in agent_stats if s.get("avg_latency_ms"))),
                            2,
                        )
                        if any(s.get("avg_latency_ms") for s in agent_stats)
                        else None,
                    },
                },
                "current_projects": [
                    {
                        "task": a.get("task"),
                        "agent_type": a.get("agent_type"),
                        "progress": a.get("progress"),
                        "job_id": a.get("job_id"),
                    }
                    for a in active
                ],
                "recent_completed_jobs": recent_jobs,
                "live_metrics": {
                    "waiting_for_tasks": len(active) == 0,
                    "status_label": "Waiting for Assignment" if not active else "Processing",
                },
            }
        )
    return {
        "count": len(departments),
        "departments": departments,
        "timestamp": pool.get("timestamp"),
    }
