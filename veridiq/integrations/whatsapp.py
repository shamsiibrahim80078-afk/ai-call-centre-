"""WhatsApp integration — official Meta WhatsApp Cloud API only. No scraping."""

from __future__ import annotations

import os
from typing import Any

import requests

from veridiq.integrations.base import status_shape

TOKEN = "VERIDIQ_WHATSAPP_TOKEN"
PHONE_NUMBER_ID = "VERIDIQ_WHATSAPP_PHONE_NUMBER_ID"
ENV_VARS = [TOKEN, PHONE_NUMBER_ID]
CAPABILITIES = ["send_message (Meta Cloud API — after explicit comms approval)"]
DOCS = "https://developers.facebook.com/docs/whatsapp/cloud-api/"


def status() -> dict[str, Any]:
    token = os.getenv(TOKEN)
    phone_id = os.getenv(PHONE_NUMBER_ID)
    if not (token and phone_id):
        return status_shape(
            "whatsapp",
            "WhatsApp",
            "messaging",
            status="configuration_required",
            configured=False,
            message=f"Set {TOKEN} and {PHONE_NUMBER_ID} (Meta WhatsApp Cloud API) to enable messaging.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    return status_shape(
        "whatsapp",
        "WhatsApp",
        "messaging",
        status="configured",
        configured=True,
        message="Cloud API credentials present — use /test to verify with a live call.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def test_connection() -> dict[str, Any]:
    token = os.getenv(TOKEN)
    phone_id = os.getenv(PHONE_NUMBER_ID)
    if not (token and phone_id):
        return {
            "platform": "whatsapp",
            "status": "configuration_required",
            "message": f"Set {TOKEN} and {PHONE_NUMBER_ID} to run a live test.",
        }
    try:
        resp = requests.get(
            f"https://graph.facebook.com/v19.0/{phone_id}",
            params={"fields": "verified_name", "access_token": token},
            timeout=6,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "platform": "whatsapp",
                "status": "ok",
                "api_response_status": resp.status_code,
                "message": f"Verified WhatsApp sender: {data.get('verified_name', '?')}.",
            }
        return {
            "platform": "whatsapp",
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"Meta Graph API returned HTTP {resp.status_code}.",
        }
    except Exception as exc:
        return {"platform": "whatsapp", "status": "error", "message": f"Meta Graph API unreachable: {str(exc)[:200]}"}


def send_message(*, to: str, text: str) -> dict[str, Any]:
    """Send a real text message via the official Meta WhatsApp Cloud API.

    Only ever invoked after explicit approval of a comms draft
    (`veridiq.comms.assistant.approve_external_action`, channel="whatsapp").
    `to` must be an E.164-formatted phone number.
    """
    token = os.getenv(TOKEN)
    phone_id = os.getenv(PHONE_NUMBER_ID)
    if not (token and phone_id):
        return {
            "status": "configuration_required",
            "message": f"Set {TOKEN} and {PHONE_NUMBER_ID} to send WhatsApp messages.",
        }
    if not (to or "").strip():
        return {"status": "error", "message": "Recipient phone number ('to') is required."}
    content = (text or "").strip()
    if not content:
        return {"status": "error", "message": "Message text is empty — nothing to send."}
    try:
        resp = requests.post(
            f"https://graph.facebook.com/v19.0/{phone_id}/messages",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": content[:4096]}},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            data = resp.json() or {}
            msg_id = ((data.get("messages") or [{}])[0]).get("id")
            return {"status": "ok", "message_id": msg_id, "message": f"WhatsApp message sent to {to}."}
        return {
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"WhatsApp send failed: HTTP {resp.status_code} {resp.text[:200]}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"WhatsApp send failed: {str(exc)[:200]}"}
