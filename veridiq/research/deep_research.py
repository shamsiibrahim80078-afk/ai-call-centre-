"""Deep research task runner — multi_search + optional LLM extract/summary.

Official APIs only. Never invents sources. Missing keys → configuration_required.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

# Matches English + common Roman-Urdu research task phrasing.
_RESEARCH_INTENT_RE = re.compile(
    r"(?:"
    r"\bdeep[\s\-]?research\b|"
    r"\bresearch\b|"
    r"\bfind\s+out\b|"
    r"\blook\s*up\b|"
    r"\bsearch\s+(?:for|the\s+web|online)\b|"
    r"\binvestigate\b|"
    r"\bgather\s+(?:info|information|sources)\b|"
    r"\bextract\b|"
    r"\bnikaal\b|"
    r"\bnikal\b|"
    r"\bdhoond(?:o|na)?\b|"
    r"\bkarke\s+(?:yeh|ye|is)\b"
    r")",
    re.I,
)

_INFLUENCER_RE = re.compile(r"\b(influencer|influencers|creators?|adrian)\b", re.I)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def looks_like_research_task(text: str) -> bool:
    """True when the user asks to research / extract / find out (not influencer-only)."""
    q = (text or "").strip()
    if not q or not _RESEARCH_INTENT_RE.search(q):
        return False
    # Pure influencer research is handled by the calling/influencer path.
    if _INFLUENCER_RE.search(q) and not re.search(r"\bdeep[\s\-]?research\b", q, re.I):
        return False
    return True


def extract_research_query(text: str) -> str:
    """Strip command words; keep the topic the user wants researched."""
    q = (text or "").strip()
    if not q:
        return ""
    cleaned = re.sub(
        r"\b("
        r"deep[\s\-]?research|research|please|pls|can\s+you|could\s+you|"
        r"find\s+out|look\s*up|search\s+for|investigate|gather|extract|"
        r"nikaal(?:\s+do)?|nikal(?:\s+do)?|dhoond(?:o|na)?|"
        r"karke|yahan\s+se|yeh|ye|cheez|do|from\s+here|"
        r"and\s+(?:summarize|summarise|extract)|"
        r"tell\s+me|what\s+(?:is|are)\s+the"
        r")\b",
        " ",
        q,
        flags=re.I,
    )
    cleaned = re.sub(r"[\"'`]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t\n\r.,:;!?-")
    return cleaned[:500] or q[:500]


def deep_research(
    *,
    query: str,
    max_results: int = 8,
    summarize: bool = True,
) -> dict[str, Any]:
    """Run multi-provider web research and optionally summarize/extract findings."""
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

    n = max(1, min(15, int(max_results)))
    search = multi_search(query=q, max_results_per_provider=min(5, n))

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

            if not ai_gateway.status().get("configured"):
                summary_status = "configuration_required"
            else:
                lines = []
                for r in results[:8]:
                    lines.append(
                        f"- {r.get('title') or 'Untitled'}: {r.get('url') or ''} — "
                        f"{(r.get('snippet') or '')[:200]}"
                    )
                prompt = (
                    "You are a careful research assistant. Using ONLY the search hits below, "
                    "extract the key facts the user asked for. Cite titles/URLs when useful. "
                    "Do NOT invent sources, quotes, statistics, or URLs that are not listed. "
                    "If the hits are thin, say what is missing. Be clear and structured "
                    "(short bullets + a 2-3 sentence takeaway).\n\n"
                    f"User research request:\n{q}\n\nSearch hits:\n" + "\n".join(lines)
                )
                gen = ai_gateway.generate(
                    prompt=prompt, task_type="research", max_providers=3, max_tokens=1400
                )
                summary_status = gen.get("status")
                if gen.get("ok") and gen.get("text"):
                    summary = str(gen.get("text")).strip()[:4000]
                elif gen.get("status") == "configuration_required":
                    summary_status = "configuration_required"
        except Exception:
            summary_status = "error"
            summary = None

    status = search.get("status") or "error"
    if status == "configuration_required":
        message = search.get("message") or (
            "No research providers configured. "
            "Set VERIDIQ_TAVILY_API_KEY / VERIDIQ_EXA_API_KEY / VERIDIQ_SERPAPI_API_KEY."
        )
    elif results:
        message = (
            f"Found {len(results)} source(s) via {', '.join(search.get('providers_used') or [])}."
            + (" Summary attached." if summary else " Summary skipped or unavailable.")
        )
    else:
        message = search.get("message") or "No public results returned."

    # Offline extract when LLM summary unavailable but we have hits
    if not summary and results:
        bullets = []
        for r in results[:6]:
            title = (r.get("title") or "Untitled").strip()
            url = (r.get("url") or "").strip()
            snip = (r.get("snippet") or "").strip()[:180]
            line = f"• {title}"
            if snip:
                line += f" — {snip}"
            if url:
                line += f" ({url})"
            bullets.append(line)
        summary = "Research findings (from live search; no invented sources):\n" + "\n".join(bullets)

    return {
        "ok": bool(results) or status == "ok",
        "status": status if results or status == "configuration_required" else status,
        "query": q,
        "results": results,
        "count": len(results),
        "summary": summary,
        "summary_status": summary_status,
        "providers_used": search.get("providers_used") or [],
        "provider_errors": search.get("provider_errors") or [],
        "message": message,
        "note": "Live search only — sources are from configured providers; nothing fabricated.",
        "timestamp": _utc_now(),
    }


def format_research_answer(research: dict[str, Any]) -> str:
    """User-facing reply for host/calling chat."""
    status = research.get("status")
    if status == "configuration_required":
        return (
            research.get("message")
            or "Deep research needs a search API key "
            "(VERIDIQ_TAVILY_API_KEY, VERIDIQ_EXA_API_KEY, or VERIDIQ_SERPAPI_API_KEY)."
        )
    summary = (research.get("summary") or "").strip()
    if summary:
        return summary
    if research.get("message"):
        return str(research["message"])
    return "Research completed but no extractable findings were returned."
