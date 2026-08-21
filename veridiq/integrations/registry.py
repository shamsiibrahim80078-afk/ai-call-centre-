"""Modular platform integration registry — official APIs only, no scraping, no fabricated status."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from veridiq.integrations import (
    ai_gateway,
    browser_playwright,
    canva,
    clerk_conn as clerk,
    crm,
    discord,
    email_smtp,
    exa,
    fal_ai,
    firebase_conn as firebase,
    github,
    gmail,
    google_calendar,
    google_drive,
    instagram,
    linkedin,
    local_video,
    marketing,
    notion,
    serpapi,
    slack,
    stripe_conn as stripe,
    supabase_conn as supabase,
    telegram,
    tavily,
    threads,
    twilio_calling,
    video_render,
    webrtc_signaling,
    whatsapp,
    x_twitter,
)
from veridiq.integrations.activity import global_platform_activity
from veridiq.integrations.llm import (
    assemblyai,
    cohere,
    deepgram,
    fireworks,
    google_ai,
    groq,
    huggingface,
    mistral,
    openrouter,
    together,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _social_messaging_entries() -> list[dict[str, Any]]:
    return [
        linkedin.status(),
        x_twitter.status(),
        instagram.status(),
        threads.status(),
        telegram.status(),
        whatsapp.status(),
        email_smtp.status(),
        gmail.status(),
        google_calendar.status(),
        google_drive.status(),
        github.status(),
        notion.status(),
        slack.status(),
        discord.status(),
        browser_playwright.status(),
        webrtc_signaling.status(),
        crm.status(),
        marketing.status(),
        twilio_calling.status(),
        canva.status(),
        video_render.status(),
        fal_ai.status(),
        local_video.status(),
        tavily.status(),
        serpapi.status(),
        exa.status(),
        supabase.status(),
        clerk.status(),
        stripe.status(),
        firebase.status(),
        ai_gateway.status(),
    ]


def _ai_provider_entries() -> list[dict[str, Any]]:
    """LLM + speech providers — official HTTP APIs only."""
    return [
        google_ai.status(),
        groq.status(),
        openrouter.status(),
        huggingface.status(),
        cohere.status(),
        mistral.status(),
        together.status(),
        fireworks.status(),
        assemblyai.status(),
        deepgram.status(),
    ]


def _internal_entries() -> list[dict[str, Any]]:
    """Existing connectors wired into the same status board, mapped honestly."""
    from blockchain.integration import global_blockchain
    from veridiq.connectors import jobs_connector, news_connector
    from veridiq.market.data import market_connectors_status
    from veridiq.rag import get_rag

    news = news_connector()
    jobs = jobs_connector()
    market = market_connectors_status()
    rag_status = get_rag().status()
    chain = global_blockchain.status()

    entries: list[dict[str, Any]] = []
    entries.append(
        {
            "platform": "news_newsapi",
            "display_name": "NewsAPI",
            "category": "news",
            "status": news.get("status"),
            "configured": news.get("status") == "ok",
            "message": news.get("message") or f"{news.get('count', 0)} live headlines available.",
            "env_vars": ["VERIDIQ_NEWSAPI_KEY", "NEWS_API_KEY"],
            "capabilities": ["top_headlines"],
            "docs_url": "https://newsapi.org/",
            "timestamp": _utc_now(),
        }
    )
    entries.append(
        {
            "platform": "jobs_remotive",
            "display_name": "Remotive Jobs",
            "category": "jobs",
            "status": "ok" if jobs.get("status") == "ok" else "unavailable",
            "configured": True,
            "message": jobs.get("message") or f"{jobs.get('count', 0)} public listings available.",
            "env_vars": [],
            "capabilities": ["remote_job_listings"],
            "docs_url": "https://remotive.com/api-documentation",
            "timestamp": _utc_now(),
        }
    )
    cg = market.get("coingecko") or {}
    entries.append(
        {
            "platform": "market_coingecko",
            "display_name": "CoinGecko",
            "category": "market",
            "status": cg.get("status", "ok"),
            "configured": True,
            "message": cg.get("note"),
            "env_vars": cg.get("env_vars")
            or ["VERIDIQ_COINGECKO_API_KEY", "VERIDIQ_CG_DEMO_API_KEY"],
            "capabilities": ["markets", "history"],
            "docs_url": "https://www.coingecko.com/en/api",
            "timestamp": _utc_now(),
        }
    )
    bn = market.get("binance") or {}
    entries.append(
        {
            "platform": "market_binance",
            "display_name": "Binance (public)",
            "category": "market",
            "status": bn.get("status", "unavailable"),
            "configured": True,
            "message": bn.get("message") or bn.get("note"),
            "env_vars": ["VERIDIQ_BINANCE_API_KEY", "VERIDIQ_BINANCE_API_SECRET"],
            "capabilities": ["24hr_ticker (public)"],
            "docs_url": "https://binance-docs.github.io/apidocs/",
            "timestamp": _utc_now(),
        }
    )
    cmc = market.get("coinmarketcap") or {}
    entries.append(
        {
            "platform": "market_coinmarketcap",
            "display_name": "CoinMarketCap",
            "category": "market",
            "status": cmc.get("status", "configuration_required"),
            "configured": cmc.get("status") not in {None, "configuration_required"},
            "message": cmc.get("message"),
            "env_vars": ["VERIDIQ_CMC_API_KEY", "COINMARKETCAP_API_KEY"],
            "capabilities": ["listings"],
            "docs_url": "https://coinmarketcap.com/api/",
            "timestamp": _utc_now(),
        }
    )
    entries.append(
        {
            "platform": "rag_qdrant",
            "display_name": "Qdrant RAG / Vector Memory",
            "category": "ai_infra",
            "status": "error" if rag_status.get("backend") == "error" else "ok",
            "configured": True,
            "message": f"Backend: {rag_status.get('backend')}, docs: {rag_status.get('memory_docs')}.",
            "env_vars": [],
            "capabilities": ["evidence_upsert", "semantic_recall"],
            "docs_url": None,
            "timestamp": _utc_now(),
        }
    )
    entries.append(
        {
            "platform": "blockchain",
            "display_name": "Blockchain Attestation",
            "category": "blockchain",
            "status": "configured" if chain.get("rpc_url") else "configuration_required",
            "configured": bool(chain.get("rpc_url")),
            "message": "Attestation readiness only — this endpoint never deploys contracts.",
            "env_vars": ["VERIDIQ_CHAIN_NETWORK", "VERIDIQ_RPC_URL", "VERIDIQ_CONTRACT_TRUTHATTESTATION"],
            "capabilities": ["report_hash_attestation (when configured)"],
            "docs_url": None,
            "timestamp": _utc_now(),
            "detail": chain,
        }
    )
    return entries


# `_internal_entries()` fans out to live upstream connectors (NewsAPI, Remotive
# jobs, Binance public tickers) with multi-second timeouts each. Every poller
# of /workspace, /dashboard-adjacent pages, and /integrations used to trigger
# that whole fan-out synchronously on every single request (observed 4-16s
# latency on /workspace under normal polling). Configuration/connectivity
# status doesn't change second-to-second, so a short TTL cache lets the agent
# roster and integration board load instantly while still refreshing often
# enough to reflect real state changes.
_INTEGRATIONS_CACHE_SEC = float(os.getenv("VERIDIQ_INTEGRATIONS_CACHE_SEC", "20"))
_integrations_cache: dict[str, Any] = {"data": None, "at": 0.0}
_integrations_lock = threading.Lock()
_integrations_refreshing = False


def _refresh_integrations_cache_now() -> dict[str, Any]:
    items = _social_messaging_entries() + _ai_provider_entries() + _internal_entries()
    data = {
        "count": len(items),
        "integrations": items,
        "categories": sorted({i["category"] for i in items}),
        "policy": "Official APIs only. No scraping. Missing credentials return configuration_required — never fabricated activity.",
        "timestamp": _utc_now(),
        "cache_ttl_sec": _INTEGRATIONS_CACHE_SEC,
    }
    with _integrations_lock:
        _integrations_cache["data"] = data
        _integrations_cache["at"] = time.time()
    return data


def all_integrations(*, force_refresh: bool = False) -> dict[str, Any]:
    """Live upstream connector status (NewsAPI, Remotive, Binance, RAG, chain...).

    `_internal_entries()` performs real network calls with multi-second
    timeouts. Serving a poller the *previous* snapshot while refreshing in the
    background (stale-while-revalidate) means /workspace and /integrations
    load instantly on every request except the very first one this process
    ever makes — never blocking on flaky upstream APIs during normal polling.
    """
    now = time.time()
    cached = _integrations_cache["data"]
    if force_refresh:
        return _refresh_integrations_cache_now()
    if cached is None:
        return _refresh_integrations_cache_now()
    if (now - _integrations_cache["at"]) >= _INTEGRATIONS_CACHE_SEC:
        global _integrations_refreshing
        if not _integrations_refreshing:
            _integrations_refreshing = True

            def _bg() -> None:
                global _integrations_refreshing
                try:
                    _refresh_integrations_cache_now()
                finally:
                    _integrations_refreshing = False

            threading.Thread(target=_bg, daemon=True, name="veridiq-integrations-refresh").start()
    return cached


def integration_detail(platform: str) -> Optional[dict[str, Any]]:
    data = all_integrations()
    return next((i for i in data["integrations"] if i["platform"] == platform), None)


TEST_FUNCS: dict[str, Callable[[], dict[str, Any]]] = {
    "linkedin": linkedin.test_connection,
    "x_twitter": x_twitter.test_connection,
    "instagram": instagram.test_connection,
    "threads": threads.test_connection,
    "telegram": telegram.test_connection,
    "whatsapp": whatsapp.test_connection,
    "email": email_smtp.test_connection,
    "gmail": gmail.test_connection,
    "google_calendar": google_calendar.test_connection,
    "google_drive": google_drive.test_connection,
    "github": github.test_connection,
    "notion": notion.test_connection,
    "slack": slack.test_connection,
    "discord": discord.test_connection,
    "browser_playwright": browser_playwright.test_connection,
    "webrtc_signaling": webrtc_signaling.test_connection,
    "crm": crm.test_connection,
    "marketing": marketing.test_connection,
    "ai_calling": twilio_calling.test_connection,
    "canva": canva.test_connection,
    "video_render": video_render.test_connection,
    "fal_ai": fal_ai.test_connection,
    "local_video": local_video.test_connection,
    "tavily": tavily.test_connection,
    "serpapi": serpapi.test_connection,
    "exa": exa.test_connection,
    "supabase": supabase.test_connection,
    "clerk": clerk.test_connection,
    "stripe": stripe.test_connection,
    "firebase": firebase.test_connection,
    "ai_gateway": ai_gateway.test_connection,
    "google_ai": google_ai.test_connection,
    "groq": groq.test_connection,
    "openrouter": openrouter.test_connection,
    "huggingface": huggingface.test_connection,
    "cohere": cohere.test_connection,
    "mistral": mistral.test_connection,
    "together": together.test_connection,
    "fireworks": fireworks.test_connection,
    "assemblyai": assemblyai.test_connection,
    "deepgram": deepgram.test_connection,
}


def test_integration(platform: str) -> dict[str, Any]:
    fn = TEST_FUNCS.get(platform)
    if not fn:
        return {
            "platform": platform,
            "status": "unsupported",
            "message": "No live connectivity test is wired for this platform; status reflects configuration only.",
        }
    result = fn()
    status = result.get("status")
    completion = "completed" if status in {"ok", "configured", "public"} else "configuration_required" if status == "configuration_required" else "failed"
    global_platform_activity.record(
        platform=platform,
        task=f"Live connectivity test for {platform}",
        workflow_stage="integration_test",
        completion_status=completion,
        api_response_status=str(result.get("api_response_status") or status),
        recent_activity=result.get("message") or f"Tested {platform} connectivity.",
        errors=result.get("message") if status == "error" else None,
    )
    return result
