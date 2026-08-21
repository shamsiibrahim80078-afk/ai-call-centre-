"""AssemblyAI — official speech-to-text API."""

from __future__ import annotations

from typing import Any

from veridiq.integrations.llm._common import configured_status, http_get_json, http_post_json, require_token

PLATFORM = "assemblyai"
DISPLAY = "AssemblyAI"
CATEGORY = "speech"
ENV_VARS = ("VERIDIQ_ASSEMBLYAI_API_KEY",)
CAPABILITIES = ["account", "transcribe"]
DOCS = "https://www.assemblyai.com/docs"
BASE = "https://api.assemblyai.com/v2"


def status() -> dict[str, Any]:
    return configured_status(
        PLATFORM,
        DISPLAY,
        CATEGORY,
        env_names=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
        missing_message=f"Set {ENV_VARS[0]} for AssemblyAI speech API access.",
        configured_message="AssemblyAI key present — use /test to verify account endpoint.",
    )


def _headers(token: str) -> dict[str, str]:
    return {"authorization": token, "content-type": "application/json"}


def test_connection() -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    resp, data, exc = http_get_json(f"{BASE}/account", headers=_headers(token))
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    if resp.status_code == 200:
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "message": "AssemblyAI account endpoint reachable.",
            "account_id": (data or {}).get("id"),
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": f"AssemblyAI HTTP {resp.status_code}.",
    }


def transcribe(*, audio_url: str, **_kwargs: Any) -> dict[str, Any]:
    """Submit a transcription job for a publicly reachable audio URL (explicit call only)."""
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
    resp, data, exc = http_post_json(
        f"{BASE}/transcript",
        headers=_headers(token),
        json_body={"audio_url": audio_url.strip()},
    )
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    if resp.status_code in {200, 201}:
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "transcript_id": (data or {}).get("id"),
            "transcript_status": (data or {}).get("status"),
            "message": "AssemblyAI transcript job submitted.",
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": (data or {}).get("error") or f"AssemblyAI HTTP {resp.status_code}.",
    }
