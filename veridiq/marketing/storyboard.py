"""Marketing video storyboard/script/shot-list generator.

Always produces a real, immediately usable creative artifact (storyboard +
voiceover script + shot list), written to `marketing_out/storyboards/`.
Turning that into an actual rendered MP4 is optional and honestly gated on a
configured render provider (`veridiq.integrations.video_render`) — this
module never claims a video file exists when it doesn't.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from veridiq.marketing.content import CORE_FEATURES, DEFAULT_PRODUCT_BRIEF  # noqa: E402

MARKETING_OUT_DIR = _ROOT / "marketing_out" / "storyboards"
MARKETING_OUT_DIR.mkdir(parents=True, exist_ok=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _shot_list(feature_key: str, duration_sec: int) -> list[dict[str, Any]]:
    feature = CORE_FEATURES.get(feature_key, CORE_FEATURES["truth_verification"])
    title = feature["title"]
    per_shot = max(3, duration_sec // 6)
    return [
        {
            "scene": 1,
            "duration_sec": per_shot,
            "shot": "Cold open — VeriDiQ wordmark animates in over a dark dashboard background.",
            "on_screen_text": "VeriDiQ",
            "voiceover": "In a world of unverified claims,",
        },
        {
            "scene": 2,
            "duration_sec": per_shot,
            "shot": f"Screen capture of the {title} view in the VeriDiQ dashboard, cursor highlighting the key result.",
            "on_screen_text": title,
            "voiceover": f"VeriDiQ's {title.lower()} gives you an answer you can actually check.",
        },
        {
            "scene": 3,
            "duration_sec": per_shot,
            "shot": "Split screen: AI agent avatar cards animate from idle to 'working' as a job runs live.",
            "on_screen_text": "Live AI Workforce",
            "voiceover": "A live team of specialist agents does the work — transparently, in real time.",
        },
        {
            "scene": 4,
            "duration_sec": per_shot,
            "shot": f"{feature['summary'][:90]}... rendered as on-screen bullet callouts over a sharp clear UI backdrop.",
            "on_screen_text": feature["title"],
            "voiceover": feature["summary"].split(".")[0] + ".",
        },
        {
            "scene": 5,
            "duration_sec": max(3, duration_sec - per_shot * 4),
            "shot": "Logo lockup with call-to-action button overlay.",
            "on_screen_text": "Try VeriDiQ free — veridiq.ai",
            "voiceover": "Start verifying, for free, at veridiq.ai.",
        },
    ]


def generate_product_tour_storyboard(
    *,
    campaign_id: Optional[str] = None,
    duration_sec: int = 75,
    product_brief: Optional[str] = None,
) -> dict[str, Any]:
    """Full-platform demo reel covering landing → core product surfaces."""
    brief = (product_brief or DEFAULT_PRODUCT_BRIEF).strip()
    duration_sec = max(45, min(180, int(duration_sec or 75)))
    scenes = [
        {
            "scene": 1,
            "duration_sec": 8,
            "shot": "Full-bleed landing hero — VERIDIQ wordmark, midnight gradient, electric blue CTA.",
            "on_screen_text": "VERIDIQ",
            "voiceover": "This is VERIDIQ — AI truth verification and a live AI workforce in one platform.",
        },
        {
            "scene": 2,
            "duration_sec": 8,
            "shot": "Dashboard overview with agent roster cards switching from idle to working.",
            "on_screen_text": "Live AI Workforce",
            "voiceover": "Specialist agents run real jobs you can watch execute — verification, research, market, and more.",
        },
        {
            "scene": 3,
            "duration_sec": 8,
            "shot": "Verification Center — claim input, truth score, evidence citations panel.",
            "on_screen_text": "Truth Verification",
            "voiceover": "Statements and media go through a multi-agent pipeline to a documented truth score.",
        },
        {
            "scene": 4,
            "duration_sec": 8,
            "shot": "Collaboration Hub — observer feed of live agent threads, invite toast appears.",
            "on_screen_text": "Collaboration Hub",
            "voiceover": "Watch agents collaborate live. Accept an invite when they call you into a meeting.",
        },
        {
            "scene": 5,
            "duration_sec": 8,
            "shot": "AI Calling / LiveKit room — video tiles, join controls, Marcus arranging a meeting.",
            "on_screen_text": "LiveKit Meetings",
            "voiceover": "Personal meetings join real LiveKit video — not a fake chat-only call.",
        },
        {
            "scene": 6,
            "duration_sec": 8,
            "shot": "Postings Studio — Mira chat drafting a VERIDIQ social post with artifact panel.",
            "on_screen_text": "Postings Studio",
            "voiceover": "Mira drafts Gemini-style posts and video storyboards — publish only after you approve.",
        },
        {
            "scene": 7,
            "duration_sec": 8,
            "shot": "Marketing Agency queue + Workforce page + Blockchain attestation badge.",
            "on_screen_text": "Growth · Ops · Chain",
            "voiceover": "Marketing drafts, ops, and optional on-chain attestation — draft-first, human in the loop.",
        },
        {
            "scene": 8,
            "duration_sec": max(5, duration_sec - 56),
            "shot": "Logo lockup with CTA over dark UI montage.",
            "on_screen_text": "Try VERIDIQ",
            "voiceover": "One platform. Live agents. Verified truth. Start at your VERIDIQ dashboard.",
        },
    ]
    # Normalize durations to sum ≈ duration_sec
    total = sum(int(s["duration_sec"]) for s in scenes)
    if total != duration_sec and total > 0:
        scale = duration_sec / total
        for s in scenes[:-1]:
            s["duration_sec"] = max(4, int(round(s["duration_sec"] * scale)))
        scenes[-1]["duration_sec"] = max(4, duration_sec - sum(s["duration_sec"] for s in scenes[:-1]))

    storyboard_id = str(uuid.uuid4())
    storyboard = {
        "storyboard_id": storyboard_id,
        "campaign_id": campaign_id,
        "feature": "full_product_tour",
        "feature_title": "Full VERIDIQ Platform Tour",
        "style": "product_demo",
        "duration_sec": duration_sec,
        "title": f"VERIDIQ — Full App Demo ({duration_sec}s)",
        "logline": (
            f"A {duration_sec}-second product demo reel covering landing, dashboard, verification, "
            "collaboration hub, LiveKit calling, postings, marketing, and attestation."
        ),
        "product_brief": brief,
        "script": "\n".join(f"[Scene {s['scene']}] {s['voiceover']}" for s in scenes),
        "shot_list": scenes,
        "call_to_action": "Open VERIDIQ — /dashboard",
        "created_at": _utc_now(),
    }

    from veridiq.integrations import video_render

    render_status = video_render.status()
    storyboard["render"] = {
        "status": render_status["status"],
        "message": render_status["message"],
        "note": (
            "This is a complete shot list + VO script for the whole app. "
            "MP4 render needs VERIDIQ_VIDEO_RENDER_API_KEY + VERIDIQ_VIDEO_RENDER_WEBHOOK_URL "
            "(Shotstack/Creatomate/etc). Until then the storyboard is the deliverable."
        ),
    }

    out_path = MARKETING_OUT_DIR / f"{storyboard_id}.json"
    out_path.write_text(json.dumps(storyboard, indent=2), encoding="utf-8")
    storyboard["artifact_path"] = str(out_path.relative_to(_ROOT))
    return storyboard


def generate_storyboard(
    *,
    campaign_id: Optional[str] = None,
    feature_key: str = "truth_verification",
    style: str = "explainer",
    duration_sec: int = 30,
    product_brief: Optional[str] = None,
) -> dict[str, Any]:
    """Build a full storyboard (title, logline, VO script, shot list, CTA) and
    persist it to `marketing_out/storyboards/<id>.json`. Always available
    offline — no API key required for this step."""
    feature = CORE_FEATURES.get(feature_key) or CORE_FEATURES["truth_verification"]
    brief = (product_brief or DEFAULT_PRODUCT_BRIEF).strip()
    duration_sec = max(15, min(120, int(duration_sec or 30)))
    shots = _shot_list(feature_key if feature_key in CORE_FEATURES else "truth_verification", duration_sec)

    storyboard_id = str(uuid.uuid4())
    storyboard = {
        "storyboard_id": storyboard_id,
        "campaign_id": campaign_id,
        "feature": feature_key,
        "feature_title": feature["title"],
        "style": style,
        "duration_sec": duration_sec,
        "title": f"VeriDiQ — {feature['title']} in {duration_sec}s",
        "logline": f"A {duration_sec}-second explainer showing how VeriDiQ's {feature['title'].lower()} works.",
        "product_brief": brief,
        "script": "\n".join(f"[Scene {s['scene']}] {s['voiceover']}" for s in shots),
        "shot_list": shots,
        "call_to_action": "Try VeriDiQ free at veridiq.ai",
        "created_at": _utc_now(),
    }

    from veridiq.integrations import video_render

    render_status = video_render.status()
    storyboard["render"] = {
        "status": render_status["status"],
        "message": render_status["message"],
        "note": (
            "Render is optional — the script and shot list above are complete and can be handed to any editor "
            "or freelancer as-is. Configure VERIDIQ_VIDEO_RENDER_API_KEY / VERIDIQ_VIDEO_RENDER_WEBHOOK_URL to "
            "submit an automated render job via POST /api/v1/veridiq/marketing/video/render."
        ),
    }

    out_path = MARKETING_OUT_DIR / f"{storyboard_id}.json"
    out_path.write_text(json.dumps(storyboard, indent=2), encoding="utf-8")
    storyboard["artifact_path"] = str(out_path.relative_to(_ROOT))
    return storyboard


def get_storyboard(storyboard_id: str) -> Optional[dict[str, Any]]:
    path = MARKETING_OUT_DIR / f"{storyboard_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    data["artifact_path"] = str(path.relative_to(_ROOT))
    return data


def render_storyboard(storyboard_id: str) -> dict[str, Any]:
    """Submit the stored storyboard to the configured video render provider
    (if any). Never fabricates a rendered video file."""
    storyboard = get_storyboard(storyboard_id)
    if not storyboard:
        return {"ok": False, "error": "unknown storyboard_id"}

    from veridiq.integrations import video_render
    from veridiq.integrations.activity import global_platform_activity

    result = video_render.render_storyboard(storyboard)
    global_platform_activity.record(
        platform="video_render",
        task=f"Render storyboard {storyboard_id[:8]} ({storyboard.get('feature_title')})",
        workflow_stage="video_render",
        completion_status="completed" if result.get("status") == "ok" else "configuration_required" if result.get("status") == "configuration_required" else "failed",
        api_response_status=result.get("status"),
        recent_activity=result.get("message"),
        errors=result.get("message") if result.get("status") == "error" else None,
    )
    return {"ok": True, "storyboard_id": storyboard_id, **result}
