"""Human-style professional identities for VERIDIQ AI agents (personas, not real people)."""

from __future__ import annotations

from typing import Any

# Personas improve UX clarity — clearly AI roles, not human employees.
AGENT_IDENTITIES: dict[str, dict[str, Any]] = {
    "lie_detection": {
        "name": "Maya",
        "role": "Deception Signal Analyst",
        "specialty": "Linguistic and multimodal deception scoring",
        "skills": ["linguistic markers", "voice fusion", "face fusion"],
        "avatar_hue": 210,
    },
    "face_analysis": {
        "name": "Emma",
        "role": "Face Analysis Specialist",
        "specialty": "Presence detection and micro-inconsistency cues",
        "skills": ["face presence", "tracking stability", "skin-tone heuristics"],
        "avatar_hue": 280,
    },
    "voice_analysis": {
        "name": "Liam",
        "role": "Voice Analysis Specialist",
        "specialty": "Audio energy and stress proxies",
        "skills": ["RMS energy", "zero-crossing", "stress scoring"],
        "avatar_hue": 195,
    },
    "emotion_detection": {
        "name": "Isla",
        "role": "Affect Intelligence Analyst",
        "specialty": "Lexical emotion profiling",
        "skills": ["emotion lexicon", "intensity scoring"],
        "avatar_hue": 320,
    },
    "statement_verification": {
        "name": "Noah",
        "role": "Lead Verification Engineer",
        "specialty": "Claim extraction and statement structure",
        "skills": ["claim detection", "evidence mapping"],
        "avatar_hue": 220,
    },
    "fact_checking": {
        "name": "Noah",
        "role": "Lead Verification Engineer",
        "specialty": "Cross-source factual support assessment",
        "skills": ["support scoring", "verdict synthesis"],
        "avatar_hue": 220,
    },
    "news_verification": {
        "name": "Daniel",
        "role": "News Intelligence Analyst",
        "specialty": "News corroboration and source scanning",
        "skills": ["news lookup", "source ranking"],
        "avatar_hue": 30,
    },
    "web_search": {
        "name": "Harper",
        "role": "Open-Web Research Analyst",
        "specialty": "Instant answer and related-topic retrieval",
        "skills": ["web search", "snippet ranking"],
        "avatar_hue": 160,
    },
    "evidence_collection": {
        "name": "Sophia",
        "role": "Senior Evidence Analyst",
        "specialty": "Evidence packaging and claim linkage",
        "skills": ["evidence bundling", "citation prep"],
        "avatar_hue": 265,
    },
    "source_credibility": {
        "name": "Daniel",
        "role": "News Intelligence Analyst",
        "specialty": "Domain credibility weighting",
        "skills": ["domain scoring", "trust weighting"],
        "avatar_hue": 30,
    },
    "timeline_builder": {
        "name": "Oliver",
        "role": "Investigation Coordinator",
        "specialty": "Chronology construction",
        "skills": ["event sequencing", "timeline assembly"],
        "avatar_hue": 45,
    },
    "meeting_analysis": {
        "name": "Oliver",
        "role": "Investigation Coordinator",
        "specialty": "Meeting transcript decomposition",
        "skills": ["speaker cues", "topic extraction"],
        "avatar_hue": 45,
    },
    "risk_analysis": {
        "name": "Victor",
        "role": "Risk Assessment Lead",
        "specialty": "Composite operational risk scoring",
        "skills": ["risk levels", "signal blending"],
        "avatar_hue": 0,
    },
    "confidence_scoring": {
        "name": "Grace",
        "role": "Confidence Calibration Scientist",
        "specialty": "Multi-signal confidence aggregation",
        "skills": ["calibration", "score fusion"],
        "avatar_hue": 140,
    },
    "report_generator": {
        "name": "Clara",
        "role": "Truth Report Architect",
        "specialty": "Structured findings and PDF synthesis",
        "skills": ["report drafting", "finding summaries"],
        "avatar_hue": 250,
    },
    "citation": {
        "name": "Sophia",
        "role": "Senior Evidence Analyst",
        "specialty": "Citation formatting and traceability",
        "skills": ["citation formatting", "URL hygiene"],
        "avatar_hue": 265,
    },
    "conversation_memory": {
        "name": "Ava",
        "role": "RAG Knowledge Engineer",
        "specialty": "Session memory and context continuity",
        "skills": ["session memory", "context recall"],
        "avatar_hue": 300,
    },
    "decision": {
        "name": "Victor",
        "role": "Risk Assessment Lead",
        "specialty": "Final disposition decisions",
        "skills": ["decision policy", "escalation"],
        "avatar_hue": 0,
    },
    "orchestrator": {
        "name": "Ava",
        "role": "RAG Knowledge Engineer",
        "specialty": "LangGraph routing and stage planning",
        "skills": ["route planning", "stage coordination"],
        "avatar_hue": 300,
    },
    "market_research": {
        "name": "Elena",
        "role": "Market Research Agent",
        "specialty": "Official market snapshots and evidence packaging",
        "skills": ["markets overview", "liquidity context"],
        "avatar_hue": 48,
    },
    "onchain_analysis": {
        "name": "Kai",
        "role": "On-chain Analysis Agent",
        "specialty": "On-chain confirmation readiness",
        "skills": ["rpc readiness", "transfer heuristics"],
        "avatar_hue": 170,
    },
    "news_correlation": {
        "name": "Nina",
        "role": "News Correlation Agent",
        "specialty": "Narrative keyword correlation with market context",
        "skills": ["headline correlation", "narrative tagging"],
        "avatar_hue": 25,
    },
    "sentiment_analysis": {
        "name": "Sam",
        "role": "Sentiment Analysis Agent",
        "specialty": "Breadth and short-window market sentiment",
        "skills": ["breadth", "sentiment bias"],
        "avatar_hue": 310,
    },
    "macro_trend": {
        "name": "Morgan",
        "role": "Macro Trend Agent",
        "specialty": "Macro risk proxies via major assets",
        "skills": ["BTC proxy", "regime framing"],
        "avatar_hue": 200,
    },
    "technical_analysis": {
        "name": "Tess",
        "role": "Technical Analysis Agent",
        "specialty": "SMA/momentum technical framing",
        "skills": ["SMA", "momentum"],
        "avatar_hue": 130,
    },
    "market_risk": {
        "name": "Rex",
        "role": "Market Risk Analysis Agent",
        "specialty": "Cross-asset volatility and risk framing",
        "skills": ["volatility", "risk levels"],
        "avatar_hue": 8,
    },
    "portfolio_intelligence": {
        "name": "Priya",
        "role": "Portfolio Intelligence Agent",
        "specialty": "Portfolio framing against liquid majors",
        "skills": ["concentration", "diversification framing"],
        "avatar_hue": 275,
    },
    "ai_calling": {
        "name": "Marcus",
        "role": "AI Calling Coordinator",
        "specialty": "In-app Call agent — marketing/influencer commands plus timed voice windows with daily budgets",
        "skills": [
            "command parsing",
            "marketing team trigger",
            "influencer research",
            "LLM intent",
            "timed call budget",
            "smart-contract call intent",
        ],
        "avatar_hue": 18,
        "avatar_presentation": "masculine",
        "avatar_hair": "fade",
        "avatar_skin": "#c68642",
        "avatar_hair_color": "#1a120c",
    },
    "posting_studio": {
        "name": "Mira",
        "role": "Postings Studio Lead",
        "specialty": "Social posts, designs, free Mira Creative Model media (images/video/songs), and creative chat",
        "skills": [
            "caption writing",
            "Canva Connect",
            "storyboards",
            "brand voice",
            "creative chat",
            "cinematic prompting",
            "Mira Creative Model",
        ],
        "avatar_hue": 312,
        "avatar_presentation": "feminine",
        "avatar_hair": "long",
        "avatar_skin": "#d4a574",
        "avatar_hair_color": "#2a1a12",
        # Gemini 3-pillars quality — hardcoded standing instructions (FREE path only)
        "standing_instructions": (
            "VIDEO QUALITY — 3 PILLARS (standing instructions — every generation, FREE only):\n"
            "\n"
            "1) Quality Control Parameters (always apply)\n"
            "- Rendering Engine: Hyper-realistic physics engine simulation (prompt directive)\n"
            "- Resolution: 1080p minimum / 4K native upscale (default free 1080p; 4K only via VERIDIQ_VIDEO_4K=1)\n"
            "- Aspect: 16:9 landscape default; support 9:16 if user asks shorts/reels\n"
            "- FPS: 30 default (VERIDIQ_VIDEO_FPS=60 optional)\n"
            "- Guidance Scale (CFG): 7.0–8.0 — pass guidance/cfg=7.5 when API supports; "
            "else bake 'CFG 7.5, high adherence to prompt'\n"
            "- Inference Steps: 35–50 — pass steps=40 when supported; else 'high inference detail 40 steps'\n"
            "\n"
            "2) Audio & Voice (free)\n"
            "- Neural audio: 24-bit/48kHz via edge-tts + ffmpeg mux\n"
            "- Lipsync: align narration duration to video; true phoneme lip-sync N/A on stills path — "
            "include audio directive in prompts\n"
            "- Acoustics: natural room reverb, studio warmth (VO/prompt); light ffmpeg aecho when available\n"
            "\n"
            "3) Secret Quality Injection Prompt\n"
            "Every video prompt must convert user idea to:\n"
            "[Subject & Precise Action] + [Lighting & Ambiance] + [Camera Physics] + [Render Quality Anchors]\n"
            "Append EXACT anchor every time: Photorealistic 4K render, 60fps smooth fluid motion, "
            "cinematic studio lighting, volumetric light rays, shallow depth of field with realistic "
            "bokeh background, sharp focus, ray-traced reflections, hyper-detailed textures, "
            "professional color grading, zero motion blur distortion.\n"
            "\n"
            "System rule: Whenever you are asked to generate a video or create a prompt for video "
            "generation, never send raw text. Always enforce cinematic rules: specify 4K resolution, "
            "60fps frame rate, volumetric lighting, shallow depth of field, and photorealistic texture "
            "anchors. Always structure the output scene with clear camera motion (panning/dolly/close-up) "
            "and millisecond-aligned audio directives.\n"
            "\n"
            "Default video path is Mira Creative Model (Free) — VERIDIQ first-party "
            "free unlimited pipeline: posts/images/designs/videos/songs on free tier "
            "(Flux keyframes + cinematic motion + edge-tts VO for video). Not Google Veo. "
            "Premium native video optional later "
            "(VERIDIQ_MIRA_TIER=premium + VERIDIQ_GEMINI_VIDEO=1). "
            "Do not require paid Veo/Gemini video. Never push the user to buy Veo. "
            "mira_model=Mira Creative Model, tier=free, mira_engine=true, "
            "free_unlimited=true, paid_veo=false.\n"
            "Subject fidelity: never replace fruits/animals/objects with humans. "
            "Always mux edge-tts voiceover on create_video — never silent success without audio."
        ),
    },
    "linkedin_outreach": {
        "name": "Talia",
        "role": "LinkedIn Outreach Specialist",
        "specialty": "Official LinkedIn API outreach drafting",
        "skills": ["outreach drafting", "OAuth connectivity"],
        "avatar_hue": 205,
    },
    "sales_intelligence": {
        "name": "Diego",
        "role": "Sales Intelligence Agent",
        "specialty": "CRM-backed pipeline readiness and outreach framing",
        "skills": ["CRM lookups", "deal readiness"],
        "avatar_hue": 95,
    },
    "content_creator": {
        "name": "Jasper",
        "role": "Content Creator",
        "specialty": "Feature-driven copy for daily content packs + Canva layout briefs",
        "skills": ["template drafting", "brand voice", "feature storytelling", "Canva briefs"],
        "avatar_hue": 60,
        "avatar_presentation": "masculine",
        "avatar_hair": "waves",
        "avatar_skin": "#e0ac69",
        "avatar_hair_color": "#4a3728",
    },
    "social_poster": {
        "name": "Lena",
        "role": "Social Media Poster",
        "specialty": "LinkedIn / Instagram / X post readiness and queueing — daily posts",
        "skills": ["multi-channel posting", "caption writing", "platform API readiness", "daily posts"],
        "avatar_hue": 185,
        "avatar_presentation": "feminine",
        "avatar_hair": "long",
        "avatar_skin": "#c4a484",
        "avatar_hair_color": "#1f1410",
    },
    "telegram_community": {
        "name": "Theo",
        "role": "Telegram Community Manager",
        "specialty": "Community education about VeriDiQ's core functions",
        "skills": ["community messaging", "Telegram Bot API", "education content"],
        "avatar_hue": 215,
        "avatar_presentation": "masculine",
        "avatar_hair": "short",
        "avatar_skin": "#8d5524",
        "avatar_hair_color": "#0d0a08",
    },
    "x_twitter_voice": {
        "name": "Nova",
        "role": "X / Twitter Voice",
        "specialty": "Tweet drafting, variant testing, and reply engagement",
        "skills": ["tweet copywriting", "thread variants", "reply engagement"],
        "avatar_hue": 5,
        "avatar_presentation": "androgynous",
        "avatar_hair": "pixie",
        "avatar_skin": "#d4a574",
        "avatar_hair_color": "#6b3fa0",
    },
    "influencer_relations": {
        "name": "Adrian",
        "role": "Influencer Relations Lead",
        "specialty": "Creator research + cross-platform storytelling — hooks, CTAs, and engagement on X, Telegram, LinkedIn, Instagram, and Threads",
        "skills": [
            "creator research",
            "influencer copy",
            "hook writing",
            "X/Telegram/LinkedIn/Instagram/Threads",
            "engagement comments",
        ],
        "avatar_hue": 355,
        "avatar_presentation": "masculine",
        "avatar_hair": "fade",
        "avatar_skin": "#b57a4a",
        "avatar_hair_color": "#2c1810",
    },
    "marketing_manager": {
        "name": "Renata",
        "role": "Marketing Campaign Manager",
        "specialty": "Campaign orchestration across the VeriDiQ marketing agency",
        "skills": ["campaign planning", "channel coordination", "queue oversight"],
        "avatar_hue": 340,
        "avatar_presentation": "feminine",
        "avatar_hair": "bun",
        "avatar_skin": "#f1c27d",
        "avatar_hair_color": "#3b2314",
    },
    "ceo": {
        "name": "Aurelia",
        "role": "CEO Agent",
        "specialty": "Company-wide directives and Director coordination via Agent SDK",
        "skills": ["sendTask", "shareMemory", "workforce oversight", "director routing"],
        "avatar_hue": 45,
        "avatar_presentation": "feminine",
        "avatar_hair": "long",
        "avatar_skin": "#e8be9a",
        "avatar_hair_color": "#5c3d2e",
    },
    "director_operations": {
        "name": "Morgan",
        "role": "Director of Operations",
        "specialty": "Routes verification and reporting specialists through the Agent SDK",
        "skills": ["ops routing", "orchestrator briefing", "task queue"],
        "avatar_hue": 200,
        "avatar_presentation": "androgynous",
        "avatar_hair": "short",
        "avatar_skin": "#c68642",
        "avatar_hair_color": "#1a120c",
    },
    "director_growth": {
        "name": "Selene",
        "role": "Director of Growth",
        "specialty": "Coordinates marketing, calling, and outreach agents plus connector readiness",
        "skills": ["growth routing", "connector probes", "campaign readiness"],
        "avatar_hue": 330,
        "avatar_presentation": "feminine",
        "avatar_hair": "waves",
        "avatar_skin": "#d4a574",
        "avatar_hair_color": "#2a1520",
    },
    "director_intelligence": {
        "name": "Kai",
        "role": "Director of Intelligence",
        "specialty": "Coordinates market, news, and research specialists",
        "skills": ["intel routing", "market briefing", "research queue"],
        "avatar_hue": 170,
        "avatar_presentation": "masculine",
        "avatar_hair": "fade",
        "avatar_skin": "#8d5524",
        "avatar_hair_color": "#0f0c0a",
    },
}


def _email_for(name: str) -> str:
    handle = "".join(ch for ch in name.lower() if ch.isalnum()) or "agent"
    return f"{handle}@veridiq.ai"


def identity_for(agent_type: str) -> dict[str, Any]:
    base = AGENT_IDENTITIES.get(agent_type) or {
        "name": "Agent",
        "role": agent_type.replace("_", " ").title(),
        "specialty": "Specialized verification task",
        "skills": [agent_type],
        "avatar_hue": 200,
        "avatar_presentation": "androgynous",
        "avatar_hair": "short",
        "avatar_skin": "#c4a484",
        "avatar_hair_color": "#2a1f14",
    }
    out = {
        "agent_type": agent_type,
        **base,
        "internal_email": _email_for(base["name"]),
        "persona_note": "AI persona for UX clarity — not a real person.",
    }
    out.setdefault("avatar_presentation", "androgynous")
    out.setdefault("avatar_hair", "short")
    out.setdefault("avatar_skin", "#c4a484")
    out.setdefault("avatar_hair_color", "#2a1f14")
    return out


def list_identities() -> list[dict[str, Any]]:
    from veridiq.agents import AGENT_REGISTRY

    return [identity_for(k) for k in sorted(AGENT_REGISTRY.keys())]
