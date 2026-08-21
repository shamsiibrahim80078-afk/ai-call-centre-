"""Google Drive connector — official Drive API via VERIDIQ service layer."""

from __future__ import annotations

import os
from typing import Any

import requests

from veridiq.integrations.base import status_shape

CLIENT_ID = "VERIDIQ_GOOGLE_DRIVE_CLIENT_ID"
CLIENT_SECRET = "VERIDIQ_GOOGLE_DRIVE_CLIENT_SECRET"
ACCESS_TOKEN = "VERIDIQ_GOOGLE_DRIVE_ACCESS_TOKEN"
ENV_VARS = [CLIENT_ID, CLIENT_SECRET, ACCESS_TOKEN]
CAPABILITIES = ["list_files", "upload (after explicit approval)"]
DOCS = "https://developers.google.com/drive/api"


def status() -> dict[str, Any]:
    if not (os.getenv(CLIENT_ID) and os.getenv(CLIENT_SECRET)):
        return status_shape(
            "google_drive",
            "Google Drive",
            "productivity",
            status="configuration_required",
            configured=False,
            message=f"Set {CLIENT_ID} and {CLIENT_SECRET} for official Drive OAuth.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    return status_shape(
        "google_drive",
        "Google Drive",
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
        return {"platform": "google_drive", "status": "configuration_required", "message": f"Set {ACCESS_TOKEN}."}
    try:
        resp = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            headers={"Authorization": f"Bearer {token}"},
            params={"pageSize": 3, "fields": "files(id,name)"},
            timeout=8,
        )
        if resp.status_code == 200:
            files = (resp.json() or {}).get("files") or []
            return {
                "platform": "google_drive",
                "status": "ok",
                "api_response_status": resp.status_code,
                "message": f"Verified Drive access — {len(files)} file(s) listed.",
            }
        return {
            "platform": "google_drive",
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"Drive API HTTP {resp.status_code}.",
        }
    except Exception as exc:
        return {"platform": "google_drive", "status": "error", "message": str(exc)[:200]}


def list_files(*, page_size: int = 10, **_kwargs: Any) -> dict[str, Any]:
    token = os.getenv(ACCESS_TOKEN)
    if not token:
        return {
            "platform": "google_drive",
            "status": "configuration_required",
            "ok": False,
            "message": f"Set {ACCESS_TOKEN}.",
        }
    try:
        resp = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            headers={"Authorization": f"Bearer {token}"},
            params={"pageSize": max(1, min(30, int(page_size))), "fields": "files(id,name,mimeType,modifiedTime)"},
            timeout=10,
        )
        if resp.status_code != 200:
            return {
                "platform": "google_drive",
                "status": "error",
                "ok": False,
                "api_response_status": resp.status_code,
                "message": f"Drive API HTTP {resp.status_code}.",
            }
        files = (resp.json() or {}).get("files") or []
        return {
            "platform": "google_drive",
            "status": "ok",
            "ok": True,
            "count": len(files),
            "files": files,
            "message": f"Listed {len(files)} file(s).",
        }
    except Exception as exc:
        return {"platform": "google_drive", "status": "error", "ok": False, "message": str(exc)[:200]}
