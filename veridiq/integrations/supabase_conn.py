"""Supabase — REST health/status (anon key required for real calls)."""

from __future__ import annotations

from typing import Any

from veridiq.integrations.base import first_env, status_shape
from veridiq.integrations.llm._common import http_get_json

PLATFORM = "supabase"
DISPLAY = "Supabase"
CATEGORY = "data"
ENV_VARS = ("VERIDIQ_SUPABASE_URL", "VERIDIQ_SUPABASE_ANON_KEY")
CAPABILITIES = ["rest_health", "rest_get"]
DOCS = "https://supabase.com/docs/guides/api"


def _url() -> str | None:
    raw = first_env("VERIDIQ_SUPABASE_URL", "SUPABASE_URL")
    return (raw or "").rstrip("/") or None


def _anon() -> str | None:
    return first_env("VERIDIQ_SUPABASE_ANON_KEY", "SUPABASE_ANON_KEY", "SUPABASE_KEY")


def status() -> dict[str, Any]:
    url = _url()
    anon = _anon()
    if not url:
        return status_shape(
            PLATFORM,
            DISPLAY,
            CATEGORY,
            status="configuration_required",
            configured=False,
            message="Set VERIDIQ_SUPABASE_URL and VERIDIQ_SUPABASE_ANON_KEY for Supabase REST.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    if not anon:
        return status_shape(
            PLATFORM,
            DISPLAY,
            CATEGORY,
            status="configuration_required",
            configured=False,
            message="VERIDIQ_SUPABASE_URL is set but VERIDIQ_SUPABASE_ANON_KEY is missing — required for REST calls.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
            extra={"project_url_set": True, "anon_key_set": False},
        )
    return status_shape(
        PLATFORM,
        DISPLAY,
        CATEGORY,
        status="configured",
        configured=True,
        message="Supabase URL + anon key present — use /test for REST health.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
        extra={"project_url_set": True, "anon_key_set": True},
    )


def test_connection() -> dict[str, Any]:
    url = _url()
    anon = _anon()
    if not url:
        return {
            "platform": PLATFORM,
            "status": "configuration_required",
            "ok": False,
            "message": "Set VERIDIQ_SUPABASE_URL.",
        }
    if not anon:
        return {
            "platform": PLATFORM,
            "status": "configuration_required",
            "ok": False,
            "message": "Set VERIDIQ_SUPABASE_ANON_KEY (do not invent). URL alone is insufficient for authenticated REST.",
            "project_url_set": True,
        }
    headers = {
        "apikey": anon,
        "Authorization": f"Bearer {anon}",
        "Accept": "application/json",
    }
    # PostgREST root / health-ish: GET /rest/v1/ with Prefer returns schema hint or empty
    resp, _data, exc = http_get_json(f"{url}/rest/v1/", headers=headers, timeout=12)
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    # 200 or 401/404 with OpenAPI can still prove reachability; treat 2xx as ok
    if 200 <= resp.status_code < 300:
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "message": "Supabase REST endpoint reachable with anon key.",
        }
    if resp.status_code in {401, 403}:
        return {
            "platform": PLATFORM,
            "status": "error",
            "ok": False,
            "api_response_status": resp.status_code,
            "message": "Supabase rejected anon key (auth error).",
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": f"Supabase REST HTTP {resp.status_code}.",
    }


def rest_health(**_kwargs: Any) -> dict[str, Any]:
    """Minimal action: same as test_connection, for platform_api callers."""
    return test_connection()
