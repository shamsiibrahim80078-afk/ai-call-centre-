"""Deepgram — official speech-to-text API."""

from __future__ import annotations

from typing import Any

import requests

from veridiq.integrations.llm._common import configured_status, http_get_json, require_token

PLATFORM = "deepgram"
DISPLAY = "Deepgram"
CATEGORY = "speech"
ENV_VARS = ("VERIDIQ_DEEPGRAM_API_KEY",)
CAPABILITIES = ["projects", "transcribe"]
DOCS = "https://developers.deepgram.com/"
BASE = "https://api.deepgram.com/v1"


def status() -> dict[str, Any]:
    return configured_status(
        PLATFORM,
        DISPLAY,
        CATEGORY,
        env_names=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
        missing_message=f"Set {ENV_VARS[0]} for Deepgram speech API access.",
        configured_message="Deepgram key present — use /test to verify projects endpoint.",
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Token {token}", "Content-Type": "application/json"}


def test_connection() -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    resp, data, exc = http_get_json(f"{BASE}/projects", headers=_headers(token))
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    if resp.status_code == 200:
        projects = (data or {}).get("projects") or []
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "message": f"Deepgram API reachable; {len(projects)} project(s).",
            "project_count": len(projects),
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": f"Deepgram HTTP {resp.status_code}.",
    }


def transcribe(*, audio_url: str, model: str = "nova-2", **_kwargs: Any) -> dict[str, Any]:
    """Transcribe a public audio URL via Deepgram listen (explicit call only)."""
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    if not (audio_url or "").strip():
        return {
            "platform": PLATFORM,
            "status": "invalid_args",
            "ok": False,
            "message": "audio_url is required (public HTTPS URL).",
        }
    try:
        r = requests.post(
            f"{BASE}/listen",
            headers=_headers(token),
            params={"model": model, "smart_format": "true"},
            json={"url": audio_url.strip()},
            timeout=60,
        )
        payload = r.json() if "json" in (r.headers.get("content-type") or "").lower() else {}
        if r.status_code == 200:
            results = payload.get("results") or {}
            channels = results.get("channels") or []
            transcript = ""
            if channels:
                alts = channels[0].get("alternatives") or [{}]
                transcript = (alts[0] or {}).get("transcript") or ""
            return {
                "platform": PLATFORM,
                "status": "ok",
                "ok": True,
                "api_response_status": r.status_code,
                "model": model,
                "text": transcript[:8000],
                "message": "Deepgram listen succeeded.",
            }
        return {
            "platform": PLATFORM,
            "status": "error",
            "ok": False,
            "api_response_status": r.status_code,
            "message": (payload.get("err_msg") if isinstance(payload, dict) else None)
            or f"Deepgram HTTP {r.status_code}.",
        }
    except Exception as exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": str(exc)[:200]}
