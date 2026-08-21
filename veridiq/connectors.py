"""
External data connectors — official APIs only.
No scraping. If credentials/config are missing, report configuration_required.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

import requests


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
            workflow_stage="connector_call",
            completion_status=completion_status,
            api_response_status=api_response_status,
            recent_activity=recent_activity,
            errors=errors,
        )
    except Exception:
        pass  # activity logging must never break the connector call itself


def news_connector(*, agent_type: Optional[str] = None, job_id: Optional[str] = None) -> dict[str, Any]:
    key = os.getenv("VERIDIQ_NEWSAPI_KEY") or os.getenv("NEWS_API_KEY")
    if not key:
        return {
            "provider": "NewsAPI",
            "status": "configuration_required",
            "message": "Set VERIDIQ_NEWSAPI_KEY to enable official news listings. No fabricated counts.",
            "articles": [],
            "count": 0,
            "timestamp": _utc_now(),
        }
    try:
        resp = requests.get(
            "https://newsapi.org/v2/top-headlines",
            params={"language": "en", "pageSize": 10, "apiKey": key},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        articles = [
            {
                "title": a.get("title"),
                "source": (a.get("source") or {}).get("name"),
                "url": a.get("url"),
                "published_at": a.get("publishedAt"),
            }
            for a in (data.get("articles") or [])
        ]
        _log_activity(
            platform="news_newsapi",
            task="Fetch top headlines",
            agent_type=agent_type,
            job_id=job_id,
            completion_status="completed",
            api_response_status=str(resp.status_code),
            recent_activity=f"Retrieved {len(articles)} live headlines from NewsAPI.",
        )
        return {
            "provider": "NewsAPI",
            "status": "ok",
            "count": len(articles),
            "articles": articles,
            "timestamp": _utc_now(),
        }
    except Exception as exc:
        _log_activity(
            platform="news_newsapi",
            task="Fetch top headlines",
            agent_type=agent_type,
            job_id=job_id,
            completion_status="failed",
            api_response_status="error",
            recent_activity="NewsAPI call failed.",
            errors=str(exc)[:200],
        )
        return {
            "provider": "NewsAPI",
            "status": "error",
            "message": str(exc)[:200],
            "articles": [],
            "count": 0,
            "timestamp": _utc_now(),
        }


def jobs_connector(*, agent_type: Optional[str] = None, job_id: Optional[str] = None) -> dict[str, Any]:
    # Remotive is a public API for remote jobs (no key required).
    try:
        resp = requests.get("https://remotive.com/api/remote-jobs", params={"limit": 10}, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        jobs = [
            {
                "title": j.get("title"),
                "company": j.get("company_name"),
                "url": j.get("url"),
                "category": j.get("category"),
                "location": j.get("candidate_required_location"),
            }
            for j in (data.get("jobs") or [])[:10]
        ]
        _log_activity(
            platform="jobs_remotive",
            task="Fetch remote job listings",
            agent_type=agent_type,
            job_id=job_id,
            completion_status="completed",
            api_response_status=str(resp.status_code),
            recent_activity=f"Retrieved {len(jobs)} listings from Remotive.",
        )
        return {
            "provider": "Remotive",
            "status": "ok",
            "count": len(jobs),
            "jobs": jobs,
            "timestamp": _utc_now(),
            "note": "Official Remotive public API.",
        }
    except Exception as exc:
        _log_activity(
            platform="jobs_remotive",
            task="Fetch remote job listings",
            agent_type=agent_type,
            job_id=job_id,
            completion_status="failed",
            api_response_status="error",
            recent_activity="Remotive API call failed.",
            errors=str(exc)[:200],
        )
        return {
            "provider": "Remotive",
            "status": "unavailable",
            "message": f"Official jobs API unreachable ({type(exc).__name__}). No fabricated listings.",
            "jobs": [],
            "count": 0,
            "timestamp": _utc_now(),
        }


def connectors_status() -> dict[str, Any]:
    return {
        "news": news_connector(),
        "jobs": jobs_connector(),
        "policy": "Official APIs only. Missing keys return configuration_required — never invented counts.",
    }
