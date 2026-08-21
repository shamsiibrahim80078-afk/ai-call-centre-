"""Optional Agora Conversational AI / RTC presence.

LiveKit remains the primary multi-party video path for VERIDIQ meetings.
Agora App ID + Agent ID enable optional agent-presence metadata; production
RTC token minting needs an App Certificate
(``VERIDIQ_AGORA_APP_CERTIFICATE`` / ``AGORA_APP_CERTIFICATE``). Missing
certificate does **not** block LiveKit meetings.
"""

from __future__ import annotations

import time
from typing import Any, Optional, Union

from veridiq.calling.agora_token import ROLE_PUBLISHER, ROLE_SUBSCRIBER, build_rtc_token
from veridiq.integrations.base import first_env

APP_ID_KEYS = ("VERIDIQ_AGORA_APP_ID", "AGORA_APP_ID")
AGENT_ID_KEYS = ("VERIDIQ_AGORA_AGENT_ID", "AGORA_AGENT_ID")
CERT_KEYS = ("VERIDIQ_AGORA_APP_CERTIFICATE", "AGORA_APP_CERTIFICATE")


def agora_app_id() -> str:
    return (first_env(*APP_ID_KEYS) or "").strip()


def agora_agent_id() -> str:
    return (first_env(*AGENT_ID_KEYS) or "").strip()


def agora_app_certificate() -> str:
    return (first_env(*CERT_KEYS) or "").strip()


def agora_ids_configured() -> bool:
    return bool(agora_app_id() and agora_agent_id())


def agora_rtc_token_ready() -> bool:
    """True when App ID + App Certificate are present for signed RTC tokens."""
    return bool(agora_app_id() and agora_app_certificate())


def agora_status() -> dict[str, Any]:
    app_id = agora_app_id()
    agent_id = agora_agent_id()
    cert = agora_app_certificate()
    ids_ok = bool(app_id and agent_id)
    token_ready = bool(app_id and cert)
    if token_ready and ids_ok:
        message = (
            "Agora App ID + Agent ID + App Certificate present — "
            "optional Conversational AI / RTC agent presence can mint tokens. "
            "LiveKit remains primary for meetings."
        )
        mode = "rtc_ready"
    elif token_ready:
        message = (
            "Agora App ID + App Certificate present — RTC tokens can be minted. "
            "Agent ID optional for Conversational AI sidecar. "
            "LiveKit remains primary for meetings."
        )
        mode = "rtc_ready"
    elif ids_ok:
        message = (
            "Agora App ID + Agent ID set for optional Conversational AI presence. "
            "App Certificate missing — cannot mint production Agora RTC tokens yet. "
            "LiveKit remains the primary meeting video path."
        )
        mode = "agent_ids_only"
    elif app_id:
        message = (
            "Agora App ID set but Agent ID and/or App Certificate missing. "
            "LiveKit remains primary for meetings."
        )
        mode = "partial"
    else:
        message = (
            "Agora not configured (optional). Set VERIDIQ_AGORA_APP_ID + "
            "VERIDIQ_AGORA_AGENT_ID; add VERIDIQ_AGORA_APP_CERTIFICATE for RTC tokens. "
            "LiveKit is primary for meetings."
        )
        mode = "absent"

    return {
        "platform": "agora",
        "primary_video": "livekit",
        "configured": ids_ok or token_ready,
        "app_id_set": bool(app_id),
        "agent_id_set": bool(agent_id),
        "app_certificate_set": bool(cert),
        "rtc_token_ready": token_ready,
        "mode": mode,
        # Never return App ID / Agent ID / certificate values in API responses.
        "message": message,
        "optional": True,
        "blocks_livekit": False,
    }


def agora_meeting_sidecar(*, meeting_id: str, livekit_room: str) -> dict[str, Any]:
    """Metadata for optional Agora agent presence alongside a LiveKit room."""
    status = agora_status()
    if not (status["configured"] or status["rtc_token_ready"]):
        return {"enabled": False, **status}
    channel = f"veridiq-{meeting_id[:8]}"
    return {
        "enabled": True,
        "meeting_id": meeting_id,
        "livekit_room": livekit_room,
        "agora_channel_hint": channel,
        "agent_id_set": status["agent_id_set"],
        "rtc_token_ready": status["rtc_token_ready"],
        "mode": status["mode"],
        "message": status["message"],
        "note": (
            "Agora is optional sidecar / agent-assist; join/screen-share/video use LiveKit. "
            "POST /api/v1/veridiq/calling/agora/token to mint an Agora RTC token when certificate is set."
        ),
    }


def mint_agora_rtc_token(
    *,
    channel: str,
    uid: Union[int, str] = 0,
    role: str = "publisher",
    ttl_sec: int = 3600,
    identity: Optional[str] = None,
) -> dict[str, Any]:
    """Mint an Agora RTC AccessToken2. Never returns the App Certificate."""
    status = agora_status()
    if not agora_rtc_token_ready():
        return {
            "ok": False,
            "error": "agora_not_rtc_ready",
            "message": status["message"],
            "status": status,
        }

    channel = (channel or "").strip()
    if not channel:
        return {"ok": False, "error": "channel_required"}

    role_key = (role or "publisher").strip().lower()
    if role_key in ("subscriber", "audience", "viewer"):
        role_id = ROLE_SUBSCRIBER
        role_out = "subscriber"
    else:
        role_id = ROLE_PUBLISHER
        role_out = "publisher"

    account: Union[int, str]
    if identity and str(identity).strip():
        account = str(identity).strip()
    else:
        try:
            account = int(uid)
        except (TypeError, ValueError):
            account = str(uid) if uid not in (None, "") else 0

    ttl = max(60, min(int(ttl_sec or 3600), 86400))
    now = int(time.time())
    try:
        token = build_rtc_token(
            app_id=agora_app_id(),
            app_certificate=agora_app_certificate(),
            channel_name=channel,
            uid=account,
            role=role_id,
            token_expire_sec=ttl,
            privilege_expire_sec=ttl,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc) or "token_build_failed"}

    if not token:
        return {"ok": False, "error": "token_build_failed"}

    return {
        "ok": True,
        "token": token,
        "app_id_set": True,
        "channel": channel,
        "uid": account,
        "role": role_out,
        "expires_at": now + ttl,
        "ttl_sec": ttl,
        "primary_video": "livekit",
        "optional": True,
        "blocks_livekit": False,
    }
