"""Production connectors + AI gateway + multi_search — focused wiring tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Load local .env for live probes (never assert on secret values).
_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
if _ENV_PATH.exists():
    for line in _ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k = k.strip()
        if k and k not in os.environ:
            os.environ[k] = v.strip().strip('"').strip("'")

from veridiq.integrations import (  # noqa: E402
    ai_gateway,
    clerk_conn as clerk,
    exa,
    firebase_conn as firebase,
    notion,
    serpapi,
    stripe_conn as stripe,
    supabase_conn as supabase,
    tavily,
)
from veridiq.integrations.platform_api import MODULE_ALIASES, PLATFORM_ACTIONS, dispatch, list_platforms  # noqa: E402
from veridiq.integrations.registry import TEST_FUNCS, all_integrations  # noqa: E402
from veridiq.research.multi_search import multi_search  # noqa: E402
from veridiq.sdk.tools import execute_tool, list_tools  # noqa: E402

NEW_PLATFORMS = [
    "tavily",
    "serpapi",
    "exa",
    "notion",
    "supabase",
    "clerk",
    "stripe",
    "firebase",
    "ai_gateway",
]

ENV_KEYS = [
    "VERIDIQ_TAVILY_API_KEY",
    "TAVILY_API_KEY",
    "VERIDIQ_SERPAPI_API_KEY",
    "SERPAPI_API_KEY",
    "VERIDIQ_EXA_API_KEY",
    "EXA_API_KEY",
    "VERIDIQ_NOTION_TOKEN",
    "NOTION_TOKEN",
    "VERIDIQ_SUPABASE_URL",
    "VERIDIQ_SUPABASE_ANON_KEY",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "VERIDIQ_CLERK_PUBLISHABLE_KEY",
    "VERIDIQ_CLERK_SECRET_KEY",
    "VITE_CLERK_PUBLISHABLE_KEY",
    "CLERK_PUBLISHABLE_KEY",
    "CLERK_SECRET_KEY",
    "VERIDIQ_STRIPE_SECRET_KEY",
    "VERIDIQ_STRIPE_PUBLISHABLE_KEY",
    "VERIDIQ_STRIPE_KEY_RAW",
    "VERIDIQ_FIREBASE_PROJECT",
    "VERIDIQ_FIREBASE_SERVICE_ACCOUNT_JSON",
    "GOOGLE_APPLICATION_CREDENTIALS",
]


@pytest.fixture
def clear_connector_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_status_configuration_required_without_keys(clear_connector_env):
    assert tavily.status()["status"] == "configuration_required"
    assert serpapi.status()["status"] == "configuration_required"
    assert exa.status()["status"] == "configuration_required"
    assert notion.status()["status"] == "configuration_required"
    assert supabase.status()["status"] == "configuration_required"
    assert clerk.status()["status"] == "configuration_required"
    assert stripe.status()["status"] == "configuration_required"
    assert firebase.status()["status"] == "configuration_required"


def test_stripe_raw_invalid_shape(clear_connector_env, monkeypatch):
    monkeypatch.setenv("VERIDIQ_STRIPE_KEY_RAW", "mk_1U18ZxIpJmsHi0JAdR9Slz3M")
    st = stripe.status()
    assert st["status"] == "configuration_required"
    assert st.get("valid_key_shape") is False
    probe = stripe.test_connection()
    assert probe["status"] == "configuration_required"


def test_supabase_url_without_anon(clear_connector_env, monkeypatch):
    monkeypatch.setenv("VERIDIQ_SUPABASE_URL", "https://example.supabase.co")
    st = supabase.status()
    assert st["status"] == "configuration_required"
    assert st.get("anon_key_set") is False
    probe = supabase.test_connection()
    assert probe["status"] == "configuration_required"


def test_firebase_project_only(clear_connector_env, monkeypatch):
    monkeypatch.setenv("VERIDIQ_FIREBASE_PROJECT", "veridiq-f122b")
    st = firebase.status()
    assert st["status"] == "configuration_required"
    assert "service account" in (st.get("message") or "").lower()


def test_clerk_primary_ui_with_fastapi_jwt_bridge(clear_connector_env, monkeypatch):
    """Clerk owns browser sign-in/up; FastAPI still issues its own JWT after /auth/clerk/sync."""
    monkeypatch.setenv("VERIDIQ_CLERK_PUBLISHABLE_KEY", "pk_test_xxxxx")
    monkeypatch.setenv("VERIDIQ_CLERK_SECRET_KEY", "sk_test_xxxxx")
    st = clerk.status()
    assert st["configured"] is True
    assert st.get("auth_policy") == "clerk_ui_plus_fastapi_jwt"
    assert st.get("key_mode") == "test"
    assert st.get("production_ready") is False
    stub = clerk.optional_jwt_verify_stub(token="a.b.c")
    assert stub.get("verified") is False
    assert stub.get("full_jwks_verification") is False


def test_registry_and_platform_api_wire_new_platforms():
    for p in NEW_PLATFORMS:
        assert p in PLATFORM_ACTIONS
        assert p in TEST_FUNCS
        assert set(PLATFORM_ACTIONS[p].keys()) >= {"status", "test"}
    assert MODULE_ALIASES["supabase"] == "supabase_conn"
    assert MODULE_ALIASES["clerk"] == "clerk_conn"
    assert MODULE_ALIASES["stripe"] == "stripe_conn"
    assert MODULE_ALIASES["firebase"] == "firebase_conn"
    listed = {row["platform"] for row in list_platforms()["platforms"]}
    assert set(NEW_PLATFORMS).issubset(listed)
    data = all_integrations(force_refresh=True)
    platforms = {i["platform"] for i in data["integrations"]}
    assert set(NEW_PLATFORMS).issubset(platforms)


def test_sdk_tools_include_gateway_and_research():
    tools = list_tools()
    assert "ai_gateway.generate" in tools
    assert "ai_gateway.status" in tools
    assert "research.multi_search" in tools
    assert "tavily.search" in tools


def test_multi_search_configuration_required(clear_connector_env):
    result = multi_search(query="test")
    assert result["status"] == "configuration_required"
    assert result["results"] == []
    assert result["ok"] is False


def test_ai_gateway_status_shape():
    st = ai_gateway.status()
    assert st["platform"] == "ai_gateway"
    assert "task_types" in st or st.get("configured") in {True, False}
    assert st["category"] == "ai"


@pytest.mark.live
def test_live_connector_probes():
    """Live network probes — resilient statuses only; secrets never logged."""
    results = {}
    for name, fn in [
        ("tavily", tavily.test_connection),
        ("serpapi", serpapi.test_connection),
        ("exa", exa.test_connection),
        ("notion", notion.test_connection),
        ("github", __import__("veridiq.integrations.github", fromlist=["test_connection"]).test_connection),
        ("clerk", clerk.test_connection),
        ("supabase", supabase.test_connection),
        ("stripe", stripe.test_connection),
        ("firebase", firebase.test_connection),
        ("ai_gateway", ai_gateway.test_connection),
    ]:
        try:
            results[name] = fn()
        except Exception as exc:
            results[name] = {"status": "error", "message": str(exc)[:120]}

    for name, result in results.items():
        assert result.get("status") in {
            "ok",
            "error",
            "configuration_required",
            "configured",
        }, f"{name} unexpected status: {result.get('status')}"
        msg = str(result.get("message") or "")
        # Never leak full secrets in messages (skip non-secret ids/urls)
        skip_leak_keys = {
            "VERIDIQ_SUPABASE_URL",
            "SUPABASE_URL",
            "VERIDIQ_FIREBASE_PROJECT",
            "VERIDIQ_CLERK_PUBLISHABLE_KEY",
            "VERIDIQ_STRIPE_PUBLISHABLE_KEY",
        }
        for key in ENV_KEYS:
            if key in skip_leak_keys:
                continue
            val = os.environ.get(key)
            if val and len(val) > 12 and not val.startswith("pk_") and "http" not in val.lower():
                assert val not in msg, f"{name} leaked env value"

    assert {k: v.get("status") for k, v in results.items()}


@pytest.mark.live
def test_live_dispatch_tavily_status():
    result = dispatch("tavily", "status")
    assert result.get("platform") == "tavily"
    assert result.get("status") in {"configured", "configuration_required", "ok"}


@pytest.mark.live
def test_live_multi_search_when_configured():
    result = multi_search(query="bitcoin price", max_results_per_provider=2)
    assert result.get("status") in {"ok", "error", "configuration_required"}
    if result.get("status") == "ok":
        assert isinstance(result.get("results"), list)
        assert result.get("providers_used")


@pytest.mark.live
def test_live_execute_tool_ai_gateway_status():
    result = execute_tool("ai_gateway.status")
    assert result.get("platform") == "ai_gateway" or result.get("tool") == "ai_gateway.status"
    assert result.get("status") in {"configured", "configuration_required", "ok", "error"}
