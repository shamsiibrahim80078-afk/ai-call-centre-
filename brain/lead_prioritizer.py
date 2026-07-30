"""
Lead Prioritizer — rank scouted leads into HIGH / MEDIUM / LOW buckets.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import initialize_database, list_leads  # noqa: E402

SIZE_WEIGHT = {"small": 5.0, "medium": 12.0, "large": 18.0}


def _pain_count(lead: dict[str, Any]) -> int:
    raw = lead.get("pain_points") or ""
    if isinstance(raw, list):
        return len(raw)
    text = str(raw).strip()
    if not text or text.lower() == "none detected":
        return 0
    return len([p for p in text.split(";") if p.strip()])


def _infer_size(lead: dict[str, Any]) -> str:
    explicit = str(lead.get("business_size") or "").lower()
    if explicit in SIZE_WEIGHT:
        return explicit
    summary = str(lead.get("website_summary") or "").lower()
    if "large" in summary:
        return "large"
    if "medium" in summary:
        return "medium"
    score = float(lead.get("opportunity_score") or 0)
    if score >= 80:
        return "large"
    if score >= 50:
        return "medium"
    return "small"


def _website_quality(lead: dict[str, Any]) -> float:
    if lead.get("website_quality") is not None:
        return float(lead["website_quality"])
    # Inverse proxy from scores: high opportunity often means weaker site
    opp = float(lead.get("opportunity_score") or 0)
    auto = float(lead.get("automation_score") or 0)
    return max(0.0, 100.0 - ((opp + auto) / 2.0))


def compute_priority_score(lead: dict[str, Any]) -> float:
    """
    Composite ranking score.
    Higher = more actionable outbound target.
    """
    opportunity = float(lead.get("opportunity_score") or 0)
    automation = float(lead.get("automation_score") or 0)
    pains = _pain_count(lead)
    size = _infer_size(lead)
    quality = _website_quality(lead)

    # Weigh opportunity + automation heavily; more pains raise urgency;
    # weaker website quality (lower quality) slightly increases priority.
    score = (
        opportunity * 0.45
        + automation * 0.30
        + pains * 4.0
        + SIZE_WEIGHT.get(size, 5.0)
        + max(0.0, (70.0 - quality) * 0.15)
    )
    return round(score, 2)


def assign_priority_level(priority_score: float) -> str:
    if priority_score >= 70:
        return "HIGH"
    if priority_score >= 40:
        return "MEDIUM"
    return "LOW"


def prioritize_lead(lead: dict[str, Any]) -> dict[str, Any]:
    """Annotate a single lead with priority score and level."""
    enriched = dict(lead)
    score = compute_priority_score(enriched)
    level = assign_priority_level(score)
    enriched["priority_score"] = score
    enriched["priority"] = level
    enriched["business_size"] = _infer_size(enriched)
    enriched["website_quality"] = _website_quality(enriched)
    enriched["pain_point_count"] = _pain_count(enriched)
    return enriched


def prioritize_leads(leads: Optional[list[dict[str, Any]]] = None) -> list[dict[str, Any]]:
    """
    Sort leads using Opportunity Score, Business Size, Pain Points, Website Quality.
    Returns HIGH → MEDIUM → LOW ordered list.
    """
    initialize_database()
    source = leads if leads is not None else list_leads(limit=1000)
    ranked = [prioritize_lead(lead) for lead in source]
    ranked.sort(
        key=lambda item: (
            {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(item["priority"], 3),
            -float(item["priority_score"]),
            -float(item.get("opportunity_score") or 0),
        )
    )
    return ranked


def priority_summary(leads: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Dashboard aggregates for prioritized leads."""
    ranked = prioritize_leads(leads)
    high = [l for l in ranked if l["priority"] == "HIGH"]
    medium = [l for l in ranked if l["priority"] == "MEDIUM"]
    low = [l for l in ranked if l["priority"] == "LOW"]

    def _avg(items: list[dict[str, Any]], field: str) -> float:
        values = [float(i.get(field) or 0) for i in items if i.get(field) is not None]
        return round(sum(values) / len(values), 2) if values else 0.0

    return {
        "total_leads": len(ranked),
        "high_priority": len(high),
        "medium_priority": len(medium),
        "low_priority": len(low),
        "average_opportunity_score": _avg(ranked, "opportunity_score"),
        "average_automation_score": _avg(ranked, "automation_score"),
        "average_priority_score": _avg(ranked, "priority_score"),
        "leads": ranked,
    }


def _self_test() -> None:
    print("=" * 60)
    print("LEAD PRIORITIZER — SELF-TEST")
    print("=" * 60)

    sample = [
        {
            "business_name": "High Opp Co",
            "opportunity_score": 92,
            "automation_score": 88,
            "pain_points": "missing chatbot; poor seo; no booking system; outdated design",
            "website_quality": 35,
            "business_size": "medium",
        },
        {
            "business_name": "Mid Opp Co",
            "opportunity_score": 55,
            "automation_score": 40,
            "pain_points": "weak marketing; missing chatbot",
            "website_quality": 60,
            "business_size": "small",
        },
        {
            "business_name": "Low Opp Co",
            "opportunity_score": 15,
            "automation_score": 10,
            "pain_points": "none detected",
            "website_quality": 90,
            "business_size": "large",
        },
    ]
    ranked = prioritize_leads(sample)
    assert ranked[0]["priority"] == "HIGH"
    assert ranked[-1]["priority"] == "LOW"
    summary = priority_summary(sample)
    assert summary["total_leads"] == 3
    assert summary["high_priority"] >= 1
    print(f"[OK] ranked={[ (r['business_name'], r['priority'], r['priority_score']) for r in ranked ]}")
    print(f"[OK] summary high={summary['high_priority']} med={summary['medium_priority']} low={summary['low_priority']}")
    print("=" * 60)
    print("LEAD PRIORITIZER SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
