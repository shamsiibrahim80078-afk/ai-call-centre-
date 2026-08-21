"""SerpAPI — official Google search results API."""

from __future__ import annotations

from typing import Any

from veridiq.integrations.base import first_env, status_shape
from veridiq.integrations.llm._common import http_get_json, require_token

PLATFORM = "serpapi"
DISPLAY = "SerpAPI"
CATEGORY = "research"
ENV_VARS = ("VERIDIQ_SERPAPI_API_KEY", "SERPAPI_API_KEY")
CAPABILITIES = ["search"]
DOCS = "https://serpapi.com/search-api"
BASE = "https://serpapi.com"


def status() -> dict[str, Any]:
    token = first_env(*ENV_VARS)
    if not token:
        return status_shape(
            PLATFORM,
            DISPLAY,
            CATEGORY,
            status="configuration_required",
            configured=False,
            message=f"Set {ENV_VARS[0]} for SerpAPI search.",
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
        message="SerpAPI key present — use /test or search.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def test_connection() -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    resp, data, exc = http_get_json(
        f"{BASE}/account",
        params={"api_key": token},
        timeout=12,
    )
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    if resp.status_code == 200:
        plan = (data or {}).get("plan_name") or (data or {}).get("account_email") or "account"
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "message": f"SerpAPI account reachable ({plan}).",
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": f"SerpAPI HTTP {resp.status_code}.",
    }


def search(*, query: str, num: int = 5, **_kwargs: Any) -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    q = (query or "").strip()
    if not q:
        return {"platform": PLATFORM, "status": "invalid_args", "ok": False, "message": "query is required."}
    resp, data, exc = http_get_json(
        f"{BASE}/search",
        params={
            "api_key": token,
            "q": q[:500],
            "engine": "google",
            "num": max(1, min(10, int(num))),
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
            "message": f"SerpAPI HTTP {resp.status_code}.",
        }
    organic = (data or {}).get("organic_results") or []
    results = [
        {
            "title": r.get("title"),
            "url": r.get("link"),
            "snippet": (r.get("snippet") or "")[:500],
            "position": r.get("position"),
            "provider": PLATFORM,
        }
        for r in organic
    ]
    return {
        "platform": PLATFORM,
        "status": "ok",
        "ok": True,
        "api_response_status": resp.status_code,
        "query": q,
        "results": results,
        "count": len(results),
        "message": f"SerpAPI returned {len(results)} organic result(s).",
    }
