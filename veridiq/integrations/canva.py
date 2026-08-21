"""Canva integration — official Canva Connect API only. No scraping.

https://www.canva.dev/docs/connect/
"""

from __future__ import annotations

import os
from typing import Any

import requests

from veridiq.integrations.base import status_shape

CLIENT_ID = "VERIDIQ_CANVA_CLIENT_ID"
CLIENT_SECRET = "VERIDIQ_CANVA_CLIENT_SECRET"
ACCESS_TOKEN = "VERIDIQ_CANVA_ACCESS_TOKEN"

ENV_VARS = [CLIENT_ID, CLIENT_SECRET, ACCESS_TOKEN]
CAPABILITIES = [
    "create_design (POST /v1/designs — after explicit comms approval)",
    "get_design (poll edit_url/thumbnail)",
]
DOCS = "https://www.canva.dev/docs/connect/"

_PRESET_TYPES = {"doc", "whiteboard", "presentation"}


def status() -> dict[str, Any]:
    client_id = os.getenv(CLIENT_ID)
    client_secret = os.getenv(CLIENT_SECRET)
    token = os.getenv(ACCESS_TOKEN)
    if not (client_id and client_secret):
        return status_shape(
            "canva",
            "Canva",
            "creative",
            status="configuration_required",
            configured=False,
            message=f"Set {CLIENT_ID} and {CLIENT_SECRET} to register the official Canva Connect app.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    return status_shape(
        "canva",
        "Canva",
        "creative",
        status="configured" if token else "configuration_required",
        configured=bool(token),
        message=(
            "OAuth token present — use /test to verify with a live call."
            if token
            else f"Canva Connect app configured. Complete the OAuth 2.0 flow and set {ACCESS_TOKEN} to create designs."
        ),
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def test_connection() -> dict[str, Any]:
    token = os.getenv(ACCESS_TOKEN)
    if not token:
        return {"platform": "canva", "status": "configuration_required", "message": f"Set {ACCESS_TOKEN} to run a live test."}
    try:
        resp = requests.get(
            "https://api.canva.com/rest/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
        if resp.status_code == 200:
            return {
                "platform": "canva",
                "status": "ok",
                "api_response_status": resp.status_code,
                "message": "Canva Connect access token verified with a live lookup.",
            }
        return {
            "platform": "canva",
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"Canva API returned HTTP {resp.status_code}: {resp.text[:200]}",
        }
    except Exception as exc:
        return {"platform": "canva", "status": "error", "message": f"Canva API unreachable: {str(exc)[:200]}"}


def create_design(
    *,
    title: str,
    design_type: str = "custom",
    width: int = 1080,
    height: int = 1080,
) -> dict[str, Any]:
    """Create a real design via the official Canva Connect API
    (`POST /v1/designs`) — never fabricates a design id or edit URL.

    `design_type` is either one of the official presets (`doc`, `whiteboard`,
    `presentation`) or `custom` (with `width`/`height` in px, 40-8000 each).
    """
    token = os.getenv(ACCESS_TOKEN)
    if not token:
        return {
            "status": "configuration_required",
            "message": f"Set {ACCESS_TOKEN} (Canva Connect OAuth 2.0 access token, scope design:content:write) to create designs.",
        }
    if design_type in _PRESET_TYPES:
        dt: dict[str, Any] = {"type": "preset", "name": design_type}
    else:
        w = max(40, min(8000, int(width or 1080)))
        h = max(40, min(8000, int(height or 1080)))
        dt = {"type": "custom", "width": w, "height": h}
    try:
        resp = requests.post(
            "https://api.canva.com/rest/v1/designs",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"design_type": dt, "title": (title or "VERIDIQ Marketing Creative")[:255]},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            data = (resp.json() or {}).get("design") or {}
            urls = data.get("urls") or {}
            return {
                "status": "ok",
                "design_id": data.get("id"),
                "edit_url": urls.get("edit_url"),
                "view_url": urls.get("view_url"),
                "message": f"Canva design created (id {data.get('id')}). Open edit_url to finish it in Canva.",
            }
        if resp.status_code in (401, 403):
            return {
                "status": "configuration_required",
                "api_response_status": resp.status_code,
                "message": f"Canva rejected the request (HTTP {resp.status_code}) — token may be expired or missing the design:content:write scope. {resp.text[:200]}",
            }
        return {
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"Canva design create failed: HTTP {resp.status_code} {resp.text[:200]}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Canva design create failed: {str(exc)[:200]}"}


def get_design(design_id: str) -> dict[str, Any]:
    token = os.getenv(ACCESS_TOKEN)
    if not token:
        return {"status": "configuration_required", "message": f"Set {ACCESS_TOKEN} to look up a Canva design."}
    if not (design_id or "").strip():
        return {"status": "error", "message": "design_id is required."}
    try:
        resp = requests.get(
            f"https://api.canva.com/rest/v1/designs/{design_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = (resp.json() or {}).get("design") or {}
            return {"status": "ok", "design": data}
        return {
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"Canva get design failed: HTTP {resp.status_code} {resp.text[:200]}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Canva get design failed: {str(exc)[:200]}"}
