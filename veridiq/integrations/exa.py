"""Exa — official neural / keyword search API."""

from __future__ import annotations

from typing import Any

from veridiq.integrations.base import first_env, status_shape
from veridiq.integrations.llm._common import http_post_json, require_token

PLATFORM = "exa"
DISPLAY = "Exa Search"
CATEGORY = "research"
ENV_VARS = ("VERIDIQ_EXA_API_KEY", "EXA_API_KEY")
CAPABILITIES = ["search"]
DOCS = "https://docs.exa.ai/"
BASE = "https://api.exa.ai"


def status() -> dict[str, Any]:
    token = first_env(*ENV_VARS)
    if not token:
        return status_shape(
            PLATFORM,
            DISPLAY,
            CATEGORY,
            status="configuration_required",
            configured=False,
            message=f"Set {ENV_VARS[0]} for Exa search.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    return status_shape(
        PLATFORM,
        DISPLAY,
        CATEGORY,
        status="configured",
        configured=True,
        message="Exa key present — use /test or search.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def _headers(token: str) -> dict[str, str]:
    return {"x-api-key": token, "Content-Type": "application/json", "Accept": "application/json"}


def test_connection() -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    resp, data, exc = http_post_json(
        f"{BASE}/search",
        headers=_headers(token),
        json_body={"query": "veridiq connectivity ping", "numResults": 1, "type": "auto"},
        timeout=15,
    )
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    if resp.status_code == 200:
        results = (data or {}).get("results") or []
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "message": f"Exa reachable; {len(results)} result(s) on probe.",
            "result_count": len(results),
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": f"Exa HTTP {resp.status_code}.",
    }


def search(*, query: str, num_results: int = 5, **_kwargs: Any) -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    q = (query or "").strip()
    if not q:
        return {"platform": PLATFORM, "status": "invalid_args", "ok": False, "message": "query is required."}
    resp, data, exc = http_post_json(
        f"{BASE}/search",
        headers=_headers(token),
        json_body={
            "query": q[:500],
            "numResults": max(1, min(10, int(num_results))),
            "type": "auto",
            "contents": {"text": {"maxCharacters": 400}},
        },
        timeout=20,
    )
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    if resp.status_code != 200:
        return {
            "platform": PLATFORM,
            "status": "error",
            "ok": False,
            "api_response_status": resp.status_code,
            "message": f"Exa HTTP {resp.status_code}.",
        }
    raw = (data or {}).get("results") or []
    results = []
    for r in raw:
        text = ""
        if isinstance(r.get("text"), str):
            text = r["text"]
        elif isinstance(r.get("contents"), dict):
            text = str((r["contents"] or {}).get("text") or "")
        results.append(
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "snippet": text[:500],
                "score": r.get("score"),
                "provider": PLATFORM,
            }
        )
    return {
        "platform": PLATFORM,
        "status": "ok",
        "ok": True,
        "api_response_status": resp.status_code,
        "query": q,
        "results": results,
        "count": len(results),
        "message": f"Exa returned {len(results)} result(s).",
    }
