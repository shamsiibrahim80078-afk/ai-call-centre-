"""Video render — local unlimited free MP4 first; fal/webhook optional.

Never fabricates an MP4. Local slideshow is $0 / unlimited. fal.ai is optional
paid/credits cinematic path when explicitly preferred or local unavailable.
"""

from __future__ import annotations

import os
from typing import Any

import requests

from veridiq.integrations.base import status_shape

RENDER_API_KEY = "VERIDIQ_VIDEO_RENDER_API_KEY"
RENDER_WEBHOOK_URL = "VERIDIQ_VIDEO_RENDER_WEBHOOK_URL"
FAL_KEY = "VERIDIQ_FAL_API_KEY"
PREFER_FAL = "VERIDIQ_VIDEO_PREFER_FAL"
ENV_VARS = [FAL_KEY, RENDER_API_KEY, RENDER_WEBHOOK_URL, "VERIDIQ_VIDEO_LOCAL", PREFER_FAL]
CAPABILITIES = [
    "local unlimited free MP4 slideshow (default)",
    "fal.ai text-to-video (optional credits)",
    "optional operator webhook",
]


def _prefer_fal() -> bool:
    return (os.getenv(PREFER_FAL) or "").strip().lower() in ("1", "true", "yes", "on")


def status() -> dict[str, Any]:
    from veridiq.integrations import fal_ai, local_video

    local = local_video.status()
    if local.get("configured") and not _prefer_fal():
        return status_shape(
            "video_render",
            "Video Render",
            "video",
            status="configured",
            configured=True,
            message=local.get("message") or "Local unlimited free MP4 ready.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=None,
            extra={"provider": "local_video", "unlimited": True, "local": local},
        )

    fal = fal_ai.status()
    if fal.get("configured") and _prefer_fal():
        return status_shape(
            "video_render",
            "Video Render",
            "video",
            status="configured",
            configured=True,
            message=fal.get("message") or "fal.ai configured.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url="https://fal.ai/models/fal-ai/ltx-video/api",
            extra={"provider": "fal_ai", "fal": fal},
        )

    if local.get("configured"):
        return status_shape(
            "video_render",
            "Video Render",
            "video",
            status="configured",
            configured=True,
            message=local.get("message"),
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=None,
            extra={"provider": "local_video", "unlimited": True},
        )

    key = os.getenv(RENDER_API_KEY)
    webhook = os.getenv(RENDER_WEBHOOK_URL)
    if key and webhook:
        return status_shape(
            "video_render",
            "Video Render",
            "video",
            status="configured",
            configured=True,
            message="Render webhook configured.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=None,
            extra={"provider": "webhook"},
        )

    return status_shape(
        "video_render",
        "Video Render",
        "video",
        status="configuration_required",
        configured=False,
        message=(
            "Install imageio + imageio-ffmpeg for unlimited free local MP4s "
            f"(pip install imageio imageio-ffmpeg). Optional: {FAL_KEY} for AI video credits."
        ),
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=None,
    )


def test_connection() -> dict[str, Any]:
    from veridiq.integrations import local_video

    if local_video.is_enabled():
        return local_video.test_connection()
    result = status()
    return {"platform": "video_render", "status": result["status"], "message": result["message"]}


def render_storyboard(storyboard: dict[str, Any]) -> dict[str, Any]:
    """Local free unlimited first; fal only if preferred; else webhook."""
    from veridiq.integrations import fal_ai, local_video

    # Default: local unlimited free
    if local_video.is_enabled() and not _prefer_fal():
        local = local_video.render_storyboard(storyboard or {})
        if local.get("ok") or local.get("status") == "ok":
            return local
        # If local failed hard, fall through to fal/webhook

    if fal_ai.is_configured() and _prefer_fal():
        prompt = fal_ai.prompt_from_storyboard(storyboard or {})
        result = fal_ai.text_to_video(prompt=prompt)
        result["storyboard_id"] = (storyboard or {}).get("storyboard_id")
        result["prompt_used"] = prompt[:400]
        return result

    if local_video.is_enabled():
        return local_video.render_storyboard(storyboard or {})

    key = os.getenv(RENDER_API_KEY)
    if not key:
        return {
            "status": "configuration_required",
            "message": (
                "Local free video needs: pip install imageio imageio-ffmpeg. "
                f"Optional paid/credits path: {FAL_KEY}."
            ),
        }
    webhook = os.getenv(RENDER_WEBHOOK_URL)
    if not webhook:
        return {
            "status": "configuration_required",
            "message": f"Set {RENDER_WEBHOOK_URL} or use local free renderer.",
        }
    try:
        resp = requests.post(
            webhook,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=storyboard,
            timeout=15,
        )
        if resp.status_code in (200, 201, 202):
            return {
                "status": "ok",
                "message": f"Render job submitted to configured webhook (HTTP {resp.status_code}).",
                "provider_response": resp.text[:500],
            }
        return {
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"Render webhook returned HTTP {resp.status_code}: {resp.text[:200]}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Render webhook call failed: {str(exc)[:200]}"}
