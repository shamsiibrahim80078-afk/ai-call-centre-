"""Official market data connectors — CoinGecko public API (no key), optional CMC."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

import requests

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
COINGECKO_PRO_BASE = "https://pro-api.coingecko.com/api/v3"


def _coingecko_key() -> Optional[str]:
    return (
        os.getenv("VERIDIQ_COINGECKO_API_KEY")
        or os.getenv("VERIDIQ_CG_DEMO_API_KEY")
        or os.getenv("COINGECKO_API_KEY")
        or None
    )


def _coingecko_request(path: str, *, params: Optional[dict[str, Any]] = None, timeout: float = 8):
    """GET CoinGecko with optional demo/pro API key headers when configured."""
    key = _coingecko_key()
    headers: dict[str, str] = {}
    base = COINGECKO_BASE
    if key:
        # Demo keys (CG-...) use x-cg-demo-api-key on the public host;
        # Pro keys use pro-api + x-cg-pro-api-key.
        if key.startswith("CG-"):
            headers["x-cg-demo-api-key"] = key
        else:
            headers["x-cg-pro-api-key"] = key
            base = COINGECKO_PRO_BASE
    return requests.get(f"{base}{path}", params=params or {}, headers=headers, timeout=timeout)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _log_activity(
    *,
    platform: str,
    task: str,
    agent_type: Optional[str] = None,
    job_id: Optional[str] = None,
    completion_status: str,
    api_response_status: Optional[str] = None,
    recent_activity: Optional[str] = None,
    errors: Optional[str] = None,
) -> None:
    if not agent_type and not job_id:
        return  # plain status/dashboard reads never populate the live activity feed
    try:
        from veridiq.integrations.activity import global_platform_activity

        global_platform_activity.record(
            platform=platform,
            task=task,
            agent_type=agent_type,
            job_id=job_id,
            workflow_stage="market_data_call",
            completion_status=completion_status,
            api_response_status=api_response_status,
            recent_activity=recent_activity,
            errors=errors,
        )
    except Exception:
        pass


def market_overview(
    vs_currency: str = "usd",
    per_page: int = 20,
    *,
    agent_type: Optional[str] = None,
    job_id: Optional[str] = None,
    log: bool = True,
) -> dict[str, Any]:
    """Live market snapshot via CoinGecko (public or keyed demo/pro when configured)."""
    try:
        resp = _coingecko_request(
            "/coins/markets",
            params={
                "vs_currency": vs_currency,
                "order": "market_cap_desc",
                "per_page": per_page,
                "page": 1,
                "sparkline": "true",
                "price_change_percentage": "24h",
            },
            timeout=8,
        )
        resp.raise_for_status()
        rows = resp.json() or []
        assets = [
            {
                "id": r.get("id"),
                "symbol": (r.get("symbol") or "").upper(),
                "name": r.get("name"),
                "price": r.get("current_price"),
                "market_cap": r.get("market_cap"),
                "volume_24h": r.get("total_volume"),
                "change_24h_pct": r.get("price_change_percentage_24h"),
                "sparkline": ((r.get("sparkline_in_7d") or {}).get("price") or [])[-48:],
                "image": r.get("image"),
            }
            for r in rows
        ]
        if log:
            _log_activity(
                platform="market_coingecko",
                task="Fetch CoinGecko markets overview",
                agent_type=agent_type,
                job_id=job_id,
                completion_status="completed",
                api_response_status=str(resp.status_code),
                recent_activity=f"Retrieved {len(assets)} live assets from CoinGecko.",
            )
        return {
            "provider": "CoinGecko",
            "status": "ok",
            "vs_currency": vs_currency,
            "count": len(assets),
            "assets": assets,
            "heatmap": [
                {
                    "symbol": a["symbol"],
                    "change_24h_pct": a["change_24h_pct"],
                    "market_cap": a["market_cap"],
                }
                for a in assets
            ],
            "dominance": market_dominance(assets),
            "volatility": volatility_summary(assets),
            "liquidity": liquidity_summary(assets),
            "binance_public": binance_public_tickers(agent_type=agent_type, job_id=job_id, log=log),
            "disclaimer": "Market data is informational. Analyses are probabilistic, not financial advice or guarantees.",
            "timestamp": _utc_now(),
        }
    except Exception as exc:
        if log:
            _log_activity(
                platform="market_coingecko",
                task="Fetch CoinGecko markets overview",
                agent_type=agent_type,
                job_id=job_id,
                completion_status="failed",
                api_response_status="error",
                recent_activity="CoinGecko call failed.",
                errors=str(exc)[:200],
            )
        return {
            "provider": "CoinGecko",
            "status": "unavailable",
            "message": f"Official CoinGecko API unreachable ({type(exc).__name__}). No fabricated prices.",
            "assets": [],
            "heatmap": [],
            "count": 0,
            "timestamp": _utc_now(),
        }


def coin_history(
    coin_id: str = "bitcoin",
    days: int = 7,
    vs_currency: str = "usd",
    *,
    agent_type: Optional[str] = None,
    job_id: Optional[str] = None,
    log: bool = True,
) -> dict[str, Any]:
    try:
        resp = _coingecko_request(
            f"/coins/{coin_id}/market_chart",
            params={"vs_currency": vs_currency, "days": days},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        prices = data.get("prices") or []
        if log:
            _log_activity(
                platform="market_coingecko",
                task=f"Fetch {coin_id} price history",
                agent_type=agent_type,
                job_id=job_id,
                completion_status="completed",
                api_response_status=str(resp.status_code),
                recent_activity=f"Retrieved {len(prices)} price points for {coin_id}.",
            )
        return {
            "provider": "CoinGecko",
            "status": "ok",
            "coin_id": coin_id,
            "days": days,
            "prices": [{"t": p[0], "price": p[1]} for p in prices[-120:]],
            "volumes": [{"t": v[0], "volume": v[1]} for v in (data.get("total_volumes") or [])[-120:]],
            "timestamp": _utc_now(),
        }
    except Exception as exc:
        if log:
            _log_activity(
                platform="market_coingecko",
                task=f"Fetch {coin_id} price history",
                agent_type=agent_type,
                job_id=job_id,
                completion_status="failed",
                api_response_status="error",
                recent_activity="CoinGecko history call failed.",
                errors=str(exc)[:200],
            )
        return {
            "provider": "CoinGecko",
            "status": "unavailable",
            "message": str(exc)[:200],
            "prices": [],
            "volumes": [],
            "timestamp": _utc_now(),
        }


def simple_indicators(prices: list[float]) -> dict[str, Any]:
    if len(prices) < 5:
        return {"status": "insufficient_data", "sma_short": None, "sma_long": None, "momentum": None}
    short = sum(prices[-5:]) / 5
    long_n = min(20, len(prices))
    long = sum(prices[-long_n:]) / long_n
    momentum = ((prices[-1] - prices[-5]) / prices[-5]) if prices[-5] else None
    return {
        "status": "ok",
        "sma_short": round(short, 6),
        "sma_long": round(long, 6),
        "momentum": round(momentum, 6) if momentum is not None else None,
        "trend_bias": "up" if short > long else "down",
    }


def binance_public_tickers(
    symbols: Optional[list[str]] = None,
    *,
    agent_type: Optional[str] = None,
    job_id: Optional[str] = None,
    log: bool = True,
) -> dict[str, Any]:
    """Binance public 24hr ticker — no API key required."""
    try:
        resp = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=8)
        resp.raise_for_status()
        rows = resp.json() or []
        want = {s.upper() for s in (symbols or ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"])}
        picked = []
        for r in rows:
            sym = (r.get("symbol") or "").upper()
            if sym in want:
                picked.append(
                    {
                        "symbol": sym,
                        "price": float(r.get("lastPrice") or 0),
                        "volume": float(r.get("volume") or 0),
                        "quote_volume": float(r.get("quoteVolume") or 0),
                        "change_24h_pct": float(r.get("priceChangePercent") or 0),
                        "high": float(r.get("highPrice") or 0),
                        "low": float(r.get("lowPrice") or 0),
                    }
                )
        if log:
            _log_activity(
                platform="market_binance",
                task="Fetch Binance public 24hr ticker",
                agent_type=agent_type,
                job_id=job_id,
                completion_status="completed",
                api_response_status=str(resp.status_code),
                recent_activity=f"Retrieved {len(picked)} tickers from Binance public API.",
            )
        return {
            "provider": "Binance",
            "status": "ok",
            "auth": "public",
            "count": len(picked),
            "tickers": picked,
            "timestamp": _utc_now(),
        }
    except Exception as exc:
        if log:
            _log_activity(
                platform="market_binance",
                task="Fetch Binance public 24hr ticker",
                agent_type=agent_type,
                job_id=job_id,
                completion_status="failed",
                api_response_status="error",
                recent_activity="Binance public API call failed.",
                errors=str(exc)[:200],
            )
        return {
            "provider": "Binance",
            "status": "unavailable",
            "message": f"Binance public API unreachable ({type(exc).__name__}). No fabricated tickers.",
            "tickers": [],
            "count": 0,
            "timestamp": _utc_now(),
        }


def market_dominance(assets: list[dict[str, Any]]) -> dict[str, Any]:
    caps = [(a.get("symbol"), float(a.get("market_cap") or 0)) for a in assets]
    total = sum(c for _, c in caps) or 0.0
    if not total:
        return {"status": "insufficient_data", "items": []}
    items = [
        {"symbol": s, "dominance_pct": round((c / total) * 100, 3)}
        for s, c in caps
        if s
    ]
    return {"status": "ok", "items": items[:12], "basis": "share of returned CoinGecko sample market caps"}


def volatility_summary(assets: list[dict[str, Any]]) -> dict[str, Any]:
    moves = [abs(float(a.get("change_24h_pct") or 0)) for a in assets]
    if not moves:
        return {"status": "insufficient_data"}
    avg = sum(moves) / len(moves)
    return {
        "status": "ok",
        "avg_abs_change_24h": round(avg, 4),
        "max_abs_change_24h": round(max(moves), 4),
        "sample": len(moves),
    }


def liquidity_summary(assets: list[dict[str, Any]]) -> dict[str, Any]:
    vols = [float(a.get("volume_24h") or 0) for a in assets]
    if not vols:
        return {"status": "insufficient_data"}
    return {
        "status": "ok",
        "total_volume_24h": round(sum(vols), 2),
        "median_volume_24h": round(sorted(vols)[len(vols) // 2], 2),
        "sample": len(vols),
    }


def coinmarketcap_status() -> dict[str, Any]:
    key = os.getenv("VERIDIQ_CMC_API_KEY") or os.getenv("COINMARKETCAP_API_KEY")
    if not key:
        return {
            "provider": "CoinMarketCap",
            "status": "configuration_required",
            "message": "Set VERIDIQ_CMC_API_KEY for CoinMarketCap listings. CoinGecko remains available without a key.",
        }
    return {"provider": "CoinMarketCap", "status": "configured", "ready": True}


def market_connectors_status() -> dict[str, Any]:
    binance = binance_public_tickers(log=False)
    cg_key = _coingecko_key()
    cg_note = (
        "CoinGecko demo/pro API key present — authenticated markets/history."
        if cg_key
        else "No API key required for basic markets endpoints (public). Optional: VERIDIQ_COINGECKO_API_KEY."
    )
    return {
        "coingecko": {
            "status": "ok",
            "auth": "keyed" if cg_key else "public",
            "configured": True,
            "note": cg_note,
            "env_vars": ["VERIDIQ_COINGECKO_API_KEY", "VERIDIQ_CG_DEMO_API_KEY"],
        },
        "binance": {
            "status": binance.get("status"),
            "auth": "public",
            "message": binance.get("message"),
            "note": "Public 24hr ticker requires no key. Authenticated endpoints need VERIDIQ_BINANCE_API_KEY / SECRET.",
        },
        "coinmarketcap": coinmarketcap_status(),
        "mexc": {
            "status": "configuration_required",
            "message": "Set VERIDIQ_MEXC_API_KEY when enabling MEXC official authenticated APIs.",
        },
        "policy": "Official APIs only. Missing credentials return configuration_required — never invented prices.",
    }
