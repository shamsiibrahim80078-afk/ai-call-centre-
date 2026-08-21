"""Shared helpers for AI provider connectors."""

from __future__ import annotations

from typing import Any, Optional

import requests

from veridiq.integrations.base import first_env, status_shape


def configured_status(
    platform: str,
    display_name: str,
    category: str,
    *,
    env_names: tuple[str, ...],
    capabilities: list[str],
    docs_url: str,
    missing_message: str,
    configured_message: str,
) -> dict[str, Any]:
    token = first_env(*env_names)
    if not token:
        return status_shape(
            platform,
            display_name,
            category,
            status="configuration_required",
            configured=False,
            message=missing_message,
            env_vars=env_names,
            capabilities=capabilities,
            docs_url=docs_url,
        )
    return status_shape(
        platform,
        display_name,
        category,
        status="configured",
        configured=True,
        message=configured_message,
        env_vars=env_names,
        capabilities=capabilities,
        docs_url=docs_url,
    )


def require_token(platform: str, *env_names: str) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    token = first_env(*env_names)
    if not token:
        primary = env_names[0] if env_names else "API_KEY"
        return None, {
            "platform": platform,
            "status": "configuration_required",
            "ok": False,
            "message": f"Set {primary}.",
        }
    return token, None


def http_get_json(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    params: Optional[dict[str, Any]] = None,
    timeout: float = 12,
) -> tuple[Optional[requests.Response], Optional[dict[str, Any]], Optional[str]]:
    try:
        resp = requests.get(url, headers=headers or {}, params=params, timeout=timeout)
        data: Optional[dict[str, Any]] = None
        ctype = (resp.headers.get("content-type") or "").lower()
        if "json" in ctype:
            try:
                parsed = resp.json()
                data = parsed if isinstance(parsed, dict) else {"data": parsed}
            except Exception:
                data = None
        return resp, data, None
    except Exception as exc:
        return None, None, str(exc)[:200]


def http_post_json(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    json_body: Optional[dict[str, Any]] = None,
    timeout: float = 30,
) -> tuple[Optional[requests.Response], Optional[dict[str, Any]], Optional[str]]:
    try:
        resp = requests.post(url, headers=headers or {}, json=json_body or {}, timeout=timeout)
        data: Optional[dict[str, Any]] = None
        ctype = (resp.headers.get("content-type") or "").lower()
        if "json" in ctype:
            try:
                parsed = resp.json()
                data = parsed if isinstance(parsed, dict) else {"data": parsed}
            except Exception:
                data = None
        return resp, data, None
    except Exception as exc:
        return None, None, str(exc)[:200]
