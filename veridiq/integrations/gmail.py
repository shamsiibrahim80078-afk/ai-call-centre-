"""Gmail connector — official Gmail API (OAuth 2.0) via VERIDIQ service layer."""

from __future__ import annotations

import os
from typing import Any

import requests

from veridiq.integrations.base import status_shape

CLIENT_ID = "VERIDIQ_GMAIL_CLIENT_ID"
CLIENT_SECRET = "VERIDIQ_GMAIL_CLIENT_SECRET"
ACCESS_TOKEN = "VERIDIQ_GMAIL_ACCESS_TOKEN"
ENV_VARS = [CLIENT_ID, CLIENT_SECRET, ACCESS_TOKEN]
CAPABILITIES = ["profile", "list_messages (readonly)", "send (after explicit approval — not auto)"]
DOCS = "https://developers.google.com/gmail/api"


def status() -> dict[str, Any]:
    if not (os.getenv(CLIENT_ID) and os.getenv(CLIENT_SECRET)):
        return status_shape(
            "gmail",
            "Gmail",
            "productivity",
            status="configuration_required",
            configured=False,
            message=f"Set {CLIENT_ID} and {CLIENT_SECRET} for official Gmail OAuth.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    token = os.getenv(ACCESS_TOKEN)
    return status_shape(
        "gmail",
        "Gmail",
        "productivity",
        status="configured",
        configured=True,
        message="OAuth client configured." + (" Access token present." if token else f" Set {ACCESS_TOKEN} for live calls."),
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def test_connection() -> dict[str, Any]:
    token = os.getenv(ACCESS_TOKEN)
    if not token:
        return {"platform": "gmail", "status": "configuration_required", "message": f"Set {ACCESS_TOKEN}."}
    try:
        resp = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "platform": "gmail",
                "status": "ok",
                "api_response_status": resp.status_code,
                "message": f"Verified Gmail for {data.get('emailAddress', 'user')}.",
            }
        return {
            "platform": "gmail",
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"Gmail API HTTP {resp.status_code}.",
        }
    except Exception as exc:
        return {"platform": "gmail", "status": "error", "message": str(exc)[:200]}


def list_messages(*, max_results: int = 5, q: str = "", **_kwargs: Any) -> dict[str, Any]:
    """List recent messages via official Gmail API (readonly)."""
    token = os.getenv(ACCESS_TOKEN)
    if not token:
        return {"platform": "gmail", "status": "configuration_required", "ok": False, "message": f"Set {ACCESS_TOKEN}."}
    try:
        params: dict[str, Any] = {"maxResults": max(1, min(20, int(max_results)))}
        if q:
            params["q"] = q
        resp = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=10,
        )
        if resp.status_code != 200:
            return {
                "platform": "gmail",
                "status": "error",
                "ok": False,
                "api_response_status": resp.status_code,
                "message": f"Gmail API HTTP {resp.status_code}.",
            }
        messages = (resp.json() or {}).get("messages") or []
        return {
            "platform": "gmail",
            "status": "ok",
            "ok": True,
            "count": len(messages),
            "messages": messages,
            "message": f"Listed {len(messages)} message id(s).",
        }
    except Exception as exc:
        return {"platform": "gmail", "status": "error", "ok": False, "message": str(exc)[:200]}
