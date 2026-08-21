"""Thin multi-search fan-out across configured research providers.

Official APIs only (Tavily, Exa, SerpAPI). No scraping. No fabricated results.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _providers() -> dict[str, Any]:
    from veridiq.integrations import exa, serpapi, tavily

    return {"tavily": tavily, "exa": exa, "serpapi": serpapi}


def configured_providers() -> list[str]:
    out: list[str] = []
    for name, mod in _providers().items():
        try:
            if mod.status().get("configured"):
                out.append(name)
        except Exception:
            continue
    return out


def multi_search(
    *,
    query: str,
    max_results_per_provider: int = 5,
    providers: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Fan-out search to configured providers and merge results."""
    q = (query or "").strip()
    if not q:
        return {
            "status": "invalid_args",
            "ok": False,
            "message": "query is required.",
            "results": [],
            "count": 0,
            "providers_used": [],
            "timestamp": _utc_now(),
        }

    catalog = _providers()
    wanted = providers or list(catalog.keys())
    active = []
    for name in wanted:
        mod = catalog.get(name)
        if not mod:
            continue
        try:
            if mod.status().get("configured"):
                active.append(name)
        except Exception:
            continue

    if not active:
        return {
            "status": "configuration_required",
            "ok": False,
            "message": "No research providers configured. Set VERIDIQ_TAVILY_API_KEY / VERIDIQ_EXA_API_KEY / VERIDIQ_SERPAPI_API_KEY.",
            "results": [],
            "count": 0,
            "providers_used": [],
            "provider_errors": [],
            "timestamp": _utc_now(),
        }

    n = max(1, min(10, int(max_results_per_provider)))
    merged: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    used: list[str] = []
    seen_urls: set[str] = set()

    def _call(name: str) -> tuple[str, dict[str, Any]]:
        mod = catalog[name]
        if name == "serpapi":
            return name, mod.search(query=q, num=n)
        if name == "exa":
            return name, mod.search(query=q, num_results=n)
        return name, mod.search(query=q, max_results=n)

    with ThreadPoolExecutor(max_workers=min(3, len(active))) as pool:
        futures = [pool.submit(_call, name) for name in active]
        for fut in as_completed(futures):
            try:
                name, result = fut.result()
            except Exception as exc:
                errors.append({"provider": "unknown", "status": "error", "message": str(exc)[:200]})
                continue
            if result.get("status") != "ok":
                errors.append(
                    {
                        "provider": name,
                        "status": result.get("status"),
                        "message": (result.get("message") or "")[:200],
                    }
                )
                continue
            used.append(name)
            for item in result.get("results") or []:
                url = (item.get("url") or "").strip()
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                merged.append(
                    {
                        "title": item.get("title"),
                        "url": url or None,
                        "snippet": item.get("snippet"),
                        "provider": name,
                        "score": item.get("score") or item.get("position"),
                    }
                )

    return {
        "status": "ok" if used else "error",
        "ok": bool(used),
        "query": q,
        "results": merged,
        "count": len(merged),
        "providers_used": used,
        "provider_errors": errors,
        "message": f"Merged {len(merged)} result(s) from {len(used)} provider(s)."
        if used
        else "All configured providers failed.",
        "timestamp": _utc_now(),
    }
