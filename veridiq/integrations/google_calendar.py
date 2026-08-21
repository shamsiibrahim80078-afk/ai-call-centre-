"""Google Calendar connector — official Calendar API via VERIDIQ service layer."""

from __future__ import annotations

import os
from typing import Any

import requests

from veridiq.integrations.base import status_shape

CLIENT_ID = "VERIDIQ_GOOGLE_CALENDAR_CLIENT_ID"
CLIENT_SECRET = "VERIDIQ_GOOGLE_CALENDAR_CLIENT_SECRET"
ACCESS_TOKEN = "VERIDIQ_GOOGLE_CALENDAR_ACCESS_TOKEN"
ENV_VARS = [CLIENT_ID, CLIENT_SECRET, ACCESS_TOKEN]
CAPABILITIES = ["list_events", "create_event (after explicit approval)"]
DOCS = "https://developers.google.com/calendar/api"


def status() -> dict[str, Any]:
    if not (os.getenv(CLIENT_ID) and os.getenv(CLIENT_SECRET)):
        return status_shape(
            "google_calendar",
            "Google Calendar",
            "productivity",
            status="configuration_required",
            configured=False,
            message=f"Set {CLIENT_ID} and {CLIENT_SECRET} for official Calendar OAuth.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    return status_shape(
        "google_calendar",
        "Google Calendar",
        "productivity",
        status="configured",
        configured=True,
        message="OAuth client configured." + (f" Set {ACCESS_TOKEN} for live calls." if not os.getenv(ACCESS_TOKEN) else " Access token present."),
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def test_connection() -> dict[str, Any]:
    token = os.getenv(ACCESS_TOKEN)
    if not token:
        return {"platform": "google_calendar", "status": "configuration_required", "message": f"Set {ACCESS_TOKEN}."}
    try:
        resp = requests.get(
            "https://www.googleapis.com/calendar/v3/users/me/calendarList",
            headers={"Authorization": f"Bearer {token}"},
            params={"maxResults": 3},
            timeout=8,
        )
        if resp.status_code == 200:
            items = (resp.json() or {}).get("items") or []
            return {
                "platform": "google_calendar",
                "status": "ok",
                "api_response_status": resp.status_code,
                "message": f"Verified Calendar access — {len(items)} calendar(s) visible.",
            }
        return {
            "platform": "google_calendar",
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"Calendar API HTTP {resp.status_code}.",
        }
    except Exception as exc:
        return {"platform": "google_calendar", "status": "error", "message": str(exc)[:200]}


def list_events(*, calendar_id: str = "primary", max_results: int = 5, **_kwargs: Any) -> dict[str, Any]:
    token = os.getenv(ACCESS_TOKEN)
    if not token:
        return {
            "platform": "google_calendar",
            "status": "configuration_required",
            "ok": False,
            "message": f"Set {ACCESS_TOKEN}.",
        }
    try:
        resp = requests.get(
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
            headers={"Authorization": f"Bearer {token}"},
            params={"maxResults": max(1, min(20, int(max_results))), "singleEvents": True, "orderBy": "startTime"},
            timeout=10,
        )
        if resp.status_code != 200:
            return {
                "platform": "google_calendar",
                "status": "error",
                "ok": False,
                "api_response_status": resp.status_code,
                "message": f"Calendar API HTTP {resp.status_code}.",
            }
        items = (resp.json() or {}).get("items") or []
        events = [
            {"id": e.get("id"), "summary": e.get("summary"), "start": e.get("start"), "end": e.get("end")}
            for e in items
        ]
        return {
            "platform": "google_calendar",
            "status": "ok",
            "ok": True,
            "count": len(events),
            "events": events,
            "message": f"Listed {len(events)} event(s).",
        }
    except Exception as exc:
        return {"platform": "google_calendar", "status": "error", "ok": False, "message": str(exc)[:200]}
