"""
Business Analyzer — detect digital gaps and score automation opportunity.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _blob(parsed: dict[str, Any]) -> str:
    parts = [
        str(parsed.get("about") or ""),
        str(parsed.get("raw_text_sample") or ""),
        str(parsed.get("title") or ""),
        " ".join(parsed.get("social_links") or []),
        " ".join(parsed.get("emails") or []),
    ]
    return " ".join(parts).lower()


def analyze_business(parsed: dict[str, Any]) -> dict[str, Any]:
    """
    Analyze scraper output and produce pain points + opportunity/automation scores.
    Scores are 0-100 (higher = greater need / greater automation upside).
    """
    if not isinstance(parsed, dict) or not parsed:
        raise ValueError("parsed website payload is required.")

    text = _blob(parsed)
    html_length = int(parsed.get("html_length") or 0)
    text_length = int(parsed.get("text_length") or 0)
    social_count = len(parsed.get("social_links") or [])
    has_email = bool(parsed.get("email") or parsed.get("emails"))
    has_phone = bool(parsed.get("phone") or parsed.get("phones"))

    findings: dict[str, bool] = {
        "missing_chatbot": not any(
            token in text for token in ("chatbot", "live chat", "intercom", "drift", "tawk")
        ),
        "missing_ai_automation": not any(
            token in text
            for token in ("ai automation", "artificial intelligence", "machine learning", "gpt")
        ),
        "no_booking_system": not any(
            token in text
            for token in ("book now", "schedule", "calendly", "appointment", "reservation")
        ),
        "weak_marketing": social_count < 2,
        "poor_seo": (
            not parsed.get("meta", {}).get("description")
            or text_length < 400
            or html_length < 1500
        ),
        "missing_contact_forms": not any(
            token in text for token in ("contact form", "get in touch", "send message", "contact us")
        )
        and not has_email,
        "outdated_design": html_length < 2500 or "table layout" in text or "macromedia" in text,
    }

    weights = {
        "missing_chatbot": 14,
        "missing_ai_automation": 16,
        "no_booking_system": 14,
        "weak_marketing": 12,
        "poor_seo": 14,
        "missing_contact_forms": 16,
        "outdated_design": 14,
    }

    pain_points = [key.replace("_", " ") for key, hit in findings.items() if hit]
    opportunity_score = float(sum(weights[k] for k, hit in findings.items() if hit))
    opportunity_score = min(100.0, opportunity_score)

    automation_score = 0.0
    if findings["missing_chatbot"]:
        automation_score += 22
    if findings["missing_ai_automation"]:
        automation_score += 24
    if findings["no_booking_system"]:
        automation_score += 18
    if findings["missing_contact_forms"]:
        automation_score += 16
    if findings["weak_marketing"]:
        automation_score += 10
    if not has_phone:
        automation_score += 5
    if not has_email:
        automation_score += 5
    automation_score = min(100.0, float(automation_score))

    website_quality = 100.0
    website_quality -= 15 if findings["poor_seo"] else 0
    website_quality -= 15 if findings["outdated_design"] else 0
    website_quality -= 10 if findings["weak_marketing"] else 0
    website_quality -= 10 if findings["missing_contact_forms"] else 0
    website_quality = max(0.0, website_quality)

    size_signal = "small"
    if html_length > 80000 or text_length > 20000 or social_count >= 4:
        size_signal = "large"
    elif html_length > 20000 or text_length > 5000 or social_count >= 2:
        size_signal = "medium"

    summary = (
        f"{parsed.get('business_name') or 'Business'} appears to be a "
        f"{parsed.get('industry') or 'general'} company. "
        f"Detected {len(pain_points)} digital gap(s). "
        f"Opportunity={opportunity_score:.0f}, Automation={automation_score:.0f}."
    )

    return {
        "business_name": parsed.get("business_name"),
        "website": parsed.get("website"),
        "findings": findings,
        "pain_points": pain_points,
        "pain_points_text": "; ".join(pain_points) if pain_points else "none detected",
        "opportunity_score": opportunity_score,
        "automation_score": automation_score,
        "website_quality": website_quality,
        "business_size": size_signal,
        "website_summary": summary,
        "industry": parsed.get("industry"),
        "email": parsed.get("email"),
        "phone": parsed.get("phone"),
        "city": parsed.get("city"),
        "country": parsed.get("country"),
        "analyzed_at": _utc_now_iso(),
    }


def _self_test() -> None:
    print("=" * 60)
    print("BUSINESS ANALYZER — SELF-TEST")
    print("=" * 60)

    from utils.web_scraper import scrape_website

    parsed = scrape_website("https://example.com")
    report = analyze_business(parsed)
    assert 0 <= report["opportunity_score"] <= 100
    assert 0 <= report["automation_score"] <= 100
    assert isinstance(report["pain_points"], list)
    assert report["website_summary"]
    print(f"[OK] pain_points={report['pain_points']}")
    print(f"[OK] opportunity_score={report['opportunity_score']}")
    print(f"[OK] automation_score={report['automation_score']}")
    print(f"[OK] website_quality={report['website_quality']}")
    print(f"[OK] business_size={report['business_size']}")
    print(f"[OK] summary={report['website_summary']}")
    print("=" * 60)
    print("BUSINESS ANALYZER SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
