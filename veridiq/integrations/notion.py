"""Notion — official Notion API (list/search pages)."""

from __future__ import annotations

from typing import Any

from veridiq.integrations.base import first_env, status_shape
from veridiq.integrations.llm._common import http_get_json, http_post_json, require_token

PLATFORM = "notion"
DISPLAY = "Notion"
CATEGORY = "productivity"
ENV_VARS = ("VERIDIQ_NOTION_TOKEN", "NOTION_TOKEN")
CAPABILITIES = ["whoami", "search_pages"]
DOCS = "https://developers.notion.com/"
BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def status() -> dict[str, Any]:
    token = first_env(*ENV_VARS)
    if not token:
        return status_shape(
            PLATFORM,
            DISPLAY,
            CATEGORY,
            status="configuration_required",
            configured=False,
            message=f"Set {ENV_VARS[0]} (internal integration secret) for Notion API.",
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
        message="Notion token present — use /test or search_pages.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def test_connection() -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    resp, data, exc = http_get_json(f"{BASE}/users/me", headers=_headers(token), timeout=12)
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    if resp.status_code == 200:
        bot = (data or {}).get("bot") or {}
        name = (data or {}).get("name") or bot.get("owner") or "bot"
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "message": f"Notion bot verified ({name}).",
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": f"Notion HTTP {resp.status_code}.",
    }


def search_pages(*, query: str = "", page_size: int = 10, **_kwargs: Any) -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    body: dict[str, Any] = {"page_size": max(1, min(25, int(page_size)))}
    q = (query or "").strip()
    if q:
        body["query"] = q[:200]
    resp, data, exc = http_post_json(
        f"{BASE}/search",
        headers=_headers(token),
        json_body=body,
        timeout=15,
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
            "message": f"Notion HTTP {resp.status_code}.",
        }
    pages = []
    for item in (data or {}).get("results") or []:
        props = item.get("properties") or {}
        title = None
        for prop in props.values():
            if isinstance(prop, dict) and prop.get("type") == "title":
                parts = prop.get("title") or []
                title = "".join(p.get("plain_text") or "" for p in parts) or None
                break
        pages.append(
            {
                "id": item.get("id"),
                "object": item.get("object"),
                "url": item.get("url"),
                "title": title,
            }
        )
    return {
        "platform": PLATFORM,
        "status": "ok",
        "ok": True,
        "api_response_status": resp.status_code,
        "pages": pages,
        "count": len(pages),
        "message": f"Notion search returned {len(pages)} item(s).",
    }
