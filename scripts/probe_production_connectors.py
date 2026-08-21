"""Live probe script for production connectors — redacts secrets in output."""
from __future__ import annotations

import os
from pathlib import Path


def load_env() -> None:
    p = Path(__file__).resolve().parents[1] / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def redact(v: str) -> str:
    v = (v or "").strip()
    if len(v) < 10:
        return "SET" if v else "EMPTY"
    return f"{v[:4]}...{v[-4:]}"


def main() -> None:
    load_env()
    keys = [
        "VERIDIQ_TAVILY_API_KEY",
        "VERIDIQ_SERPAPI_API_KEY",
        "VERIDIQ_EXA_API_KEY",
        "VERIDIQ_NEWSAPI_KEY",
        "VERIDIQ_COINGECKO_API_KEY",
        "VERIDIQ_CMC_API_KEY",
        "VERIDIQ_GITHUB_TOKEN",
        "VERIDIQ_NOTION_TOKEN",
        "VERIDIQ_SUPABASE_URL",
        "VERIDIQ_CLERK_PUBLISHABLE_KEY",
        "VERIDIQ_CLERK_SECRET_KEY",
        "VERIDIQ_FIREBASE_PROJECT",
        "VERIDIQ_STRIPE_KEY_RAW",
        "VERIDIQ_TELEGRAM_BOT_TOKEN",
    ]
    print("ENV (redacted):")
    for k in keys:
        print(f"  {k}={redact(os.getenv(k, ''))}")
    print(
        "  VERIDIQ_SUPABASE_ANON_KEY=",
        "SET" if os.getenv("VERIDIQ_SUPABASE_ANON_KEY") else "MISSING (expected)",
    )

    from veridiq.connectors import news_connector
    from veridiq.integrations import (
        ai_gateway,
        clerk_conn as clerk,
        exa,
        firebase_conn as firebase,
        github,
        notion,
        serpapi,
        stripe_conn as stripe,
        supabase_conn as supabase,
        tavily,
    )
    from veridiq.market.data import market_connectors_status, market_overview
    from veridiq.research.multi_search import multi_search

    probes: dict = {}
    for name, fn in [
        ("tavily", tavily.test_connection),
        ("serpapi", serpapi.test_connection),
        ("exa", exa.test_connection),
        ("notion", notion.test_connection),
        ("github", github.test_connection),
        ("clerk", clerk.test_connection),
        ("supabase", supabase.test_connection),
        ("stripe", stripe.test_connection),
        ("firebase", firebase.test_connection),
        ("ai_gateway", ai_gateway.test_connection),
    ]:
        try:
            r = fn()
            probes[name] = {"status": r.get("status"), "message": (r.get("message") or "")[:160]}
        except Exception as e:
            probes[name] = {"status": "error", "message": str(e)[:160]}

    news = news_connector()
    probes["newsapi"] = {
        "status": news.get("status"),
        "message": (news.get("message") or f"count={news.get('count')}")[:160],
    }
    mkt = market_connectors_status()
    probes["coingecko"] = {
        "status": mkt["coingecko"].get("status"),
        "message": (mkt["coingecko"].get("note") or "")[:160],
    }
    probes["cmc"] = {
        "status": mkt["coinmarketcap"].get("status"),
        "message": (mkt["coinmarketcap"].get("message") or "configured")[:160],
    }
    try:
        ov = market_overview(per_page=3, log=False)
        probes["coingecko_live"] = {"status": ov.get("status"), "message": f"assets={ov.get('count')}"}
    except Exception as e:
        probes["coingecko_live"] = {"status": "error", "message": str(e)[:120]}

    ms = multi_search(query="AI agents market", max_results_per_provider=2)
    probes["multi_search"] = {
        "status": ms.get("status"),
        "message": (ms.get("message") or "")[:160],
        "providers": ms.get("providers_used"),
        "count": ms.get("count"),
    }

    print("PROBES:")
    for k, v in probes.items():
        extra = ""
        if "providers" in v:
            extra = f" providers={v.get('providers')} count={v.get('count')}"
        print(f"  {k}: {v['status']} — {v.get('message', '')}{extra}")


if __name__ == "__main__":
    main()
