"""Groq — official OpenAI-compatible chat/completions API."""

from __future__ import annotations

from typing import Any

from veridiq.integrations.llm._common import configured_status, http_get_json, http_post_json, require_token

PLATFORM = "groq"
DISPLAY = "Groq"
CATEGORY = "ai"
ENV_VARS = ("VERIDIQ_GROQ_API_KEY",)
CAPABILITIES = ["list_models", "generate_text"]
DOCS = "https://console.groq.com/docs/overview"
BASE = "https://api.groq.com/openai/v1"


def status() -> dict[str, Any]:
    return configured_status(
        PLATFORM,
        DISPLAY,
        CATEGORY,
        env_names=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
        missing_message=f"Set {ENV_VARS[0]} for Groq API access.",
        configured_message="Groq key present — use /test to verify with models.list.",
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def test_connection() -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    resp, data, exc = http_get_json(f"{BASE}/models", headers=_headers(token))
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    if resp.status_code == 200:
        items = (data or {}).get("data") or []
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "message": f"Groq API reachable; {len(items)} models listed.",
            "model_count": len(items),
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": f"Groq API HTTP {resp.status_code}.",
    }


def generate_text(
    *,
    prompt: str,
    model: str = "llama-3.1-8b-instant",
    **kwargs: Any,
) -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    if not (prompt or "").strip():
        return {"platform": PLATFORM, "status": "invalid_args", "ok": False, "message": "prompt is required."}
    max_tokens = int(kwargs.get("max_tokens") or 256)
    resp, data, exc = http_post_json(
        f"{BASE}/chat/completions",
        headers=_headers(token),
        json_body={
            "model": model,
            "messages": [{"role": "user", "content": prompt[:12000]}],
            "max_tokens": max(64, min(max_tokens, 4096)),
        },
    )
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    if resp.status_code == 200:
        choices = (data or {}).get("choices") or []
        text = ""
        if choices:
            text = ((choices[0].get("message") or {}).get("content")) or ""
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "model": model,
            "text": text[:8000],
            "message": "Groq chat completion succeeded.",
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": ((data or {}).get("error") or {}).get("message")
        if isinstance((data or {}).get("error"), dict)
        else f"Groq HTTP {resp.status_code}.",
    }
