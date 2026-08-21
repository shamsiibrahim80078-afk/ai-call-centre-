"""Mira freemium stub — free by default; premium switches on later via env.

Enable premium later without restructuring the agent:

  VERIDIQ_MIRA_TIER=premium
  VERIDIQ_GEMINI_VIDEO=1          # optional Veo native video
  # and/or
  VERIDIQ_VIDEO_PREFER_FAL=1      # optional fal.ai video

Until both the tier and at least one paid-video flag are set, every create_*
path stays on the free Mira Creative Model pipeline. No billing UI required.
"""

from __future__ import annotations

import os
from typing import Any


TIER_ENV = "VERIDIQ_MIRA_TIER"
VEO_ENV = "VERIDIQ_GEMINI_VIDEO"
FAL_PREFER_ENV = "VERIDIQ_VIDEO_PREFER_FAL"

FREE_FEATURES = ("posts", "images", "designs", "videos", "songs")
PREMIUM_FEATURES = ("veo_native_video",)


def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def current_tier() -> str:
    """Return ``free`` (default) or ``premium`` from ``VERIDIQ_MIRA_TIER``."""
    raw = (os.getenv(TIER_ENV) or "free").strip().lower()
    if raw in ("premium", "pro", "paid"):
        return "premium"
    return "free"


def veo_flag_on() -> bool:
    """Paid Veo opt-in flag (same semantics as google_ai.veo_enabled)."""
    return _truthy(os.getenv(VEO_ENV))


def fal_flag_on() -> bool:
    """Optional fal.ai prefer flag — premium backend switch, not a key check."""
    return _truthy(os.getenv(FAL_PREFER_ENV))


def is_premium() -> bool:
    """True only if tier=premium AND (Veo flag or fal flag).

    Having ``VERIDIQ_GEMINI_VIDEO=1`` alone does not unlock premium while
    ``VERIDIQ_MIRA_TIER`` remains free (the default).
    """
    if current_tier() != "premium":
        return False
    return veo_flag_on() or fal_flag_on()


def premium_ready() -> bool:
    """Code path for premium exists but is off until ``is_premium()``."""
    return True


def premium_video_unlocked() -> bool:
    """Native paid video (Veo) may be attempted only when premium is active + Veo on."""
    return is_premium() and veo_flag_on()


def status() -> dict[str, Any]:
    tier = current_tier()
    premium = is_premium()
    return {
        "tier": tier,
        "is_premium": premium,
        "premium_ready": premium_ready(),
        "free_features": list(FREE_FEATURES),
        "premium_features": list(PREMIUM_FEATURES),
        "premium_locked": not premium,
        "veo_flag": veo_flag_on(),
        "fal_flag": fal_flag_on(),
        "env": {
            "tier": TIER_ENV,
            "veo": VEO_ENV,
            "fal_prefer": FAL_PREFER_ENV,
        },
        "message": (
            "Mira Free Model active — unlimited posts/images/designs/videos/songs."
            if not premium
            else "Mira premium tier active — paid video backends may be used."
        ),
    }
