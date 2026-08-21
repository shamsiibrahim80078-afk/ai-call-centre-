"""Slack connector — official Slack Web API via VERIDIQ service layer."""

from __future__ import annotations

import os
from typing import Any

import requests

from veridiq.integrations.base import status_shape

BOT_TOKEN = "VERIDIQ_SLACK_BOT_TOKEN"
ENV_VARS = [BOT_TOKEN]
CAPABILITIES = ["auth_test", "post_message (after explicit approval)"]
DOCS = "https://api.slack.com/web"


def status() -> dict[str, Any]:
    if not os.getenv(BOT_TOKEN):
        return status_shape(
            "slack",
            "Slack",
            "comms",
            status="configuration_required",
            configured=False,
            message=f"Set {BOT_TOKEN} (xoxb-...) for official Slack Web API access.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    return status_shape(
        "slack",
        "Slack",
        "comms",
        status="configured",
        configured=True,
        message="Slack bot token present — use /test to verify with a live call.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def test_connection() -> dict[str, Any]:
    token = os.getenv(BOT_TOKEN)
    if not token:
        return {"platform": "slack", "status": "configuration_required", "message": f"Set {BOT_TOKEN}."}
    try:
        resp = requests.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code == 200 and data.get("ok"):
            return {
                "platform": "slack",
                "status": "ok",
                "api_response_status": resp.status_code,
                "message": f"Verified Slack team {data.get('team')} as @{data.get('user')}.",
            }
        return {
            "platform": "slack",
            "status": "error",
            "api_response_status": resp.status_code,
            "message": data.get("error") or f"Slack API HTTP {resp.status_code}.",
        }
    except Exception as exc:
        return {"platform": "slack", "status": "error", "message": str(exc)[:200]}


def post_message(*, channel: str, text: str, **_kwargs: Any) -> dict[str, Any]:
    token = os.getenv(BOT_TOKEN)
    if not token:
        return {"platform": "slack", "status": "configuration_required", "ok": False, "message": f"Set {BOT_TOKEN}."}
    if not channel or not text:
        return {"platform": "slack", "status": "invalid_args", "ok": False, "message": "channel and text are required."}
    try:
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
            json={"channel": channel, "text": text[:4000]},
            timeout=10,
        )
        data = resp.json() if resp.ok else {}
        if data.get("ok"):
            return {
                "platform": "slack",
                "status": "ok",
                "ok": True,
                "ts": data.get("ts"),
                "channel": data.get("channel"),
                "message": "Message posted via Slack Web API.",
            }
        return {
            "platform": "slack",
            "status": "error",
            "ok": False,
            "message": data.get("error") or f"Slack HTTP {resp.status_code}.",
        }
    except Exception as exc:
        return {"platform": "slack", "status": "error", "ok": False, "message": str(exc)[:200]}
