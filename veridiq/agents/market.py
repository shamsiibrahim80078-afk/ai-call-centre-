"""Market Intelligence specialist agents — probabilistic analysis, not guarantees."""

from __future__ import annotations

from typing import Any

from veridiq.agents.base import VeridiqAgent
from veridiq.market.data import coin_history, market_overview, simple_indicators


class MarketResearchAgent(VeridiqAgent):
    agent_type = "market_research"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        overview = payload.get("market_overview") or market_overview(
            per_page=12, agent_type=self.agent_type, job_id=payload.get("job_id")
        )
        assets = overview.get("assets") or []
        top = assets[:5]
        evidence = [
            {
                "symbol": a.get("symbol"),
                "price": a.get("price"),
                "market_cap": a.get("market_cap"),
                "volume_24h": a.get("volume_24h"),
                "source": "CoinGecko",
            }
            for a in top
        ]
        return {
            "summary": f"Reviewed {len(assets)} liquid assets from CoinGecko.",
            "evidence": evidence,
            "sources": ["CoinGecko /coins/markets"],
            "risks": ["Market data can lag; liquidity and venue differences apply."],
            "alternative_scenarios": [
                "Risk-on continuation if majors hold above short SMAs",
                "Risk-off rotation if breadth deteriorates",
            ],
            "disclaimer": "Probabilistic analysis only — not financial advice or a guarantee.",
            "confidence": 0.72 if assets else 0.2,
            "market_overview": overview,
        }


class OnchainAnalysisAgent(VeridiqAgent):
    agent_type = "onchain_analysis"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        # On-chain depth requires provider keys; report readiness honestly.
        return {
            "summary": "On-chain deep scans require configured RPC/indexer credentials.",
            "evidence": [],
            "sources": [],
            "risks": ["Without VERIDIQ_RPC_URL / indexer keys, on-chain claims cannot be verified live."],
            "alternative_scenarios": ["Configure RPC to enable transfer/volume confirmation."],
            "status": "configuration_optional",
            "disclaimer": "Probabilistic analysis only — not a guarantee.",
            "confidence": 0.35,
        }


class NewsCorrelationAgent(VeridiqAgent):
    agent_type = "news_correlation"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = (payload.get("text") or "").lower()
        hints = [w for w in ("bitcoin", " eth", "sec", "etf", "rate", "inflation") if w.strip() in text]
        return {
            "summary": "Correlated request text against common market narrative keywords.",
            "evidence": [{"keyword": h, "note": "present in request"} for h in hints],
            "sources": ["request_text"],
            "risks": ["Keyword correlation is weak evidence without verified headlines."],
            "alternative_scenarios": ["Enable VERIDIQ_NEWSAPI_KEY for stronger news correlation."],
            "disclaimer": "Probabilistic analysis only — not a guarantee.",
            "confidence": 0.55 if hints else 0.4,
        }


class SentimentAnalysisAgent(VeridiqAgent):
    agent_type = "sentiment_analysis"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        overview = payload.get("market_overview") or market_overview(
            per_page=20, agent_type=self.agent_type, job_id=payload.get("job_id")
        )
        assets = overview.get("assets") or []
        ups = sum(1 for a in assets if (a.get("change_24h_pct") or 0) > 0)
        downs = sum(1 for a in assets if (a.get("change_24h_pct") or 0) < 0)
        bias = "constructive" if ups > downs else "cautious" if downs > ups else "mixed"
        return {
            "summary": f"24h breadth sentiment bias: {bias} ({ups} up / {downs} down among sampled assets).",
            "evidence": [{"ups": ups, "downs": downs, "sample": len(assets)}],
            "sources": ["CoinGecko 24h price_change_percentage"],
            "risks": ["Short-window breadth can reverse quickly."],
            "alternative_scenarios": ["Mean-reversion after crowded moves", "Trend continuation if breadth expands"],
            "disclaimer": "Probabilistic analysis only — not a guarantee.",
            "confidence": 0.6 if assets else 0.2,
            "sentiment": bias,
        }


class MacroTrendAgent(VeridiqAgent):
    agent_type = "macro_trend"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        overview = payload.get("market_overview") or market_overview(
            per_page=5, agent_type=self.agent_type, job_id=payload.get("job_id")
        )
        btc = next((a for a in (overview.get("assets") or []) if a.get("symbol") == "BTC"), None)
        return {
            "summary": "Macro proxy uses BTC dominance of attention as risk barometer (not full macro model).",
            "evidence": [{"btc_price": (btc or {}).get("price"), "btc_change_24h": (btc or {}).get("change_24h_pct")}],
            "sources": ["CoinGecko BTC market row"],
            "risks": ["Crypto-native proxy ≠ complete macro regime model."],
            "alternative_scenarios": ["Risk-off if BTC leads lower with rising volume", "Risk-on if BTC stabilizes and alts catch up"],
            "disclaimer": "Probabilistic analysis only — not a guarantee.",
            "confidence": 0.5 if btc else 0.25,
        }


class TechnicalAnalysisAgent(VeridiqAgent):
    agent_type = "technical_analysis"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        coin_id = payload.get("coin_id") or "bitcoin"
        hist = coin_history(coin_id=coin_id, days=7, agent_type=self.agent_type, job_id=payload.get("job_id"))
        prices = [float(p["price"]) for p in (hist.get("prices") or []) if p.get("price") is not None]
        ind = simple_indicators(prices)
        return {
            "summary": f"Technical bias for {coin_id}: {ind.get('trend_bias') or 'n/a'}.",
            "evidence": [{"indicators": ind, "points": len(prices)}],
            "sources": [f"CoinGecko /coins/{coin_id}/market_chart"],
            "risks": ["Indicators lag; false breakouts are common."],
            "alternative_scenarios": ["Breakout continuation", "Failed break and mean reversion"],
            "disclaimer": "Probabilistic analysis only — not a guarantee.",
            "confidence": 0.58 if ind.get("status") == "ok" else 0.25,
            "indicators": ind,
            "history": hist,
        }


class MarketRiskAgent(VeridiqAgent):
    agent_type = "market_risk"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        overview = payload.get("market_overview") or market_overview(
            per_page=15, agent_type=self.agent_type, job_id=payload.get("job_id")
        )
        assets = overview.get("assets") or []
        vol = [abs(float(a.get("change_24h_pct") or 0)) for a in assets]
        avg_move = sum(vol) / len(vol) if vol else 0.0
        level = "elevated" if avg_move > 5 else "moderate" if avg_move > 2 else "contained"
        return {
            "summary": f"Cross-asset 24h absolute move average ≈ {avg_move:.2f}% → risk {level}.",
            "evidence": [{"avg_abs_change_24h": round(avg_move, 4), "sample": len(assets)}],
            "sources": ["CoinGecko markets"],
            "risks": ["Volatility clustering", "Liquidity gaps", "Narrative shocks"],
            "alternative_scenarios": ["Volatility compression", "Volatility expansion on catalyst"],
            "disclaimer": "Probabilistic analysis only — not a guarantee.",
            "confidence": 0.62 if assets else 0.2,
            "risk_level": level,
        }


class PortfolioIntelligenceAgent(VeridiqAgent):
    agent_type = "portfolio_intelligence"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        overview = payload.get("market_overview") or market_overview(
            per_page=10, agent_type=self.agent_type, job_id=payload.get("job_id")
        )
        assets = overview.get("assets") or []
        concentration = "high" if assets and (assets[0].get("market_cap") or 0) > 0 else "unknown"
        return {
            "summary": "Portfolio framing uses liquid majors as reference set — not a personal portfolio.",
            "evidence": [{"top_symbols": [a.get("symbol") for a in assets[:5]], "concentration_proxy": concentration}],
            "sources": ["CoinGecko markets"],
            "risks": ["Without holdings input, portfolio guidance stays generic."],
            "alternative_scenarios": ["Diversify across uncorrelated regimes", "Concentrate with explicit risk budget"],
            "disclaimer": "Probabilistic analysis only — not a guarantee.",
            "confidence": 0.45 if assets else 0.2,
        }


MARKET_AGENT_CLASSES = {
    "market_research": MarketResearchAgent,
    "onchain_analysis": OnchainAnalysisAgent,
    "news_correlation": NewsCorrelationAgent,
    "sentiment_analysis": SentimentAnalysisAgent,
    "macro_trend": MacroTrendAgent,
    "technical_analysis": TechnicalAnalysisAgent,
    "market_risk": MarketRiskAgent,
    "portfolio_intelligence": PortfolioIntelligenceAgent,
}
