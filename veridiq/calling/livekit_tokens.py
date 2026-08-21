"""LiveKit access-token minting for VERIDIQ meetings.

Uses PyJWT (already in requirements) with the LiveKit Cloud JWT grant shape.
Credentials: prefer ``VERIDIQ_LIVEKIT_*``, fall back to ``LIVEKIT_*``.
Never logs or returns the API secret.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import jwt

from veridiq.integrations.base import first_env

URL_KEYS = ("VERIDIQ_LIVEKIT_URL", "LIVEKIT_URL")
KEY_KEYS = ("VERIDIQ_LIVEKIT_API_KEY", "LIVEKIT_API_KEY")
SECRET_KEYS = ("VERIDIQ_LIVEKIT_API_SECRET", "LIVEKIT_API_SECRET")


def livekit_url() -> str:
    return (first_env(*URL_KEYS) or "").strip()


def livekit_api_key() -> str:
    return (first_env(*KEY_KEYS) or "").strip()


def livekit_api_secret() -> str:
    return (first_env(*SECRET_KEYS) or "").strip()


def livekit_configured() -> bool:
    return bool(livekit_url() and livekit_api_key() and livekit_api_secret())


def livekit_status() -> dict[str, Any]:
    configured = livekit_configured()
    return {
        "configured": configured,
        "url": livekit_url() if configured else "",
        "api_key_set": bool(livekit_api_key()),
        "api_secret_set": bool(livekit_api_secret()),
        "message": (
            "LiveKit Cloud credentials ready — tokens can be minted."
            if configured
            else "Set VERIDIQ_LIVEKIT_URL / VERIDIQ_LIVEKIT_API_KEY / VERIDIQ_LIVEKIT_API_SECRET "
            "(or LIVEKIT_* aliases) in .env."
        ),
    }


def mint_access_token(
    *,
    identity: str,
    room_name: str,
    name: Optional[str] = None,
    ttl_sec: int = 7200,
    can_publish: bool = True,
    can_subscribe: bool = True,
    can_publish_data: bool = True,
    room_join: bool = True,
) -> dict[str, Any]:
    """Mint a LiveKit access JWT for ``identity`` to join ``room_name``."""
    if not livekit_configured():
        return {
            "ok": False,
            "error": "livekit_not_configured",
            "message": livekit_status()["message"],
        }
    identity = (identity or "").strip()
    room_name = (room_name or "").strip()
    if not identity or not room_name:
        return {"ok": False, "error": "identity_and_room_required"}

    api_key = livekit_api_key()
    api_secret = livekit_api_secret()
    now = int(time.time())
    ttl = max(60, min(int(ttl_sec or 7200), 86400))
    payload: dict[str, Any] = {
        "iss": api_key,
        "sub": identity,
        "nbf": now - 5,
        "exp": now + ttl,
        "video": {
            "roomJoin": bool(room_join),
            "room": room_name,
            "canPublish": bool(can_publish),
            "canSubscribe": bool(can_subscribe),
            "canPublishData": bool(can_publish_data),
        },
    }
    display = (name or identity).strip()
    if display:
        payload["name"] = display

    token = jwt.encode(payload, api_secret, algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return {
        "ok": True,
        "token": token,
        "url": livekit_url(),
        "identity": identity,
        "name": display,
        "room": room_name,
        "expires_at": now + ttl,
        "ttl_sec": ttl,
    }
