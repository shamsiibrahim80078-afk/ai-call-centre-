"""Public influencer / creator research via official search + optional AI summary.

Official APIs only (Tavily / Exa / SerpAPI fan-out). No scraping.
Missing credentials → ``configuration_required`` — never invented shortlists.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def research_creators(
    *,
    query: str,
    niche: Optional[str] = None,
    max_results: int = 8,
    summarize: bool = True,
) -> dict[str, Any]:
    """Fan-out public web research for creator / influencer signals."""
    from veridiq.research.multi_search import multi_search

    q = (query or "").strip()
    if not q:
        return {
            "ok": False,
            "status": "invalid_args",
            "message": "query is required.",
            "results": [],
            "count": 0,
            "summary": None,
            "providers_used": [],
            "timestamp": _utc_now(),
        }

    niche_bit = (niche or "").strip()
    search_q = f"{q} {niche_bit} influencers creators social".strip()
    n = max(1, min(15, int(max_results)))
    search = multi_search(query=search_q, max_results_per_provider=min(5, n))

    results: list[dict[str, Any]] = []
    for item in search.get("results") or []:
        results.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "snippet": item.get("snippet"),
                "provider": item.get("provider"),
                "score": item.get("score"),
            }
        )
        if len(results) >= n:
            break

    summary: Optional[str] = None
    summary_status: Optional[str] = None
    if summarize and results:
        try:
            from veridiq.integrations import ai_gateway

            lines = []
            for r in results[:6]:
                lines.append(f"- {r.get('title') or 'Untitled'}: {r.get('url') or ''} — {(r.get('snippet') or '')[:160]}")
            prompt = (
                "You are VeriDiQ influencer research. Summarize these public web hits for outreach planning. "
                "Do NOT invent handles, follower counts, or contact details. Be concise (4-6 bullets).\n\n"
                + "\n".join(lines)
            )
            gen = ai_gateway.generate(prompt=prompt, task_type="research", max_providers=2)
            summary_status = gen.get("status")
            if gen.get("ok") and gen.get("text"):
                summary = str(gen.get("text")).strip()[:2500]
            elif gen.get("status") == "configuration_required":
                summary_status = "configuration_required"
        except Exception as exc:
            summary_status = "error"
            summary = None
            _ = str(exc)[:120]

    status = search.get("status") or "error"
    if status == "configuration_required":
        message = search.get("message") or "No research providers configured."
    elif results:
        message = (
            f"Found {len(results)} public signal(s) via {', '.join(search.get('providers_used') or [])}."
            + (" AI summary attached." if summary else " AI summary skipped or unavailable.")
        )
    else:
        message = search.get("message") or "No public results returned."

    return {
        "ok": bool(results) or status == "ok",
        "status": status if results or status == "configuration_required" else status,
        "query": q,
        "niche": niche_bit or None,
        "search_query": search_q,
        "results": results,
        "count": len(results),
        "summary": summary,
        "summary_status": summary_status,
        "providers_used": search.get("providers_used") or [],
        "provider_errors": search.get("provider_errors") or [],
        "message": message,
        "note": (
            "Public web research only — no fabricated follower counts, engagement metrics, or auto-outreach. "
            "Use Adrian (influencer_relations) + Marketing Agency drafts for approved engagement."
        ),
        "timestamp": _utc_now(),
    }
