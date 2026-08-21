"""fal.ai — official text-to-video API (queue). No fabricated MP4s.

Auth: Authorization: Key <VERIDIQ_FAL_API_KEY>
Docs: https://fal.ai/docs
Default model: fal-ai/ltx-video (relatively cheap for free-credit accounts).
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

import requests

from veridiq.integrations.base import status_shape

API_KEY_ENV = "VERIDIQ_FAL_API_KEY"
# Also accept FAL_KEY (fal CLI / docs convention)
ALT_KEY_ENV = "FAL_KEY"
MODEL_ENV = "VERIDIQ_FAL_VIDEO_MODEL"
DEFAULT_MODEL = "fal-ai/ltx-video"
ENV_VARS = [API_KEY_ENV, MODEL_ENV]
CAPABILITIES = ["text_to_video", "render_storyboard_prompt"]
DOCS = "https://fal.ai/models/fal-ai/ltx-video/api"
QUEUE_BASE = "https://queue.fal.run"


def _api_key() -> str:
    return (os.getenv(API_KEY_ENV) or os.getenv(ALT_KEY_ENV) or "").strip().rstrip("+")


def is_configured() -> bool:
    return bool(_api_key())


def _model() -> str:
    return (os.getenv(MODEL_ENV) or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def status() -> dict[str, Any]:
    key = _api_key()
    if not key:
        return status_shape(
            "fal_ai",
            "fal.ai Video",
            "video",
            status="configuration_required",
            configured=False,
            message=f"Set {API_KEY_ENV} (fal.ai API key) to generate MP4s from storyboard prompts.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    return status_shape(
        "fal_ai",
        "fal.ai Video",
        "video",
        status="configured",
        configured=True,
        message=f"fal.ai key present — text-to-video via {_model()}.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
        extra={"model": _model()},
    )


def test_connection() -> dict[str, Any]:
    st = status()
    if not st.get("configured"):
        return {"platform": "fal_ai", "status": "configuration_required", "ok": False, "message": st.get("message")}
    # Lightweight auth check: submit is expensive; hit models list if possible, else accept configured.
    key = _api_key()
    try:
        resp = requests.get(
            "https://api.fal.ai/v1/models",
            headers={"Authorization": f"Key {key}"},
            params={"limit": 1},
            timeout=12,
        )
        if resp.status_code in (200, 401, 403):
            ok = resp.status_code == 200
            return {
                "platform": "fal_ai",
                "status": "ok" if ok else "error",
                "ok": ok,
                "api_response_status": resp.status_code,
                "message": (
                    "fal.ai API key accepted."
                    if ok
                    else f"fal.ai auth failed HTTP {resp.status_code}: {resp.text[:160]}"
                ),
            }
        return {
            "platform": "fal_ai",
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "message": f"fal.ai reachable (HTTP {resp.status_code}); key is set.",
        }
    except Exception as exc:
        return {"platform": "fal_ai", "status": "error", "ok": False, "message": str(exc)[:200]}


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Key {_api_key()}",
        "Content-Type": "application/json",
    }


def text_to_video(
    *,
    prompt: str,
    model: Optional[str] = None,
    poll_sec: float = 4.0,
    max_wait_sec: float = 240.0,
) -> dict[str, Any]:
    """Submit text-to-video on fal queue and poll until video URL or timeout."""
    key = _api_key()
    if not key:
        return {
            "status": "configuration_required",
            "ok": False,
            "message": f"Set {API_KEY_ENV} to generate video with fal.ai.",
        }
    q = (prompt or "").strip()
    if not q:
        return {"status": "invalid_args", "ok": False, "message": "prompt is required."}
    mid = (model or _model()).strip()
    try:
        submit = requests.post(
            f"{QUEUE_BASE}/{mid}",
            headers=_headers(),
            json={"prompt": q[:1800]},
            timeout=30,
        )
        if submit.status_code not in (200, 201, 202):
            return {
                "status": "error",
                "ok": False,
                "api_response_status": submit.status_code,
                "message": f"fal.ai submit HTTP {submit.status_code}: {submit.text[:240]}",
            }
        payload = submit.json() if submit.content else {}
        request_id = payload.get("request_id") or payload.get("requestId")
        if not request_id:
            # Some models return sync-ish body
            video = _extract_video(payload)
            if video:
                return {
                    "status": "ok",
                    "ok": True,
                    "provider": "fal_ai",
                    "model": mid,
                    "video_url": video,
                    "message": "fal.ai returned a video URL.",
                    "raw": _safe_raw(payload),
                }
            return {
                "status": "error",
                "ok": False,
                "message": "fal.ai submit succeeded but no request_id/video in response.",
                "raw": _safe_raw(payload),
            }

        deadline = time.time() + max(30.0, float(max_wait_sec))
        status_url = f"{QUEUE_BASE}/{mid}/requests/{request_id}/status"
        result_url = f"{QUEUE_BASE}/{mid}/requests/{request_id}"
        last_status = "IN_QUEUE"
        while time.time() < deadline:
            st_resp = requests.get(status_url, headers=_headers(), timeout=20)
            st_body = st_resp.json() if st_resp.content else {}
            last_status = str(st_body.get("status") or st_resp.status_code)
            if last_status in ("COMPLETED", "OK", "SUCCESS") or st_resp.status_code == 200 and st_body.get("status") == "COMPLETED":
                break
            if last_status in ("FAILED", "ERROR", "CANCELLED"):
                return {
                    "status": "error",
                    "ok": False,
                    "provider": "fal_ai",
                    "model": mid,
                    "request_id": request_id,
                    "message": f"fal.ai job {last_status}: {str(st_body)[:240]}",
                }
            time.sleep(max(1.5, float(poll_sec)))

        res = requests.get(result_url, headers=_headers(), timeout=45)
        if res.status_code != 200:
            return {
                "status": "error",
                "ok": False,
                "provider": "fal_ai",
                "model": mid,
                "request_id": request_id,
                "api_response_status": res.status_code,
                "message": f"fal.ai result HTTP {res.status_code}: {res.text[:240]}",
                "last_status": last_status,
            }
        data = res.json() if res.content else {}
        # queue.result wraps in {response: ...} sometimes
        body = data.get("response") if isinstance(data.get("response"), dict) else data
        video = _extract_video(body) or _extract_video(data)
        if not video:
            return {
                "status": "error",
                "ok": False,
                "provider": "fal_ai",
                "model": mid,
                "request_id": request_id,
                "message": "fal.ai completed but no video URL found in response.",
                "raw": _safe_raw(data),
            }
        return {
            "status": "ok",
            "ok": True,
            "provider": "fal_ai",
            "model": mid,
            "request_id": request_id,
            "video_url": video,
            "message": "fal.ai video ready.",
            "raw": _safe_raw(data),
        }
    except Exception as exc:
        return {"status": "error", "ok": False, "message": f"fal.ai call failed: {str(exc)[:200]}"}


def _extract_video(data: dict[str, Any]) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    video = data.get("video")
    if isinstance(video, dict) and video.get("url"):
        return str(video["url"])
    if isinstance(video, str) and video.startswith("http"):
        return video
    for key in ("video_url", "url", "output"):
        val = data.get(key)
        if isinstance(val, str) and val.startswith("http") and (".mp4" in val or "fal.media" in val or "video" in val):
            return val
        if isinstance(val, dict) and val.get("url"):
            return str(val["url"])
    return None


def _safe_raw(data: dict[str, Any]) -> dict[str, Any]:
    """Trim large payloads for API responses."""
    try:
        import json

        raw = json.dumps(data)[:800]
        return {"preview": raw}
    except Exception:
        return {}


def prompt_from_storyboard(storyboard: dict[str, Any]) -> str:
    title = str(storyboard.get("title") or "VERIDIQ product demo").strip()
    logline = str(storyboard.get("logline") or "").strip()
    shots = storyboard.get("shot_list") or []
    bits: list[str] = [
        f"Cinematic product demo for {title}. Dark midnight UI, electric blue accents, modern SaaS dashboard aesthetic.",
    ]
    if logline:
        bits.append(logline)
    for shot in shots[:5]:
        if not isinstance(shot, dict):
            continue
        vo = str(shot.get("voiceover") or "").strip()
        visual = str(shot.get("shot") or shot.get("on_screen_text") or "").strip()
        if visual:
            bits.append(visual)
        elif vo:
            bits.append(vo)
    bits.append(
        "Smooth camera push-in, crisp UI screens, professional tech commercial style, no distorted text."
    )
    return " ".join(bits)[:1800]
