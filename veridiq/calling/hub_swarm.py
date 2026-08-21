"""High-cadence multi-thread swarm for Collaboration Hub (scripted, optional LLM).

Feels like ~100 agents collaborating across many live threads without
100 LLM calls/sec — scheduled ticks + role-specific message banks.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any, Optional

from veridiq.workforce.identities import AGENT_IDENTITIES, identity_for

# Target live working rooms (each has 3–5 specialists). Across rooms we surface
# most of the workforce roster so the hub feels densely populated.
THREAD_BLUEPRINTS: list[dict[str, Any]] = [
    {
        "key": "canva_daily",
        "topic": "Canva daily posts — logo & layout",
        "agents": ["content_creator", "social_poster", "marketing_manager", "director_growth"],
    },
    {
        "key": "influencer_outreach",
        "topic": "Influencer shortlist & outreach hooks",
        "agents": ["influencer_relations", "marketing_manager", "x_twitter_voice", "ai_calling"],
    },
    {
        "key": "telegram_community",
        "topic": "Telegram community education pack",
        "agents": ["telegram_community", "content_creator", "director_growth"],
    },
    {
        "key": "x_voice",
        "topic": "X / Twitter voice variants",
        "agents": ["x_twitter_voice", "social_poster", "influencer_relations"],
    },
    {
        "key": "linkedin_sales",
        "topic": "LinkedIn outreach pipeline",
        "agents": ["linkedin_outreach", "sales_intelligence", "director_operations"],
    },
    {
        "key": "market_intel",
        "topic": "Market intel desk — macro + sentiment",
        "agents": ["market_research", "macro_trend", "sentiment_analysis", "director_intelligence"],
    },
    {
        "key": "onchain_desk",
        "topic": "On-chain + portfolio framing",
        "agents": ["onchain_analysis", "portfolio_intelligence", "market_risk", "director_intelligence"],
    },
    {
        "key": "news_corr",
        "topic": "News correlation & credibility",
        "agents": ["news_correlation", "news_verification", "source_credibility", "web_search"],
    },
    {
        "key": "verification_core",
        "topic": "Statement verification pipeline",
        "agents": ["statement_verification", "fact_checking", "evidence_collection", "citation"],
    },
    {
        "key": "multimodal",
        "topic": "Face / voice / emotion fusion",
        "agents": ["face_analysis", "voice_analysis", "emotion_detection", "lie_detection"],
    },
    {
        "key": "risk_confidence",
        "topic": "Risk & confidence calibration",
        "agents": ["risk_analysis", "confidence_scoring", "decision", "orchestrator"],
    },
    {
        "key": "timeline_meetings",
        "topic": "Timeline builder + meeting analysis",
        "agents": ["timeline_builder", "meeting_analysis", "conversation_memory", "report_generator"],
    },
    {
        "key": "tech_ta",
        "topic": "Technical analysis desk",
        "agents": ["technical_analysis", "market_research", "market_risk"],
    },
    {
        "key": "exec_sync",
        "topic": "Executive sync — Aurelia & directors",
        "agents": ["ceo", "director_operations", "director_growth", "director_intelligence"],
    },
    {
        "key": "calling_coord",
        "topic": "Calling desk — Marcus coordinating specialists",
        "agents": ["ai_calling", "marketing_manager", "content_creator", "influencer_relations"],
    },
    {
        "key": "growth_campaign",
        "topic": "Growth campaign readiness",
        "agents": ["director_growth", "marketing_manager", "social_poster", "telegram_community"],
    },
    {
        "key": "ops_queue",
        "topic": "Ops queue — routing verification jobs",
        "agents": ["director_operations", "orchestrator", "report_generator", "decision"],
    },
    {
        "key": "evidence_pack",
        "topic": "Evidence packaging for truth reports",
        "agents": ["evidence_collection", "citation", "report_generator", "confidence_scoring"],
    },
    {
        "key": "web_research",
        "topic": "Open-web research sprint",
        "agents": ["web_search", "news_verification", "fact_checking"],
    },
    {
        "key": "sales_crm",
        "topic": "Sales intelligence & CRM readiness",
        "agents": ["sales_intelligence", "linkedin_outreach", "director_operations"],
    },
    {
        "key": "deception_desk",
        "topic": "Deception signals review",
        "agents": ["lie_detection", "voice_analysis", "face_analysis", "risk_analysis"],
    },
    {
        "key": "brand_content",
        "topic": "Brand storytelling for daily pack",
        "agents": ["content_creator", "marketing_manager", "x_twitter_voice", "social_poster"],
    },
    {
        "key": "intel_brief",
        "topic": "Director intel briefing",
        "agents": ["director_intelligence", "macro_trend", "news_correlation", "portfolio_intelligence"],
    },
    {
        "key": "memory_orchestrate",
        "topic": "Conversation memory + orchestration",
        "agents": ["conversation_memory", "orchestrator", "decision", "ceo"],
    },
]

TARGET_LIVE_THREADS = len(THREAD_BLUEPRINTS)  # 24 rooms
TICK_BATCH = 6  # threads advanced per poll
TICK_INTERVAL_SEC = 1.0

# Role-flavored work lines (no LLM required)
_WORK_LINES: dict[str, list[str]] = {
    "content_creator": [
        "Locked headline B — sharper CTA for the Canva frame.",
        "Swapping logo safe-zone; text won't collide with the mark.",
        "Daily pack copy v3 ready for social_poster handoff.",
        "Need human eyes on logo size before we freeze the template.",
    ],
    "social_poster": [
        "Queueing LinkedIn + Instagram captions for today's pack.",
        "Character counts OK for X; trimming emoji density.",
        "Platform readiness green — waiting on final Canva export.",
        "Scheduling window set for PKT evening peak.",
    ],
    "marketing_manager": [
        "Campaign brief synced — keep channel drafts under the cap.",
        "Priority: daily posts first, influencer hooks second.",
        "Blocking on logo approval before we go wider.",
        "Assigning content_creator → social_poster in this room.",
    ],
    "influencer_relations": [
        "Shortlisted 3 creators in AI-verification niche.",
        "Drafting hook + CTA for creator outreach thread.",
        "Adrian here — need brand voice check on the pitch.",
        "Ready for a personal meeting if Ibrahim wants to pick the creator angle.",
    ],
    "x_twitter_voice": [
        "Variant A is punchier; B is more explanatory.",
        "Reply-engagement draft ready for the launch tweet.",
        "Thread outline: problem → proof → VeriDiQ CTA.",
    ],
    "telegram_community": [
        "Community explainer posted to draft — education-first tone.",
        "Pin candidate: how verification jobs flow end-to-end.",
        "Theo: keeping Meta out; Telegram-only for this pack.",
    ],
    "ai_calling": [
        "Marcus standing by — say who you want to meet and I'll request them.",
        "Can open a LiveKit personal room once the specialist approves.",
        "Logged interact request; waiting on specialist approval.",
    ],
    "ceo": [
        "Keep velocity high — flag blockers in this thread.",
        "Directors: confirm specialist ownership before inviting humans.",
        "Observer mode for Ibrahim until an invite is accepted.",
    ],
    "director_operations": [
        "Ops queue clear — routing next verification batch.",
        "Morgan: specialist assigned; ETA on draft in this room.",
        "Escalating logo decision to personal meeting if needed.",
    ],
    "director_growth": [
        "Growth connectors probed — posting paths look ready.",
        "Selene: prioritize daily pack + influencer room.",
    ],
    "director_intelligence": [
        "Intel desk green — macro + news correlation in sync.",
        "Kai: folding sentiment into the brief.",
    ],
    "default": [
        "Working the assigned specialty — posting status in-thread.",
        "Syncing outputs with peer agents in this room.",
        "Next checkpoint in ~30s; continuing live.",
        "No blockers on my side — waiting on peer handoff.",
    ],
}


def unique_agent_types_in_blueprints() -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for bp in THREAD_BLUEPRINTS:
        for a in bp["agents"]:
            if a not in seen:
                seen.add(a)
                ordered.append(a)
    return ordered


def estimated_agent_presence() -> dict[str, Any]:
    types = unique_agent_types_in_blueprints()
    # Count seats (an agent in 2 rooms counts twice for "busy workforce" feel)
    seats = sum(len(bp["agents"]) for bp in THREAD_BLUEPRINTS)
    return {
        "unique_agents": len(types),
        "thread_seats": seats,
        "live_threads_target": TARGET_LIVE_THREADS,
        "roster_size": len(AGENT_IDENTITIES),
    }


def work_line_for(agent_type: str, topic: str, turn: int) -> str:
    ident = identity_for(agent_type)
    bank = _WORK_LINES.get(agent_type) or _WORK_LINES["default"]
    # Deterministic-ish variety from turn + agent
    seed = int(hashlib.md5(f"{agent_type}:{topic}:{turn}".encode()).hexdigest()[:8], 16)
    line = bank[seed % len(bank)]
    # Occasionally inject topic fragment
    if turn % 5 == 0:
        return f"{ident['name']}: {line} (re: {topic[:48]})"
    return f"{ident['name']}: {line}"


def invite_line(agent_type: str, user_name: str) -> str:
    ident = identity_for(agent_type)
    return (
        f"{ident['name']}: {user_name}, we want you to join and interact with us — "
        f"accept the invite for a personal meeting with {ident['name']} ({ident['role']})."
    )


def opening_line(agent_type: str, topic: str) -> str:
    ident = identity_for(agent_type)
    return f"{ident['name']}: Live on “{topic}” — {ident['role']} taking the next action."


def blueprint_by_key(key: str) -> Optional[dict[str, Any]]:
    for bp in THREAD_BLUEPRINTS:
        if bp["key"] == key:
            return bp
    return None


def pick_tick_indices(n_threads: int, batch: int = TICK_BATCH, *, salt: int = 0) -> list[int]:
    if n_threads <= 0:
        return []
    rng = random.Random((salt // 2) ^ n_threads)
    idxs = list(range(n_threads))
    rng.shuffle(idxs)
    return idxs[: max(1, min(batch, n_threads))]
