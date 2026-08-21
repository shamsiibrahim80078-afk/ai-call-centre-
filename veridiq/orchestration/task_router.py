"""Intelligent task routing — break requests into department/agent plans."""

from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from veridiq.orchestration.events import global_job_events
from veridiq.workforce.collaboration import global_collaboration_hub


INTENT_RULES: list[tuple[str, list[str]]] = [
    ("market", [r"\b(crypto|bitcoin|btc|eth|market|token|trading|coingecko|portfolio)\b"]),
    ("news", [r"\b(news|headline|breaking|press)\b"]),
    ("meeting", [r"\b(meeting|transcript|agenda|call notes)\b"]),
    ("comms", [r"\b(email|outreach|follow[- ]?up|agenda|contact notes)\b"]),
    ("investigate", [r"\b(investigate|company|diligence|osint)\b"]),
    ("verify", [r"\b(verify|speech|claim|truth|fact[- ]?check)\b"]),
]


def classify_intent(text: str) -> str:
    t = (text or "").lower()
    for intent, patterns in INTENT_RULES:
        for p in patterns:
            if re.search(p, t):
                return intent
    return "verify"


def plan_request(text: str) -> dict[str, Any]:
    intent = classify_intent(text)
    plans = {
        "market": {
            "department": "market_intelligence",
            "pipeline": "market_intelligence",
            "agents": [
                "market_research",
                "technical_analysis",
                "sentiment_analysis",
                "news_correlation",
                "macro_trend",
                "onchain_analysis",
                "market_risk",
                "portfolio_intelligence",
            ],
            "parallel": True,
        },
        "news": {
            "department": "news_analysis",
            "pipeline": "truth",
            "agents": ["news_verification", "web_search", "source_credibility", "fact_checking"],
            "parallel": True,
        },
        "meeting": {
            "department": "meeting_analysis",
            "pipeline": "truth",
            "agents": ["meeting_analysis", "timeline_builder", "statement_verification"],
            "parallel": True,
        },
        "comms": {
            "department": "reporting",
            "pipeline": "comms",
            "agents": ["conversation_memory", "report_generator"],
            "parallel": False,
        },
        "investigate": {
            "department": "investigation",
            "pipeline": "truth",
            "agents": ["web_search", "evidence_collection", "source_credibility", "risk_analysis", "fact_checking"],
            "parallel": True,
        },
        "verify": {
            "department": "verification",
            "pipeline": "truth",
            "agents": ["orchestrator", "evidence_collection", "statement_verification", "fact_checking", "confidence_scoring"],
            "parallel": True,
        },
    }
    plan = plans[intent]
    return {
        "intent": intent,
        "request": text,
        "department": plan["department"],
        "pipeline": plan["pipeline"],
        "subtasks": [{"agent_type": a, "task": f"Execute {a}"} for a in plan["agents"]],
        "parallel": plan["parallel"],
        "workflow_stages": [
            "user_request",
            "task_planner",
            "agent_assignment",
            "evidence_retrieval",
            "verification",
            "reasoning",
            "report_generation",
            "completed",
        ],
    }


def emit_plan(job_id: str, plan: dict[str, Any]) -> None:
    global_job_events.emit(job_id, "route", f"Intent={plan['intent']} → {plan['department']}")
    global_collaboration_hub.record_event(
        job_id=job_id,
        stage="route",
        message=f"Task planner selected {plan['department']} ({plan['intent']}).",
        agent_type="orchestrator",
    )
    for sub in plan.get("subtasks") or []:
        global_collaboration_hub.record_event(
            job_id=job_id,
            stage="delegation",
            message=f"Delegating: {sub['task']}",
            agent_type=sub["agent_type"],
        )


def new_job_id() -> str:
    return str(uuid.uuid4())
