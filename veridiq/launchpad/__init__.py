"""VERIDIQ Token Launchpad — live market feed + VERIDIQ launch pipeline.

Uses official public market APIs (CoinGecko) for trending/charts and the
existing crypto_launchpad + deployed_contracts store for VERIDIQ-originated
launches. Architecture allows future official ecosystem SDKs without replacing
this surface.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Optional

from database import initialize_database, list_deployed_contracts
from veridiq.market.data import coin_history, market_overview

# Lightweight in-process cache so the Launchpad UI can poll without hammering CoinGecko.
_CACHE: dict[str, Any] = {"at": 0.0, "data": None}
_CACHE_TTL = 20.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _cached_markets(per_page: int = 40) -> dict[str, Any]:
    now = time.time()
    if _CACHE["data"] is not None and (now - _CACHE["at"]) < _CACHE_TTL:
        return _CACHE["data"]
    data = market_overview(per_page=per_page, log=False)
    _CACHE["at"] = now
    _CACHE["data"] = data
    return data


def launchpad_snapshot(
    *,
    q: Optional[str] = None,
    sort: str = "trending",
    network: Optional[str] = None,
) -> dict[str, Any]:
    """Pump.fun-inspired board built from live CoinGecko + VERIDIQ launches."""
    initialize_database()
    markets = _cached_markets(40)
    assets = list(markets.get("assets") or [])
    source_status = markets.get("status") or "ok"

    # Trending = highest |24h change| among liquid assets; new = lowest market cap in set
    def _chg(a: dict[str, Any]) -> float:
        return float(a.get("change_24h_pct") if a.get("change_24h_pct") is not None else a.get("price_change_24h") or 0)

    trending = sorted(assets, key=lambda a: abs(_chg(a)), reverse=True)[:12]
    new_launches_mkt = sorted(assets, key=lambda a: float(a.get("market_cap") or 0) or 1e18)[:12]

    veridiq_launches = []
    for c in list_deployed_contracts():
        if network and str(c.get("network") or "").lower() != network.lower():
            continue
        veridiq_launches.append(
            {
                "id": f"vq-{c.get('id')}",
                "source": "veridiq",
                "name": c.get("token_name"),
                "symbol": c.get("token_symbol"),
                "network": c.get("network"),
                "contract_address": c.get("contract_address"),
                "tx_hash": c.get("tx_hash"),
                "launched_at": c.get("deployed_at") or c.get("created_at"),
                "status": "launched",
            }
        )

    # Synthetic buy/sell stream derived from live price ticks (honest: labeled as market ticks, not DEX fills)
    buy_sell_stream = []
    for a in assets[:25]:
        ch = _chg(a)
        side = "buy" if ch >= 0 else "sell"
        buy_sell_stream.append(
            {
                "side": side,
                "symbol": a.get("symbol"),
                "name": a.get("name"),
                "price": a.get("price"),
                "change_24h": ch,
                "volume_24h": a.get("volume_24h"),
                "kind": "market_tick",
                "note": "Derived from live CoinGecko 24h change — not a DEX fill feed.",
                "timestamp": _utc_now(),
            }
        )

    # Wallet activity: VERIDIQ launch addresses as observed wallets
    wallet_activity = [
        {
            "wallet": v.get("contract_address"),
            "action": "token_launch",
            "symbol": v.get("symbol"),
            "network": v.get("network"),
            "tx_hash": v.get("tx_hash"),
            "timestamp": v.get("launched_at"),
            "source": "veridiq",
        }
        for v in veridiq_launches[:30]
    ]

    tokens = []
    for a in assets:
        tokens.append(
            {
                "id": a.get("id"),
                "source": "coingecko",
                "name": a.get("name"),
                "symbol": a.get("symbol"),
                "price": a.get("price"),
                "market_cap": a.get("market_cap"),
                "volume_24h": a.get("volume_24h"),
                "change_24h": _chg(a),
                "sparkline": a.get("sparkline") or [],
                "image": a.get("image"),
            }
        )

    if q:
        ql = q.lower().strip()
        tokens = [t for t in tokens if ql in str(t.get("symbol") or "").lower() or ql in str(t.get("name") or "").lower()]
        veridiq_launches = [
            v
            for v in veridiq_launches
            if ql in str(v.get("symbol") or "").lower() or ql in str(v.get("name") or "").lower()
        ]

    if sort == "volume":
        tokens = sorted(tokens, key=lambda t: float(t.get("volume_24h") or 0), reverse=True)
    elif sort == "gainers":
        tokens = sorted(tokens, key=lambda t: float(t.get("change_24h") or 0), reverse=True)
    elif sort == "losers":
        tokens = sorted(tokens, key=lambda t: float(t.get("change_24h") or 0))
    else:  # trending
        tokens = sorted(tokens, key=lambda t: abs(float(t.get("change_24h") or 0)), reverse=True)

    analytics = {
        "market_assets": len(assets),
        "veridiq_launches": len(veridiq_launches),
        "avg_change_24h": round(sum(_chg(a) for a in assets) / max(1, len(assets)), 4) if assets else None,
        "total_volume_24h": sum(float(a.get("volume_24h") or 0) for a in assets),
        "feed_source": "coingecko_public" if source_status == "ok" else source_status,
        "launch_pipeline": "crypto_launchpad.compile_audit_and_deploy",
        "future_ecosystems": ["official_pump_fun_api_when_available", "base", "solana", "ethereum"],
    }

    return {
        "status": source_status,
        "tokens": tokens,
        "trending": [
            {
                "id": t.get("id"),
                "symbol": t.get("symbol"),
                "name": t.get("name"),
                "change_24h": _chg(t),
                "price": t.get("price"),
            }
            for t in trending
        ],
        "new_launches": veridiq_launches[:20]
        + [
            {
                "id": a.get("id"),
                "source": "coingecko",
                "name": a.get("name"),
                "symbol": a.get("symbol"),
                "price": a.get("price"),
                "market_cap": a.get("market_cap"),
                "status": "listed",
            }
            for a in new_launches_mkt[:10]
        ],
        "veridiq_launches": veridiq_launches,
        "transactions": buy_sell_stream[:40],
        "buy_sell_stream": buy_sell_stream[:40],
        "wallet_activity": wallet_activity,
        "analytics": analytics,
        "filters": {"q": q, "sort": sort, "network": network},
        "timestamp": _utc_now(),
    }


def launchpad_token_chart(coin_id: str, *, days: int = 1) -> dict[str, Any]:
    hist = coin_history(coin_id, days=days, log=False)
    return {
        "coin_id": coin_id,
        "days": days,
        "history": hist,
        "timestamp": _utc_now(),
    }


def launch_token(
    *,
    token_name: str,
    token_symbol: str,
    network: str = "Base",
    initial_supply: int = 1_000_000,
    decimals: int = 18,
) -> dict[str, Any]:
    """VERIDIQ-native launch through existing crypto_launchpad pipeline."""
    from crypto_launchpad import compile_audit_and_deploy

    result = compile_audit_and_deploy(
        token_name=token_name,
        token_symbol=token_symbol,
        network=network,
        initial_supply=initial_supply,
        decimals=decimals,
    )
    result["launchpad"] = True
    result["timestamp"] = _utc_now()
    return result


def token_fingerprint(symbol: str, network: str) -> str:
    return hashlib.sha256(f"{symbol}|{network}".encode()).hexdigest()[:16]
