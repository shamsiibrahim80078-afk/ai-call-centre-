"""
Scout Agent — autonomous business discovery employee.
Inherits BaseAgent, scouts targets, persists unique leads, maintains heartbeats.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.base_agent import BaseAgent  # noqa: E402
from database import (  # noqa: E402
    find_lead,
    get_lead,
    initialize_database,
    save_lead,
    update_lead,
)
from utils.business_analyzer import analyze_business  # noqa: E402
from utils.web_scraper import scrape_website  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class ScoutAgent(BaseAgent):
    """First real autonomous employee: discovers and stores unique business leads."""

    def __init__(
        self,
        name: str = "Scout-Prime",
        *,
        agent_uuid: Optional[str] = None,
        auto_register: bool = True,
    ) -> None:
        super().__init__(
            name=name,
            agent_type="scout",
            agent_uuid=agent_uuid,
            auto_register=auto_register,
        )
        self.jobs_processed: int = 0
        self.leads_created: int = 0
        self.duplicates_skipped: int = 0
        self.last_job_result: Optional[dict[str, Any]] = None

    def _run_task(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        if task in {"scout", "scout_business", "ingest_leads", "analyze_website"}:
            return self.process_scouting_job(payload)
        return super()._run_task(task, payload)

    def process_scouting_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """
        Continuously-callable scouting unit:
        extract business info from job (or live scrape), analyze, save unique lead.
        """
        self.heartbeat(status="active", current_task="scout_business")
        self.jobs_processed += 1

        website = (job.get("website") or job.get("url") or "").strip() or None
        business_name = (job.get("business_name") or job.get("name") or "").strip() or None
        parsed: Optional[dict[str, Any]] = job.get("parsed")
        analysis: Optional[dict[str, Any]] = job.get("analysis")

        if website and job.get("live_scrape"):
            parsed = scrape_website(website)
            business_name = business_name or parsed.get("business_name")
            website = parsed.get("website") or website

        if parsed is None:
            parsed = {
                "business_name": business_name,
                "website": website,
                "phone": job.get("phone"),
                "email": job.get("email"),
                "industry": job.get("industry"),
                "city": job.get("city"),
                "country": job.get("country"),
                "about": job.get("about") or job.get("website_summary"),
                "social_links": job.get("social_links") or [],
                "emails": [job["email"]] if job.get("email") else [],
                "phones": [job["phone"]] if job.get("phone") else [],
                "html_length": int(job.get("html_length") or 5000),
                "text_length": int(job.get("text_length") or 1200),
                "meta": {"description": job.get("about")},
                "raw_text_sample": job.get("about") or "",
                "title": business_name,
            }

        if not business_name:
            business_name = str(parsed.get("business_name") or "").strip()
        if not business_name:
            raise ValueError("scouting job requires business_name or scrapeable website.")

        website = website or parsed.get("website")

        # Duplicate prevention: website first, then business name
        existing = None
        if website:
            existing = find_lead(website=website)
        if existing is None:
            existing = find_lead(business_name=business_name)

        if analysis is None:
            analysis = analyze_business(parsed)

        stamped = _utc_now_iso()
        lead_payload = {
            "business_name": business_name,
            "website": website,
            "pain_points": analysis.get("pain_points_text"),
            "phone": analysis.get("phone") or parsed.get("phone") or job.get("phone"),
            "status": "scouted",
            "industry": analysis.get("industry") or parsed.get("industry") or job.get("industry"),
            "email": analysis.get("email") or parsed.get("email") or job.get("email"),
            "city": analysis.get("city") or parsed.get("city") or job.get("city"),
            "country": analysis.get("country") or parsed.get("country") or job.get("country"),
            "opportunity_score": float(analysis.get("opportunity_score") or 0),
            "automation_score": float(analysis.get("automation_score") or 0),
            "website_summary": analysis.get("website_summary"),
            "last_analyzed": analysis.get("analyzed_at") or stamped,
        }

        if existing:
            self.duplicates_skipped += 1
            lead = update_lead(int(existing["id"]), **lead_payload)
            created = False
            action = "updated_existing"
        else:
            lead_id = save_lead(**lead_payload)
            lead = get_lead(lead_id) or {"id": lead_id, **lead_payload}
            self.leads_created += 1
            created = True
            action = "created"

        self.heartbeat(status="idle", current_task=None, increment_cycle=False)
        result = {
            "action": action,
            "created": created,
            "duplicate": not created,
            "lead": lead,
            "analysis": analysis,
            "jobs_processed": self.jobs_processed,
            "leads_created": self.leads_created,
            "duplicates_skipped": self.duplicates_skipped,
        }
        self.last_job_result = result
        self._state["last_scout_result"] = {
            "lead_id": lead.get("id"),
            "action": action,
            "at": stamped,
        }
        self.save_state()
        return result

    def scout_batch(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Process a continuous stream/list of scouting jobs."""
        results: list[dict[str, Any]] = []
        for job in jobs:
            results.append(self.execute(task="scout_business", payload=job)["result"])
        return results


# Process-level scout status for API surfaces
_scout_runtime: dict[str, Any] = {
    "running": False,
    "agent_uuid": None,
    "jobs_processed": 0,
    "leads_created": 0,
    "duplicates_skipped": 0,
    "last_result": None,
    "started_at": None,
    "finished_at": None,
}


def get_scout_runtime() -> dict[str, Any]:
    return dict(_scout_runtime)


def update_scout_runtime(**kwargs: Any) -> dict[str, Any]:
    _scout_runtime.update(kwargs)
    return get_scout_runtime()


def _self_test() -> None:
    print("=" * 60)
    print("SCOUT AGENT — SELF-TEST")
    print("=" * 60)

    initialize_database()
    scout = ScoutAgent(name="Scout-Test-Alpha")
    hb = scout.heartbeat(status="active", current_task="self_test")
    assert hb["last_ping_at"]
    print(f"[OK] heartbeat uuid={scout.uuid} cycles={scout.total_cycles}")

    job = {
        "business_name": "Phase3 Test Dental",
        "website": "https://phase3-test-dental.example",
        "phone": "+1-555-0199",
        "email": "hello@phase3-test-dental.example",
        "industry": "healthcare",
        "city": "Austin",
        "country": "USA",
        "about": "Family dental clinic. Contact us today.",
        "html_length": 1800,
        "text_length": 350,
    }
    first = scout.process_scouting_job(job)
    assert first["created"] is True
    lead_id = first["lead"]["id"]
    print(f"[OK] database write lead_id={lead_id} score={first['lead']['opportunity_score']}")

    second = scout.process_scouting_job(job)
    assert second["duplicate"] is True
    assert second["lead"]["id"] == lead_id
    print(f"[OK] duplicate prevention skipped={scout.duplicates_skipped}")

    assert scout.leads_created == 1
    print("[OK] scout counters consistent")
    print("=" * 60)
    print("SCOUT AGENT SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
