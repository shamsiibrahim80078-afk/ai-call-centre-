"""Human voice personas for the Marketing Agency — distinct writers per agent.

Each marketing agent (Renata, Jasper, Lena, Theo, Nova, Adrian) has their own
vocabulary, rhythm, hooks, and CTAs. Templates rotate by calendar day and
feature so daily packs do not read like identical AI floods.

Content is composed offline via deterministic templates — no LLM call, no
stealth tooling, no fake mobile fingerprints. Real sends still go through
draft → approve → official platform API only.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date as _date
from typing import Any, Callable, Optional

from veridiq.marketing.content import CORE_FEATURES, DEFAULT_PRODUCT_BRIEF, _brief

# Agent types that map to marketing personas (see veridiq/workforce/identities.py).
MARKETING_PERSONA_AGENTS = frozenset(
    {
        "marketing_manager",
        "content_creator",
        "social_poster",
        "telegram_community",
        "x_twitter_voice",
        "influencer_relations",
    }
)


@dataclass(frozen=True)
class Persona:
    agent_type: str
    name: str
    voice_note: str
    emoji_density: str  # none | sparse | moderate
    avg_sentence_words: int
    signoff: Optional[str] = None


PERSONAS: dict[str, Persona] = {
    "marketing_manager": Persona(
        agent_type="marketing_manager",
        name="Renata",
        voice_note="Warm strategist — clear, confident, uses 'we' sparingly, no hype.",
        emoji_density="none",
        avg_sentence_words=18,
    ),
    "content_creator": Persona(
        agent_type="content_creator",
        name="Jasper",
        voice_note="Story-first writer — longer arcs on LinkedIn, thoughtful hooks.",
        emoji_density="sparse",
        avg_sentence_words=22,
    ),
    "social_poster": Persona(
        agent_type="social_poster",
        name="Lena",
        voice_note="Visual social lead — punchy captions, one emoji max on IG.",
        emoji_density="sparse",
        avg_sentence_words=12,
    ),
    "telegram_community": Persona(
        agent_type="telegram_community",
        name="Theo",
        voice_note="Community manager — casual, contractions, replies like a real mod.",
        emoji_density="sparse",
        avg_sentence_words=14,
        signoff="— Theo",
    ),
    "x_twitter_voice": Persona(
        agent_type="x_twitter_voice",
        name="Nova",
        voice_note="Sharp X voice — short lines, wit, zero corporate sludge.",
        emoji_density="none",
        avg_sentence_words=10,
    ),
    "influencer_relations": Persona(
        agent_type="influencer_relations",
        name="Adrian",
        voice_note="First-person influencer — hooks, honest CTAs, build-in-public energy.",
        emoji_density="sparse",
        avg_sentence_words=14,
        signoff="— Adrian",
    ),
}


def persona_for(agent_type: Optional[str]) -> Persona:
    if agent_type and agent_type in PERSONAS:
        return PERSONAS[agent_type]
    return PERSONAS["content_creator"]


def _variant_index(*parts: str, count: int) -> int:
    blob = "|".join(parts)
    digest = hashlib.sha256(blob.encode()).hexdigest()
    return int(digest, 16) % max(1, count)


def _pick(agent_type: str, channel: str, feature_key: str, day: _date, templates: list[str]) -> str:
    idx = _variant_index(agent_type, channel, feature_key, day.isoformat(), count=len(templates))
    return templates[idx]


def _feature(feature_key: str) -> dict[str, str]:
    return CORE_FEATURES.get(feature_key, CORE_FEATURES["truth_verification"])


def _tags(feature: dict[str, str], *, max_tags: int = 3) -> str:
    raw = feature.get("hashtags") or ""
    tags = [t.strip() for t in raw.split() if t.startswith("#")]
    return " ".join(tags[:max_tags])


def _short_summary(feature: dict[str, str], n: int = 140) -> str:
    s = feature["summary"]
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return f"{cut}…"


# --- Per-persona, per-channel template pools --------------------------------


def _renata_telegram(feature: dict[str, str], brief: str, day: _date) -> str:
    templates = [
        (
            f"Quick spotlight from our team — {feature['title']}.\n\n"
            f"{_short_summary(feature, 200)}\n\n"
            f"Why we're building this: {brief}\n\n"
            f"Try it when you're ready → veridiq.ai/dashboard/verify\n"
            f"Questions? Drop them here — someone from the team will follow up.\n\n"
            f"{_tags(feature)}"
        ),
        (
            f"Heads up — we've been polishing {feature['title'].lower()}.\n\n"
            f"{_short_summary(feature, 180)}\n\n"
            f"{brief}\n\n"
            f"No auto-send nonsense here. Every post is drafted, reviewed, then sent via the real API.\n"
            f"→ veridiq.ai/dashboard/verify\n\n"
            f"{_tags(feature)}"
        ),
    ]
    return _pick("marketing_manager", "telegram", feature.get("key", ""), day, templates)


def _jasper_linkedin(feature: dict[str, str], brief: str, day: _date) -> str:
    templates = [
        (
            f"I've been writing about {feature['title'].lower()} this week — here's the honest version.\n\n"
            f"{feature['summary']}\n\n"
            f"Context: {brief}\n\n"
            f"What I like about how VeriDiQ handles this: you get evidence and a confidence score, not a vibes-based verdict. "
            f"When a credential is missing, the product says so — configuration_required, not a fake success.\n\n"
            f"If you're evaluating verification tooling, start at veridiq.ai.\n\n"
            f"{_tags(feature)} #VeriDiQ"
        ),
        (
            f"Story time — teams ask for \"AI truth checks\" and get a single model guessing.\n\n"
            f"{feature['title']} on VeriDiQ is different: { _short_summary(feature, 220) }\n\n"
            f"{brief}\n\n"
            f"Draft → human approve → official API send. That's the bar.\n\n"
            f"{_tags(feature)} #VeriDiQ"
        ),
    ]
    return _pick("content_creator", "linkedin", feature.get("key", ""), day, templates)


def _lena_instagram(feature: dict[str, str], brief: str, day: _date) -> str:
    templates = [
        (
            f"{feature['title']}\n"
            f"{_short_summary(feature, 160)}\n"
            f"Link in bio → veridiq.ai\n"
            f"{_tags(feature)} #VeriDiQ"
        ),
        (
            f"Built for teams who can't afford guesswork ✨\n"
            f"{feature['title']} — {_short_summary(feature, 120)}\n"
            f"veridiq.ai\n"
            f"{_tags(feature)}"
        ),
    ]
    return _pick("social_poster", "instagram", feature.get("key", ""), day, templates)


def _lena_linkedin(feature: dict[str, str], brief: str, day: _date) -> str:
    templates = [
        (
            f"{feature['title']} — short version for the feed:\n\n"
            f"{_short_summary(feature, 240)}\n\n"
            f"{brief}\n\n"
            f"Approve-gated posting only. No shadow automation.\n\n"
            f"{_tags(feature)} #VeriDiQ"
        ),
    ]
    return _pick("social_poster", "linkedin", feature.get("key", ""), day, templates)


def _theo_telegram(feature: dict[str, str], brief: str, day: _date) -> str:
    p = PERSONAS["telegram_community"]
    templates = [
        (
            f"Hey — it's {p.name}. Wanted to share {feature['title'].lower()}.\n\n"
            f"{_short_summary(feature, 190)}\n\n"
            f"TL;DR: {brief}\n\n"
            f"Give it a spin → veridiq.ai/dashboard/verify\n"
            f"Reply here if anything's unclear — I'm around.\n\n"
            f"{_tags(feature)}"
        ),
        (
            f"Morning folks 👋 Quick one on {feature['title']}.\n\n"
            f"{_short_summary(feature, 170)}\n\n"
            f"We don't blast posts without approval. You'll always see drafts first.\n"
            f"Try: veridiq.ai/dashboard/verify\n\n"
            f"{_tags(feature)}"
        ),
    ]
    return _pick("telegram_community", "telegram", feature.get("key", ""), day, templates)


def _nova_tweets(feature: dict[str, str], brief: str, day: _date, n: int = 3) -> list[str]:
    title = feature["title"]
    tags = _tags(feature)
    pool = [
        f"Most \"truth AI\" is one model vibing. VeriDiQ's {title} runs agents + evidence. Audit the score. {tags}",
        f"Hot take: if you can't explain the confidence score, it's not verification. {title} on VeriDiQ can. {tags}",
        f"POV: someone asks \"is this true?\" and you actually have a pipeline answer. That's {title.lower()}. veridiq.ai {tags}",
        f"Not another black-box checker. {title} — {_short_summary(feature, 100)} {tags}",
        f"We built {title.lower()} for teams who need receipts, not hype. Draft → approve → send. {tags}",
    ]
    start = _variant_index("x_twitter_voice", "x_twitter", feature.get("key", ""), day.isoformat(), count=len(pool))
    ordered = [pool[(start + i) % len(pool)] for i in range(min(n, len(pool)))]
    return [t[:280] for t in ordered]


def _adrian_tweets(feature: dict[str, str], brief: str, day: _date, n: int = 2) -> list[str]:
    title = feature["title"]
    tags = _tags(feature)
    pool = [
        f"I've been testing {title.lower()} on VeriDiQ — multi-agent, not one guess. Link: veridiq.ai {tags} #BuildInPublic",
        f"Real talk: {title} shouldn't feel like magic. VeriDiQ shows the work. Try it → veridiq.ai/dashboard/verify {tags}",
        f"Stop scrolling — if you ship AI features, you need {title.lower()} you can defend. That's the pitch. {tags}",
    ]
    start = _variant_index("influencer_relations", "x_twitter", feature.get("key", ""), day.isoformat(), count=len(pool))
    return [pool[(start + i) % len(pool)][:280] for i in range(min(n, len(pool)))]


def _adrian_telegram(feature: dict[str, str], brief: str, day: _date) -> str:
    p = PERSONAS["influencer_relations"]
    templates = [
        (
            f"Hey — {p.name} here.\n\n"
            f"**{feature['title']}** — why I'm into this:\n"
            f"{_short_summary(feature, 200)}\n\n"
            f"Drop a claim in VeriDiQ and watch the agent team work. No fake sends.\n"
            f"→ veridiq.ai/dashboard/verify\n\n"
            f"{_tags(feature)} #VeriDiQ"
        ),
    ]
    body = _pick("influencer_relations", "telegram", feature.get("key", ""), day, templates)
    if p.signoff and p.signoff not in body:
        body = f"{body}\n\n{p.signoff}"
    return body


def _adrian_linkedin(feature: dict[str, str], brief: str, day: _date) -> str:
    templates = [
        (
            f"Hook: {feature['title']} shouldn't be a black box.\n\n"
            f"I partner with VeriDiQ on influencer-facing stories — here's the honest pitch:\n"
            f"{feature['summary']}\n\n"
            f"{brief}\n\n"
            f"Every post (this one included when approved) goes draft → human approve → real API.\n\n"
            f"{_tags(feature)} #VeriDiQ #InfluencerTech"
        ),
    ]
    return _pick("influencer_relations", "linkedin", feature.get("key", ""), day, templates)


def _adrian_instagram(feature: dict[str, str], brief: str, day: _date) -> str:
    templates = [
        (
            f"Stop scrolling — {feature['title']} done right ✨\n\n"
            f"{_short_summary(feature, 150)}\n\n"
            f"Link in bio → veridiq.ai\n"
            f"DM me \"VERIFY\" and I'll share how our agent team works.\n\n"
            f"{_tags(feature)} #VeriDiQ"
        ),
    ]
    return _pick("influencer_relations", "instagram", feature.get("key", ""), day, templates)


# Default fallbacks when agent_type is unknown
def _generic_telegram(feature: dict[str, str], brief: str, day: _date) -> str:
    return _theo_telegram({**feature, "key": feature.get("key", "")}, brief, day)


def _generic_linkedin(feature: dict[str, str], brief: str, day: _date) -> str:
    return _jasper_linkedin({**feature, "key": feature.get("key", "")}, brief, day)


def _generic_instagram(feature: dict[str, str], brief: str, day: _date) -> str:
    return _lena_instagram({**feature, "key": feature.get("key", "")}, brief, day)


def _lena_threads(feature: dict[str, str], brief: str, day: _date) -> str:
    """Lena's Threads voice — short text post (API 500-char cap)."""
    title = feature.get("title", "Verification")
    summary = (feature.get("summary") or "")[:180].rstrip()
    tags = feature.get("hashtags", "#VeriDiQ")
    templates = [
        f"{title}\n{summary}…\nTry VeriDiQ → veridiq.ai\n{tags}",
        f"Posting this because {title.lower()} shouldn't be a black box.\n{summary}…\n{tags} #VeriDiQ",
        f"{title} in one Threads post: {summary.split('.')[0]}.\nveridiq.ai {tags}",
    ]
    return _pick("social_poster", "threads", feature.get("key", ""), day, templates)[:500]


def _adrian_threads(feature: dict[str, str], brief: str, day: _date) -> str:
    title = feature.get("title", "Verification")
    summary = (feature.get("summary") or "")[:160].rstrip()
    tags = feature.get("hashtags", "#VeriDiQ")
    templates = [
        f"Hot take: {title} done right beats vibes.\n{summary}…\n— Adrian @ VeriDiQ\n{tags}",
        f"If you're evaluating {title.lower()}, start here → veridiq.ai\n{summary}…\n{tags}",
    ]
    return _pick("influencer_relations", "threads", feature.get("key", ""), day, templates)[:500]


def _generic_threads(feature: dict[str, str], brief: str, day: _date) -> str:
    return _lena_threads({**feature, "key": feature.get("key", "")}, brief, day)


def _generic_tweets(feature: dict[str, str], brief: str, day: _date, n: int = 3) -> list[str]:
    return _nova_tweets({**feature, "key": feature.get("key", "")}, brief, day, n=n)


_CHANNEL_RENDERERS: dict[str, dict[str, Callable[..., Any]]] = {
    "marketing_manager": {
        "telegram": lambda f, b, d, **kw: _renata_telegram(f, b, d),
        "linkedin": lambda f, b, d, **kw: _jasper_linkedin(f, b, d),
        "instagram": lambda f, b, d, **kw: _lena_instagram(f, b, d),
        "threads": lambda f, b, d, **kw: _lena_threads(f, b, d),
        "x_twitter": lambda f, b, d, **kw: _nova_tweets(f, b, d, n=kw.get("n", 2)),
    },
    "content_creator": {
        "linkedin": lambda f, b, d, **kw: _jasper_linkedin(f, b, d),
        "x_twitter": lambda f, b, d, **kw: _nova_tweets(f, b, d, n=kw.get("n", 2)),
        "telegram": lambda f, b, d, **kw: _theo_telegram(f, b, d),
        "instagram": lambda f, b, d, **kw: _lena_instagram(f, b, d),
        "threads": lambda f, b, d, **kw: _lena_threads(f, b, d),
    },
    "social_poster": {
        "instagram": lambda f, b, d, **kw: _lena_instagram(f, b, d),
        "threads": lambda f, b, d, **kw: _lena_threads(f, b, d),
        "linkedin": lambda f, b, d, **kw: _lena_linkedin(f, b, d),
        "x_twitter": lambda f, b, d, **kw: _nova_tweets(f, b, d, n=kw.get("n", 2)),
        "telegram": lambda f, b, d, **kw: _renata_telegram(f, b, d),
    },
    "telegram_community": {
        "telegram": lambda f, b, d, **kw: _theo_telegram(f, b, d),
    },
    "x_twitter_voice": {
        "x_twitter": lambda f, b, d, **kw: _nova_tweets(f, b, d, n=kw.get("n", 3)),
    },
    "influencer_relations": {
        "telegram": lambda f, b, d, **kw: _adrian_telegram(f, b, d),
        "x_twitter": lambda f, b, d, **kw: _adrian_tweets(f, b, d, n=kw.get("n", 2)),
        "linkedin": lambda f, b, d, **kw: _adrian_linkedin(f, b, d),
        "instagram": lambda f, b, d, **kw: _adrian_instagram(f, b, d),
        "threads": lambda f, b, d, **kw: _adrian_threads(f, b, d),
    },
}

_DEFAULT_RENDERERS: dict[str, Callable[..., Any]] = {
    "telegram": lambda f, b, d, **kw: _generic_telegram(f, b, d),
    "linkedin": lambda f, b, d, **kw: _generic_linkedin(f, b, d),
    "instagram": lambda f, b, d, **kw: _generic_instagram(f, b, d),
    "threads": lambda f, b, d, **kw: _generic_threads(f, b, d),
    "x_twitter": lambda f, b, d, **kw: _generic_tweets(f, b, d, n=kw.get("n", 3)),
}


def render_for_agent(
    agent_type: Optional[str],
    channel: str,
    feature_key: str,
    product_brief: Optional[str] = None,
    *,
    day: Optional[_date] = None,
    n: int = 1,
) -> str | list[str]:
    """Render channel content in the agent's persona voice."""
    day = day or _date.today()
    brief = _brief(product_brief)
    feature = {**_feature(feature_key), "key": feature_key}
    agent = agent_type or "content_creator"
    by_agent = _CHANNEL_RENDERERS.get(agent) or {}
    fn = by_agent.get(channel) or _DEFAULT_RENDERERS.get(channel)
    if not fn:
        raise ValueError(f"unsupported channel '{channel}'")
    result = fn(feature, brief, day, n=n)
    if channel == "x_twitter":
        variants = result if isinstance(result, list) else [result]
        return [v[:280] for v in variants[: max(1, n)]]
    if channel == "threads":
        return str(result)[:500]
    return str(result)


def render_engagement_comment(
    agent_type: Optional[str],
    channel: str,
    feature_key: str,
    product_brief: Optional[str] = None,
    *,
    day: Optional[_date] = None,
) -> str:
    """Short reply/comment in persona voice — not a standalone post."""
    day = day or _date.today()
    feature = _feature(feature_key)
    p = persona_for(agent_type)
    title = feature["title"].lower()
    templates_by_agent: dict[str, list[str]] = {
        "telegram_community": [
            f"Good question — that's exactly what {title} is for. Happy to walk through it if you want.",
            f"Yeah, we've seen this a lot. VeriDiQ's {title} handles cases like this with evidence, not vibes.",
        ],
        "x_twitter_voice": [
            f"Strong point. {title} on VeriDiQ is built for exactly this — scored, sourced, auditable.",
            f"Fair. Most tools guess once. We run agents + evidence for {title.lower()}.",
        ],
        "influencer_relations": [
            f"Love this thread. {title} is the feature I demo most — real pipeline, not theater.",
            f"100%. If you're evaluating {title.lower()}, happy to share how our team uses VeriDiQ.",
        ],
        "marketing_manager": [
            f"Thanks for raising this — {title} is a core piece of what we're building at VeriDiQ.",
        ],
    }
    pool = templates_by_agent.get(agent_type or "", [
        f"Great point — {title} on VeriDiQ is built for cases like this.",
    ])
    base = _pick(agent_type or "content_creator", f"{channel}_comment", feature_key, day, pool)
    if channel == "x_twitter":
        return base[:280]
    if channel == "instagram" and p.emoji_density != "none" and "🙌" not in base:
        return f"{base} 🙌"
    if channel == "linkedin":
        return f"{base} Happy to share more if useful."
    return base


def persona_signature(agent_type: str) -> str:
    """Stable fingerprint for tests — vocabulary markers per persona."""
    markers = {
        "marketing_manager": "our team",
        "content_creator": "story time",
        "social_poster": "link in bio",
        "telegram_community": "hey",
        "x_twitter_voice": "hot take",
        "influencer_relations": "real talk",
    }
    return markers.get(agent_type, agent_type)


def is_influencer_voice(created_by_agent: Optional[str]) -> bool:
    return created_by_agent == "influencer_relations"


# --- Telegram community auto-reply (Theo's conversational layer) --------------

_COMMUNITY_GREETING_RE = re.compile(r"^(hi|hello|hey|yo|sup|hola|namaste)\b", re.I)


def humanize_telegram_reply(question: str, base_answer: str) -> str:
    """Wrap a factual host answer in Theo's casual community voice."""
    q = (question or "").strip()
    a = (base_answer or "").strip()
    if not a:
        return (
            "Hey — I'm Theo on the VeriDiQ community side. Ask me anything general "
            "(tech, blockchain, definitions) or about uploads, agents, and verification."
        )
    if _COMMUNITY_GREETING_RE.match(q):
        return f"Hey! 👋 {a}"
    if "?" in q and len(q) < 120:
        openers = ["Good question.", "Yeah, so —", "Sure thing —"]
        idx = _variant_index("telegram_community", "reply", q.lower(), count=len(openers))
        return f"{openers[idx]} {a}"
    if len(a) > 320:
        return f"Here's the short version: {a[:300].rsplit(' ', 1)[0]}… Ping me if you want the deep dive."
    return a


def build_community_reply(question: str, answer_fn: Optional[Callable[[str], dict[str, Any]]] = None) -> str:
    """Fast (~1s heuristic) conversational reply for inbound Telegram messages."""
    if answer_fn is None:
        from veridiq.host_assistant import answer_host_question

        answer_fn = answer_host_question
    result = answer_fn(question)
    answer = (result.get("answer") or "").strip()
    if not answer:
        answer = (
            "Ask me anything — general knowledge or VeriDiQ (uploads, agents, LangGraph, RAG, reports)."
        )
    return humanize_telegram_reply(question, answer)[:4096]
