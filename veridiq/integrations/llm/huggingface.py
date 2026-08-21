"""Hugging Face — Inference API + whoami; optional local OCR note (no CI downloads)."""

from __future__ import annotations

import os
from typing import Any

import requests

from veridiq.integrations.llm._common import configured_status, http_get_json, require_token

PLATFORM = "huggingface"
DISPLAY = "Hugging Face"
CATEGORY = "ai"
ENV_VARS = ("VERIDIQ_HF_TOKEN",)
CAPABILITIES = ["whoami", "generate_text", "inference_api", "local_ocr_optional"]
DOCS = "https://huggingface.co/docs/api-inference"
WHOAMI = "https://huggingface.co/api/whoami-v2"
INFERENCE = "https://api-inference.huggingface.co/models"


def status() -> dict[str, Any]:
    base = configured_status(
        PLATFORM,
        DISPLAY,
        CATEGORY,
        env_names=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
        missing_message=f"Set {ENV_VARS[0]} for Hugging Face Inference / whoami.",
        configured_message=(
            "HF token present — default path is Inference API. "
            "Local OCR (e.g. baidu/Unlimited-OCR via transformers) is optional: "
            "set VERIDIQ_HF_LOCAL_OCR=1; never downloaded in CI."
        ),
    )
    if os.getenv("VERIDIQ_HF_LOCAL_OCR", "").strip().lower() in {"1", "true", "yes"}:
        base["message"] = (
            (base.get("message") or "")
            + " Local OCR flag enabled — requires transformers + model weights on this host."
        )
    return base


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_connection() -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    resp, data, exc = http_get_json(WHOAMI, headers=_headers(token))
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    if resp.status_code == 200:
        name = (data or {}).get("name") or (data or {}).get("fullname") or "user"
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "message": f"Hugging Face whoami ok ({name}).",
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": f"Hugging Face whoami HTTP {resp.status_code}.",
    }


def generate_text(*, prompt: str, model: str = "gpt2", **_kwargs: Any) -> dict[str, Any]:
    """Minimal Inference API text generation. Does not download local transformers models."""
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    if not (prompt or "").strip():
        return {"platform": PLATFORM, "status": "invalid_args", "ok": False, "message": "prompt is required."}
    try:
        r = requests.post(
            f"{INFERENCE}/{model}",
            headers={**_headers(token), "Content-Type": "application/json"},
            json={"inputs": prompt[:2000], "parameters": {"max_new_tokens": 64}},
            timeout=60,
        )
        payload = r.json() if "json" in (r.headers.get("content-type") or "").lower() else None
        if r.status_code == 200:
            text = ""
            if isinstance(payload, list) and payload:
                first = payload[0]
                text = str(first.get("generated_text") if isinstance(first, dict) else first)
            elif isinstance(payload, dict):
                text = str(payload.get("generated_text") or payload.get("error") or "")
            return {
                "platform": PLATFORM,
                "status": "ok",
                "ok": True,
                "api_response_status": r.status_code,
                "model": model,
                "text": text[:8000],
                "message": "Hugging Face Inference API succeeded.",
                "note": "Local OCR/transformers is opt-in via VERIDIQ_HF_LOCAL_OCR=1 only.",
            }
        err_msg = None
        if isinstance(payload, dict):
            err_msg = payload.get("error")
        return {
            "platform": PLATFORM,
            "status": "error",
            "ok": False,
            "api_response_status": r.status_code,
            "message": err_msg or f"HF Inference HTTP {r.status_code}.",
        }
    except Exception as exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": str(exc)[:200]}
