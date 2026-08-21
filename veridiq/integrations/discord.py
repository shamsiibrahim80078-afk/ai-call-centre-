"""Discord connector — official Discord Bot API via VERIDIQ service layer."""

from __future__ import annotations

import os
from typing import Any

import requests

from veridiq.integrations.base import status_shape

BOT_TOKEN = "VERIDIQ_DISCORD_BOT_TOKEN"
ENV_VARS = [BOT_TOKEN]
CAPABILITIES = ["get_current_user", "send_channel_message (after explicit approval)"]
DOCS = "https://discord.com/developers/docs/intro"


def status() -> dict[str, Any]:
    if not os.getenv(BOT_TOKEN):
        return status_shape(
            "discord",
            "Discord",
            "comms",
            status="configuration_required",
            configured=False,
            message=f"Set {BOT_TOKEN} for official Discord Bot API access.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    return status_shape(
        "discord",
        "Discord",
        "comms",
        status="configured",
        configured=True,
        message="Discord bot token present — use /test to verify with a live call.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def test_connection() -> dict[str, Any]:
    token = os.getenv(BOT_TOKEN)
    if not token:
        return {"platform": "discord", "status": "configuration_required", "message": f"Set {BOT_TOKEN}."}
    try:
        resp = requests.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bot {token}"},
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "platform": "discord",
                "status": "ok",
                "api_response_status": resp.status_code,
                "message": f"Verified Discord bot @{data.get('username')}.",
            }
        return {
            "platform": "discord",
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"Discord API HTTP {resp.status_code}.",
        }
    except Exception as exc:
        return {"platform": "discord", "status": "error", "message": str(exc)[:200]}


def send_message(*, channel_id: str, content: str, **_kwargs: Any) -> dict[str, Any]:
    """Send a channel message via official Discord Bot API (explicit invoke only)."""
    token = os.getenv(BOT_TOKEN)
    if not token:
        return {"platform": "discord", "status": "configuration_required", "ok": False, "message": f"Set {BOT_TOKEN}."}
    if not channel_id or not content:
        return {
            "platform": "discord",
            "status": "invalid_args",
            "ok": False,
            "message": "channel_id and content are required.",
        }
    try:
        resp = requests.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
            json={"content": str(content)[:2000]},
            timeout=10,
        )
        if resp.status_code in {200, 201}:
            data = resp.json()
            return {
                "platform": "discord",
                "status": "ok",
                "ok": True,
                "message_id": data.get("id"),
                "message": "Message posted via Discord Bot API.",
            }
        return {
            "platform": "discord",
            "status": "error",
            "ok": False,
            "api_response_status": resp.status_code,
            "message": f"Discord API HTTP {resp.status_code}.",
        }
    except Exception as exc:
        return {"platform": "discord", "status": "error", "ok": False, "message": str(exc)[:200]}
