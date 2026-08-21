"""Marketing platform integration — generic official API key holder. No scraping."""

from __future__ import annotations

import os
from typing import Any

import requests

from veridiq.integrations.base import status_shape

MARKETING_KEY = "VERIDIQ_MARKETING_API_KEY"
WEBHOOK_URL = "VERIDIQ_MARKETING_WEBHOOK_URL"
ENV_VARS = [MARKETING_KEY, WEBHOOK_URL]
CAPABILITIES = ["campaign_status (provider dependent)", "send_campaign (via configured webhook, after explicit comms approval)"]


def status() -> dict[str, Any]:
    key = os.getenv(MARKETING_KEY)
    if not key:
        return status_shape(
            "marketing",
            "Marketing Platform",
            "marketing",
            status="configuration_required",
            configured=False,
            message=f"Set {MARKETING_KEY} for your marketing platform's official API (e.g. Mailchimp, Marketo).",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=None,
        )
    webhook = os.getenv(WEBHOOK_URL)
    return status_shape(
        "marketing",
        "Marketing Platform",
        "marketing",
        status="configured",
        configured=True,
        message=(
            "Marketing API key and send webhook present — approve a comms draft with channel=marketing to send."
            if webhook
            else f"Marketing API key present. Set {WEBHOOK_URL} (your provider's official send/trigger webhook) to enable live sends."
        ),
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=None,
    )


def test_connection() -> dict[str, Any]:
    key = os.getenv(MARKETING_KEY)
    if not key:
        return {
            "platform": "marketing",
            "status": "configuration_required",
            "message": f"Set {MARKETING_KEY} to enable this integration.",
        }
    if not os.getenv(WEBHOOK_URL):
        return {
            "platform": "marketing",
            "status": "configured",
            "message": f"API key present, but no send webhook is set ({WEBHOOK_URL}) — no live test is possible for a generic provider.",
        }
    return {
        "platform": "marketing",
        "status": "configured",
        "message": "API key and webhook present — use send_campaign to trigger a real send.",
    }


def send_campaign(*, subject: str, body: str, audience_hint: str = "") -> dict[str, Any]:
    """Trigger a real campaign send via the operator-configured marketing webhook.

    Only ever invoked after explicit approval of a comms draft
    (`veridiq.comms.assistant.approve_external_action`, channel="marketing").
    Generic marketing platforms don't share one fixed API shape, so VERIDIQ
    calls whatever official send/trigger webhook the operator configures —
    it never fabricates a delivered campaign when nothing is configured.
    """
    key = os.getenv(MARKETING_KEY)
    if not key:
        return {"status": "configuration_required", "message": f"Set {MARKETING_KEY} to enable marketing sends."}
    webhook = os.getenv(WEBHOOK_URL)
    if not webhook:
        return {
            "status": "configuration_required",
            "message": f"Set {WEBHOOK_URL} (your marketing platform's official send/trigger webhook) to enable live sends.",
        }
    try:
        resp = requests.post(
            webhook,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"subject": subject, "body": body, "audience_hint": audience_hint},
            timeout=10,
        )
        if resp.status_code in (200, 201, 202):
            return {"status": "ok", "message": f"Marketing campaign submitted to configured webhook (HTTP {resp.status_code})."}
        return {
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"Marketing webhook returned HTTP {resp.status_code}: {resp.text[:200]}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Marketing webhook send failed: {str(exc)[:200]}"}
