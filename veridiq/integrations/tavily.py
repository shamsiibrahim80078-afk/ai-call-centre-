"""Tavily Search — official HTTP API (research / web search)."""

from __future__ import annotations

from typing import Any

from veridiq.integrations.base import first_env, status_shape
from veridiq.integrations.llm._common import http_post_json, require_token

PLATFORM = "tavily"
DISPLAY = "Tavily Search"
CATEGORY = "research"
ENV_VARS = ("VERIDIQ_TAVILY_API_KEY", "TAVILY_API_KEY")
CAPABILITIES = ["search"]
DOCS = "https://docs.tavily.com/"
BASE = "https://api.tavily.com"


def status() -> dict[str, Any]:
    token = first_env(*ENV_VARS)
    if not token:
        return status_shape(
            PLATFORM,
            DISPLAY,
            CATEGORY,
            status="configuration_required",
            configured=False,
            message=f"Set {ENV_VARS[0]} for Tavily web search.",
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
        message="Tavily key present — use /test or search.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def test_connection() -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    resp, data, exc = http_post_json(
        f"{BASE}/search",
        headers={"Content-Type": "application/json"},
        json_body={"api_key": token, "query": "veridiq connectivity ping", "max_results": 1},
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
            "message": f"Tavily reachable; {len(results)} result(s) on probe.",
            "result_count": len(results),
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": f"Tavily HTTP {resp.status_code}.",
    }


def search(*, query: str, max_results: int = 5, **_kwargs: Any) -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    q = (query or "").strip()
    if not q:
        return {"platform": PLATFORM, "status": "invalid_args", "ok": False, "message": "query is required."}
    resp, data, exc = http_post_json(
        f"{BASE}/search",
        headers={"Content-Type": "application/json"},
        json_body={
            "api_key": token,
            "query": q[:500],
            "max_results": max(1, min(10, int(max_results))),
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
            "message": f"Tavily HTTP {resp.status_code}.",
        }
    raw = (data or {}).get("results") or []
    results = [
        {
            "title": r.get("title"),
            "url": r.get("url"),
            "snippet": (r.get("content") or r.get("snippet") or "")[:500],
            "score": r.get("score"),
            "provider": PLATFORM,
        }
        for r in raw
    ]
    return {
        "platform": PLATFORM,
        "status": "ok",
        "ok": True,
        "api_response_status": resp.status_code,
        "query": q,
        "results": results,
        "count": len(results),
        "message": f"Tavily returned {len(results)} result(s).",
    }
