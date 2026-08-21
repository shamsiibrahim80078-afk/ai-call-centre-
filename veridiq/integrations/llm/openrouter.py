"""OpenRouter — official OpenAI-compatible unified LLM API."""

from __future__ import annotations

from typing import Any

from veridiq.integrations.llm._common import configured_status, http_get_json, http_post_json, require_token

PLATFORM = "openrouter"
DISPLAY = "OpenRouter"
CATEGORY = "ai"
ENV_VARS = ("VERIDIQ_OPENROUTER_API_KEY",)
CAPABILITIES = ["list_models", "generate_text", "auth_key"]
DOCS = "https://openrouter.ai/docs"
BASE = "https://openrouter.ai/api/v1"


def status() -> dict[str, Any]:
    return configured_status(
        PLATFORM,
        DISPLAY,
        CATEGORY,
        env_names=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
        missing_message=f"Set {ENV_VARS[0]} for OpenRouter API access.",
        configured_message="OpenRouter key present — use /test to verify auth/key.",
    )


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://veridiq.local",
        "X-Title": "VERIDIQ",
    }


def test_connection() -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    resp, data, exc = http_get_json(f"{BASE}/auth/key", headers=_headers(token))
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    if resp.status_code == 200:
        meta = (data or {}).get("data") or data or {}
        label = str(meta.get("label") or meta.get("name") or "ok")
        # Never echo key-shaped labels from the auth/key payload
        if label.startswith("sk-") or len(label) > 40:
            label = "authenticated"
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "message": f"OpenRouter auth ok ({label}).",
        }
    # Fallback: models list (some keys only allow this)
    resp2, data2, exc2 = http_get_json(f"{BASE}/models", headers=_headers(token))
    if exc2:
        return {
            "platform": PLATFORM,
            "status": "error",
            "ok": False,
            "api_response_status": resp.status_code,
            "message": f"OpenRouter auth HTTP {resp.status_code}; models fallback: {exc2}",
        }
    assert resp2 is not None
    if resp2.status_code == 200:
        items = (data2 or {}).get("data") or []
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp2.status_code,
            "message": f"OpenRouter models reachable; {len(items)} models.",
            "model_count": len(items),
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp2.status_code,
        "message": f"OpenRouter HTTP {resp2.status_code}.",
    }


def generate_text(
    *,
    prompt: str,
    model: str = "openai/gpt-4o-mini",
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
            "message": "OpenRouter chat completion succeeded.",
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": f"OpenRouter HTTP {resp.status_code}.",
    }
