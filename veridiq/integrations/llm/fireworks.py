"""Fireworks AI — official OpenAI-compatible inference API."""

from __future__ import annotations

from typing import Any, Optional

from veridiq.integrations.llm._common import configured_status, http_get_json, http_post_json, require_token

PLATFORM = "fireworks"
DISPLAY = "Fireworks AI"
CATEGORY = "ai"
ENV_VARS = ("VERIDIQ_FIREWORKS_API_KEY",)
CAPABILITIES = ["list_models", "generate_text"]
DOCS = "https://docs.fireworks.ai/"
# OpenAI-compatible inference base (chat/completions, models.list)
BASE = "https://api.fireworks.ai/inference/v1"
# Control-plane models catalog (AIP-style list; supports_serverless filter)
ACCOUNTS_MODELS_URL = "https://api.fireworks.ai/v1/accounts/fireworks/models"
# llama-v3p1-8b-instruct is on-demand only (serverless=false) → inference 404.
# Prefer a current serverless model for probes and default generate_text.
DEFAULT_MODEL = "accounts/fireworks/models/gpt-oss-20b"
BILLING_HELP = "https://fireworks.ai/account/billing"
MODELS_HELP = "https://app.fireworks.ai/models?filter=LLM&serverless=true"


def status() -> dict[str, Any]:
    return configured_status(
        PLATFORM,
        DISPLAY,
        CATEGORY,
        env_names=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
        missing_message=f"Set {ENV_VARS[0]} for Fireworks AI API access.",
        configured_message="Fireworks key present — use /test to verify with models.list.",
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _api_error_message(data: Optional[dict[str, Any]]) -> str:
    if not isinstance(data, dict):
        return ""
    err = data.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("code") or ""
        return str(msg).strip()
    if isinstance(err, str):
        return err.strip()
    return str(data.get("message") or "").strip()


def _explain_http(status_code: int, data: Optional[dict[str, Any]], *, context: str) -> str:
    detail = _api_error_message(data)
    if status_code == 401:
        return (
            f"Fireworks {context} HTTP 401 (unauthorized). "
            "Check VERIDIQ_FIREWORKS_API_KEY in the Fireworks console."
            + (f" API: {detail}" if detail else "")
        )
    if status_code == 403:
        return (
            f"Fireworks {context} HTTP 403 (forbidden)."
            + (f" API: {detail}" if detail else "")
        )
    if status_code == 404:
        return (
            f"Fireworks {context} HTTP 404 - model missing, not serverless, or not deployed. "
            f"Use a serverless model from {MODELS_HELP}."
            + (f" API: {detail}" if detail else "")
        )
    if status_code == 412:
        return (
            f"Fireworks {context} HTTP 412 (precondition failed) - account suspended or "
            f"billing issue. Fix at {BILLING_HELP}."
            + (f" API: {detail}" if detail else "")
        )
    if detail:
        return f"Fireworks {context} HTTP {status_code}: {detail}"
    return f"Fireworks {context} HTTP {status_code}."


def _count_models(data: Optional[dict[str, Any]]) -> int:
    if not isinstance(data, dict):
        return 0
    items = data.get("data")
    if isinstance(items, list):
        return len(items)
    # Control-plane ListModels uses `models` array
    models = data.get("models")
    if isinstance(models, list):
        return len(models)
    return 0


def test_connection() -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err

    # 1) OpenAI-compatible models.list
    resp, data, exc = http_get_json(f"{BASE}/models", headers=_headers(token))
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    if resp.status_code == 200:
        count = _count_models(data)
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "message": f"Fireworks API reachable; {count} models listed.",
            "model_count": count,
        }

    # 2) Control-plane serverless catalog (alternate when inference /models fails)
    resp_acc, data_acc, exc_acc = http_get_json(
        ACCOUNTS_MODELS_URL,
        headers=_headers(token),
        params={"filter": "supports_serverless=true", "pageSize": 5},
    )
    if not exc_acc and resp_acc is not None and resp_acc.status_code == 200:
        count = _count_models(data_acc)
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp_acc.status_code,
            "message": (
                f"Fireworks control-plane reachable; {count} serverless models listed "
                f"(inference /models returned HTTP {resp.status_code})."
            ),
            "model_count": count,
        }

    # 3) Tiny chat completion with a known serverless model
    resp2, data2, exc2 = http_post_json(
        f"{BASE}/chat/completions",
        headers=_headers(token),
        json_body={
            "model": DEFAULT_MODEL,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        },
        timeout=30,
    )
    if exc2:
        return {
            "platform": PLATFORM,
            "status": "error",
            "ok": False,
            "api_response_status": resp.status_code,
            "message": (
                f"{_explain_http(resp.status_code, data, context='models.list')}; "
                f"completion fallback: {exc2}"
            ),
        }
    assert resp2 is not None
    if resp2.status_code == 200:
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp2.status_code,
            "message": "Fireworks chat completion probe succeeded (models.list unavailable).",
        }

    # Prefer the most actionable status (412 billing > 404 model > first models status)
    primary_code = resp2.status_code
    primary_data = data2
    if resp.status_code == 412:
        primary_code = resp.status_code
        primary_data = data
    elif resp_acc is not None and resp_acc.status_code == 412:
        primary_code = resp_acc.status_code
        primary_data = data_acc

    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": primary_code,
        "message": _explain_http(primary_code, primary_data, context="test_connection"),
        "attempts": {
            "inference_models": resp.status_code,
            "accounts_models": None if resp_acc is None else resp_acc.status_code,
            "chat_completions": resp2.status_code,
        },
    }


def generate_text(
    *,
    prompt: str,
    model: str = DEFAULT_MODEL,
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
            "message": "Fireworks chat completion succeeded.",
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": _explain_http(resp.status_code, data, context="chat/completions"),
    }
