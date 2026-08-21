"""Content template library for the VERIDIQ Marketing Agency.

Deterministic, offline, and fully editable — no LLM/network call is required
to produce a day's content pack. `product_brief` (stored per-campaign, see
`veridiq/marketing/campaigns.py`) is prepended/blended into every template so
the user can steer tone/positioning without touching code.
"""

from __future__ import annotations

import hashlib
from datetime import date as _date
from typing import Any, Optional

# Core VeriDiQ platform features — the source of truth for "educate about
# VeriDiQ's core functions" content. Keep in sync with docs/veridiq/01-PRD.md.
CORE_FEATURES: dict[str, dict[str, str]] = {
    "truth_verification": {
        "title": "AI Truth Verification",
        "summary": (
            "VeriDiQ runs statements, transcripts, and media through a multi-agent verification pipeline — "
            "claim extraction, fact-checking against live sources, deception/emotion signal scoring, and a "
            "final truth score with a documented confidence level."
        ),
        "hashtags": "#TruthVerification #FactChecking #AI",
    },
    "workforce_automation": {
        "title": "AI Workforce",
        "summary": (
            "A live roster of specialized AI agents — verification, investigation, research, market intelligence, "
            "and now marketing — each with a name, role, and department, working real jobs you can watch execute "
            "in real time."
        ),
        "hashtags": "#AIWorkforce #Automation #AgenticAI",
    },
    "blockchain_attestation": {
        "title": "Blockchain Attestation",
        "summary": (
            "Every VeriDiQ truth report can be hashed and attested on-chain — a tamper-evident, independently "
            "verifiable record that the finding existed at a point in time, without exposing the underlying data."
        ),
        "hashtags": "#Blockchain #Attestation #Web3",
    },
    "market_intelligence": {
        "title": "Market Intelligence",
        "summary": (
            "Real-time crypto/market snapshots blended with on-chain readiness, sentiment, and macro-trend "
            "agents — probabilistic scenario framing instead of hype, sourced from official market data APIs."
        ),
        "hashtags": "#MarketIntelligence #Crypto #DataDriven",
    },
    "comms_growth_automation": {
        "title": "Comms & Growth Automation",
        "summary": (
            "Draft-first outreach across email, LinkedIn, X, Instagram, Telegram, and WhatsApp — every external "
            "message is prepared by an AI agent and requires a human's explicit approval before it ever sends."
        ),
        "hashtags": "#GrowthAutomation #SafeAI #HumanInTheLoop",
    },
    "evidence_reporting": {
        "title": "Evidence-Backed Reporting",
        "summary": (
            "Structured PDF truth reports with citations, timelines, and risk scoring — built for compliance, "
            "journalism, and due-diligence teams who need a defensible paper trail, not just a verdict."
        ),
        "hashtags": "#EvidenceBased #Compliance #DueDiligence",
    },
}

DEFAULT_PRODUCT_BRIEF = (
    "VeriDiQ is an AI-native truth verification and workforce platform: a live team of specialist AI agents "
    "verifies claims, investigates evidence, tracks markets, and can optionally attest findings on-chain — all "
    "with draft-first, human-approved communication so nothing external ever sends itself."
)


def feature_keys() -> list[str]:
    return list(CORE_FEATURES.keys())


def feature_of_the_day(day: Optional[_date] = None, features: Optional[list[str]] = None) -> str:
    """Deterministically rotate through the feature library by calendar date
    so daily packs cover different core functions over time without state."""
    keys = features or feature_keys()
    if not keys:
        keys = feature_keys()
    day = day or _date.today()
    digest = hashlib.sha256(day.isoformat().encode()).hexdigest()
    idx = int(digest, 16) % len(keys)
    return keys[idx]


def _brief(product_brief: Optional[str]) -> str:
    return (product_brief or DEFAULT_PRODUCT_BRIEF).strip()


def render_telegram_post(feature_key: str, product_brief: Optional[str] = None) -> str:
    feature = CORE_FEATURES.get(feature_key, CORE_FEATURES["truth_verification"])
    brief = _brief(product_brief)
    return (
        f"📌 VeriDiQ Feature Spotlight — {feature['title']}\n\n"
        f"{feature['summary']}\n\n"
        f"Why it matters: {brief}\n\n"
        f"Try it → https://veridiq.ai/dashboard/verify\n"
        f"Questions? Reply in this channel and our team will follow up.\n\n"
        f"{feature['hashtags']}"
    )


def render_tweet_variants(feature_key: str, product_brief: Optional[str] = None, n: int = 3) -> list[str]:
    feature = CORE_FEATURES.get(feature_key, CORE_FEATURES["truth_verification"])
    title = feature["title"]
    summary = feature["summary"]
    tags = feature["hashtags"]
    variants = [
        f"🔎 {title}: {summary[:180].rstrip()}… {tags}",
        f"Most \"truth checks\" are one model guessing. VeriDiQ's {title} is a full agent pipeline with evidence "
        f"and a confidence score you can audit. {tags}",
        f"New to VeriDiQ? Start with {title.lower()} — {summary[:140].rstrip()}… Learn more: veridiq.ai {tags}",
        f"{title} in one line: {summary.split('.')[0]}. {tags}",
    ]
    return [v[:280] for v in variants[: max(1, n)]]


def render_linkedin_post(feature_key: str, product_brief: Optional[str] = None) -> str:
    feature = CORE_FEATURES.get(feature_key, CORE_FEATURES["truth_verification"])
    brief = _brief(product_brief)
    return (
        f"{feature['title']} — how VeriDiQ approaches it\n\n"
        f"{feature['summary']}\n\n"
        f"{brief}\n\n"
        f"We built this because verification and outreach tooling too often either fabricates confidence or "
        f"requires a full engineering team to stand up. VeriDiQ ships both as a working product with an honest "
        f"configuration_required state whenever a live credential is missing — never a fabricated result.\n\n"
        f"{feature['hashtags']} #VeriDiQ"
    )


def render_instagram_caption(feature_key: str, product_brief: Optional[str] = None) -> str:
    feature = CORE_FEATURES.get(feature_key, CORE_FEATURES["truth_verification"])
    return (
        f"{feature['title']} 🚀\n"
        f"{feature['summary'][:180].rstrip()}…\n"
        f"Link in bio → veridiq.ai\n"
        f"{feature['hashtags']} #VeriDiQ"
    )


def render_threads_post(feature_key: str, product_brief: Optional[str] = None) -> str:
    """Threads text post — official API media_type=TEXT, 500-char soft cap."""
    feature = CORE_FEATURES.get(feature_key, CORE_FEATURES["truth_verification"])
    brief = _brief(product_brief)
    text = (
        f"{feature['title']}\n\n"
        f"{feature['summary'][:200].rstrip()}…\n\n"
        f"{brief[:120].rstrip()}\n"
        f"Try it → veridiq.ai\n"
        f"{feature['hashtags']} #VeriDiQ"
    )
    return text[:500]


CHANNEL_RENDERERS: dict[str, Any] = {
    "telegram": render_telegram_post,
    "x_twitter": render_tweet_variants,
    "linkedin": render_linkedin_post,
    "instagram": render_instagram_caption,
    "threads": render_threads_post,
}

DEFAULT_CAMPAIGN_CHANNELS = ["telegram", "x_twitter", "linkedin", "instagram", "threads"]


def render_engagement_comment(channel: str, feature_key: str, product_brief: Optional[str] = None) -> str:
    """Short reply/comment text for engaging on other posts (X replies,
    LinkedIn comments, Instagram comment replies, Telegram group replies) —
    distinct from a full standalone post."""
    feature = CORE_FEATURES.get(feature_key, CORE_FEATURES["truth_verification"])
    base = f"Great point — this is exactly the kind of case {feature['title'].lower()} on VeriDiQ is built for."
    if channel == "x_twitter":
        return base[:280]
    if channel == "linkedin":
        return f"{base} Happy to share how our agent pipeline scores this if useful."
    if channel == "instagram":
        return f"{base} 🙌"
    if channel == "threads":
        return f"{base} Try the free verify flow on VeriDiQ."[:500]
    if channel == "telegram":
        return f"{base} Ask us anything about how it works."
    return base


# --- Influencer voice (Adrian / influencer_relations) -----------------------
# First-person, hook-driven posts for cross-platform influencer-style reach.
# Every item still lands as draft_only — never auto-sent.

_INFLUENCER_SIGNOFF = "— Adrian @ VeriDiQ"


def render_influencer_tweet(feature_key: str, product_brief: Optional[str] = None) -> str:
    feature = CORE_FEATURES.get(feature_key, CORE_FEATURES["truth_verification"])
    hook = (
        f"Hot take: most \"AI truth\" tools guess once and call it a day. "
        f"VeriDiQ's {feature['title']} runs a full agent pipeline with evidence + a score you can audit."
    )
    cta = f"Try it free → veridiq.ai/dashboard/verify {feature['hashtags']} #VeriDiQ"
    text = f"{hook[:200].rstrip()}… {cta}"
    return text[:280]


def render_influencer_tweet_variants(feature_key: str, product_brief: Optional[str] = None, n: int = 2) -> list[str]:
    feature = CORE_FEATURES.get(feature_key, CORE_FEATURES["truth_verification"])
    title = feature["title"]
    tags = feature["hashtags"]
    variants = [
        render_influencer_tweet(feature_key, product_brief),
        (
            f"If you're building with AI, you need {title.lower()} you can defend. "
            f"VeriDiQ = multi-agent verification + human-approved comms. "
            f"Link in bio. {tags} #BuildInPublic"
        )[:280],
        (
            f"POV: your team asks \"is this claim true?\" and you actually have an answer. "
            f"That's {title} on VeriDiQ — not one model, a whole workforce. "
            f"veridiq.ai {tags}"
        )[:280],
    ]
    return variants[: max(1, n)]


def render_influencer_telegram(feature_key: str, product_brief: Optional[str] = None) -> str:
    feature = CORE_FEATURES.get(feature_key, CORE_FEATURES["truth_verification"])
    return (
        f"👋 {_INFLUENCER_SIGNOFF}\n\n"
        f"**{feature['title']}** — why I'm excited about this:\n"
        f"{feature['summary']}\n\n"
        f"🎯 **CTA:** Drop a claim in VeriDiQ and watch the agent team verify it live.\n"
        f"→ https://veridiq.ai/dashboard/verify\n\n"
        f"{feature['hashtags']} #VeriDiQ"
    )


def render_influencer_linkedin(feature_key: str, product_brief: Optional[str] = None) -> str:
    feature = CORE_FEATURES.get(feature_key, CORE_FEATURES["truth_verification"])
    brief = _brief(product_brief)
    return (
        f"Hook: {feature['title']} shouldn't be a black box.\n\n"
        f"I work with the VeriDiQ team on influencer-facing storytelling — here's the honest pitch:\n"
        f"{feature['summary']}\n\n"
        f"{brief}\n\n"
        f"CTA: If you're evaluating AI verification or agentic workflows, start at veridiq.ai — "
        f"every external post (including this one when approved) goes through draft → human approve → real API send.\n\n"
        f"{feature['hashtags']} #VeriDiQ #InfluencerTech"
    )


def render_influencer_instagram(feature_key: str, product_brief: Optional[str] = None) -> str:
    feature = CORE_FEATURES.get(feature_key, CORE_FEATURES["truth_verification"])
    return (
        f"Stop scrolling — {feature['title']} done right ✨\n\n"
        f"{feature['summary'][:160].rstrip()}…\n\n"
        f"Link in bio → veridiq.ai\n"
        f"DM me \"VERIFY\" and I'll share how our agent team works.\n\n"
        f"{feature['hashtags']} #VeriDiQ #AIInfluencer"
    )


def render_influencer_threads(feature_key: str, product_brief: Optional[str] = None) -> str:
    feature = CORE_FEATURES.get(feature_key, CORE_FEATURES["truth_verification"])
    text = (
        f"Hot take: {feature['title']} shouldn't be a black box.\n"
        f"{feature['summary'][:180].rstrip()}…\n"
        f"→ veridiq.ai — {_INFLUENCER_SIGNOFF}\n"
        f"{feature['hashtags']} #VeriDiQ"
    )
    return text[:500]


INFLUENCER_RENDERERS: dict[str, Any] = {
    "telegram": render_influencer_telegram,
    "x_twitter": render_influencer_tweet_variants,
    "linkedin": render_influencer_linkedin,
    "instagram": render_influencer_instagram,
    "threads": render_influencer_threads,
}


def is_influencer_voice(created_by_agent: Optional[str]) -> bool:
    from veridiq.marketing.human_voice import is_influencer_voice as _is_influencer

    return _is_influencer(created_by_agent)
