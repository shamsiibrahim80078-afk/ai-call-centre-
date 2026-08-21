"""AI Calling — official Twilio Voice REST API only.

No number is ever dialed automatically. `place_call` is invoked exclusively
from the campaign approval flow (`veridiq.calling.campaigns.approve_campaign`)
after an explicit human approval.
"""

from __future__ import annotations

import os
from typing import Any, Optional
from urllib.parse import quote

import requests

from veridiq.integrations.base import status_shape

ACCOUNT_SID = "VERIDIQ_TWILIO_ACCOUNT_SID"
AUTH_TOKEN = "VERIDIQ_TWILIO_AUTH_TOKEN"
FROM_NUMBER = "VERIDIQ_TWILIO_FROM_NUMBER"

ENV_VARS = [ACCOUNT_SID, AUTH_TOKEN, FROM_NUMBER]
CAPABILITIES = ["account_verification", "place_call (after explicit campaign approval)", "call_status_lookup"]
DOCS = "https://www.twilio.com/docs/voice"


def status() -> dict[str, Any]:
    sid = os.getenv(ACCOUNT_SID)
    token = os.getenv(AUTH_TOKEN)
    from_number = os.getenv(FROM_NUMBER)
    if not (sid and token and from_number):
        return status_shape(
            "ai_calling",
            "AI Calling (Twilio Voice)",
            "calling",
            status="configuration_required",
            configured=False,
            message=f"Set {ACCOUNT_SID}, {AUTH_TOKEN}, and {FROM_NUMBER} to enable official Twilio Voice calling.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    return status_shape(
        "ai_calling",
        "AI Calling (Twilio Voice)",
        "calling",
        status="configured",
        configured=True,
        message="Twilio credentials present — use /test to verify the account with a live call.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def test_connection() -> dict[str, Any]:
    sid = os.getenv(ACCOUNT_SID)
    token = os.getenv(AUTH_TOKEN)
    if not (sid and token):
        return {
            "platform": "ai_calling",
            "status": "configuration_required",
            "message": f"Set {ACCOUNT_SID} and {AUTH_TOKEN} to run a live test.",
        }
    try:
        resp = requests.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json",
            auth=(sid, token),
            timeout=6,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "platform": "ai_calling",
                "status": "ok",
                "api_response_status": resp.status_code,
                "message": f"Verified Twilio account: {data.get('friendly_name', sid)}.",
            }
        return {
            "platform": "ai_calling",
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"Twilio API returned HTTP {resp.status_code}.",
        }
    except Exception as exc:
        return {"platform": "ai_calling", "status": "error", "message": f"Twilio API unreachable: {str(exc)[:200]}"}


def place_call(*, to: str, message: Optional[str] = None, twiml_url: Optional[str] = None) -> dict[str, Any]:
    """Real Twilio call creation. Only ever invoked after explicit campaign approval."""
    sid = os.getenv(ACCOUNT_SID)
    token = os.getenv(AUTH_TOKEN)
    from_number = os.getenv(FROM_NUMBER)
    if not (sid and token and from_number):
        return {"status": "configuration_required", "message": f"Set {ACCOUNT_SID}, {AUTH_TOKEN}, {FROM_NUMBER} to enable calling."}

    twiml = twiml_url or (
        "https://twimlets.com/message?Message%5B0%5D=" + quote(message or "This is a VERIDIQ automated call.")
    )
    try:
        resp = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json",
            auth=(sid, token),
            data={"To": to, "From": from_number, "Url": twiml},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            return {
                "status": "ok",
                "call_sid": data.get("sid"),
                "call_status": data.get("status"),
                "message": f"Call placed to {to} (sid {data.get('sid')}).",
            }
        return {
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"Twilio call failed: HTTP {resp.status_code} {resp.text[:150]}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Twilio call failed: {str(exc)[:200]}"}


def call_status(call_sid: str) -> dict[str, Any]:
    sid = os.getenv(ACCOUNT_SID)
    token = os.getenv(AUTH_TOKEN)
    if not (sid and token):
        return {"status": "configuration_required", "message": f"Set {ACCOUNT_SID} and {AUTH_TOKEN} to look up call status."}
    try:
        resp = requests.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls/{call_sid}.json",
            auth=(sid, token),
            timeout=6,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {"status": "ok", "call_status": data.get("status"), "duration": data.get("duration")}
        return {"status": "error", "api_response_status": resp.status_code, "message": f"Twilio returned HTTP {resp.status_code}."}
    except Exception as exc:
        return {"status": "error", "message": f"Twilio API unreachable: {str(exc)[:200]}"}
