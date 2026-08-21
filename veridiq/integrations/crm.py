"""CRM integration — HubSpot official API (or a generic CRM key). No scraping."""

from __future__ import annotations

import os
import time
from typing import Any

import requests

from veridiq.integrations.base import first_env, status_shape

HUBSPOT_KEY = "VERIDIQ_HUBSPOT_API_KEY"
GENERIC_KEY = "VERIDIQ_CRM_API_KEY"
ENV_VARS = [HUBSPOT_KEY, GENERIC_KEY]
CAPABILITIES = ["contact_lookup", "contact_create (provider dependent)"]
DOCS = "https://developers.hubspot.com/"


def status() -> dict[str, Any]:
    key = first_env(HUBSPOT_KEY, GENERIC_KEY)
    if not key:
        return status_shape(
            "crm",
            "CRM (HubSpot / generic)",
            "crm",
            status="configuration_required",
            configured=False,
            message=f"Set {HUBSPOT_KEY} (HubSpot private app token) or {GENERIC_KEY} for a generic CRM.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    provider = "HubSpot" if os.getenv(HUBSPOT_KEY) else "Generic CRM"
    return status_shape(
        "crm",
        "CRM (HubSpot / generic)",
        "crm",
        status="configured",
        configured=True,
        message=f"{provider} credentials present — use /test to verify with a live call.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def test_connection() -> dict[str, Any]:
    hubspot_key = os.getenv(HUBSPOT_KEY)
    if hubspot_key:
        try:
            resp = requests.get(
                "https://api.hubapi.com/crm/v3/objects/contacts",
                headers={"Authorization": f"Bearer {hubspot_key}"},
                params={"limit": 1},
                timeout=6,
            )
            if resp.status_code == 200:
                return {
                    "platform": "crm",
                    "status": "ok",
                    "api_response_status": resp.status_code,
                    "message": "HubSpot API key verified with a live call.",
                }
            return {
                "platform": "crm",
                "status": "error",
                "api_response_status": resp.status_code,
                "message": f"HubSpot API returned HTTP {resp.status_code}.",
            }
        except Exception as exc:
            return {"platform": "crm", "status": "error", "message": f"HubSpot API unreachable: {str(exc)[:200]}"}
    generic_key = os.getenv(GENERIC_KEY)
    if generic_key:
        return {
            "platform": "crm",
            "status": "configured",
            "message": "Generic CRM key present; provider-specific base URL is not fixed for a live test.",
        }
    return {
        "platform": "crm",
        "status": "configuration_required",
        "message": f"Set {HUBSPOT_KEY} or {GENERIC_KEY} to run a live test.",
    }


def sync_note(body: str) -> dict[str, Any]:
    """Sync a note (e.g. a call/campaign summary) to the configured CRM. Real API call — never fabricated."""
    hubspot_key = os.getenv(HUBSPOT_KEY)
    if not hubspot_key:
        return {"status": "configuration_required", "message": f"Set {HUBSPOT_KEY} to sync notes to HubSpot."}
    try:
        resp = requests.post(
            "https://api.hubapi.com/crm/v3/objects/notes",
            headers={"Authorization": f"Bearer {hubspot_key}", "Content-Type": "application/json"},
            json={"properties": {"hs_note_body": body[:5000], "hs_timestamp": str(int(time.time() * 1000))}},
            timeout=8,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            return {"status": "ok", "note_id": data.get("id"), "message": "Note synced to HubSpot."}
        return {"status": "error", "api_response_status": resp.status_code, "message": f"HubSpot returned HTTP {resp.status_code}."}
    except Exception as exc:
        return {"status": "error", "message": f"HubSpot sync failed: {str(exc)[:200]}"}
