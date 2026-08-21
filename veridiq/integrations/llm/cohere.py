"""Cohere — official Chat / Models API."""

from __future__ import annotations

from typing import Any

from veridiq.integrations.llm._common import configured_status, http_get_json, http_post_json, require_token

PLATFORM = "cohere"
DISPLAY = "Cohere"
CATEGORY = "ai"
ENV_VARS = ("VERIDIQ_COHERE_API_KEY",)
CAPABILITIES = ["list_models", "generate_text"]
DOCS = "https://docs.cohere.com/"
BASE = "https://api.cohere.com/v1"


def status() -> dict[str, Any]:
    return configured_status(
        PLATFORM,
        DISPLAY,
        CATEGORY,
        env_names=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
        missing_message=f"Set {ENV_VARS[0]} for Cohere API access.",
        configured_message="Cohere key present — use /test to verify with models list.",
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}


def test_connection() -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    # Lightweight auth probe
    resp, data, exc = http_get_json(f"{BASE}/models", headers=_headers(token), params={"page_size": 5})
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    if resp.status_code == 200:
        models = (data or {}).get("models") or []
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "message": f"Cohere API reachable; {len(models)} models listed.",
            "model_count": len(models),
        }
    # check-api-key fallback (v2)
    resp2, data2, exc2 = http_post_json(
        "https://api.cohere.com/v1/check-api-key",
        headers=_headers(token),
        json_body={},
    )
    if not exc2 and resp2 is not None and resp2.status_code == 200 and (data2 or {}).get("valid"):
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp2.status_code,
            "message": "Cohere API key valid (check-api-key).",
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": f"Cohere API HTTP {resp.status_code}.",
    }


def generate_text(*, prompt: str, model: str = "command-r-plus-08-2024", **kwargs: Any) -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    if not (prompt or "").strip():
        return {"platform": PLATFORM, "status": "invalid_args", "ok": False, "message": "prompt is required."}
    resp, data, exc = http_post_json(
        f"{BASE}/chat",
        headers=_headers(token),
        json_body={"model": model, "message": prompt[:12000]},
    )
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    if resp.status_code == 200:
        text = (data or {}).get("text") or ""
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "model": model,
            "text": text[:8000],
            "message": "Cohere chat succeeded.",
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": (data or {}).get("message") or f"Cohere HTTP {resp.status_code}.",
    }
