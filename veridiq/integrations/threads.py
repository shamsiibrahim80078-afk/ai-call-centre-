"""Threads integration — official Meta Threads API only. No scraping.

Docs: https://developers.facebook.com/docs/threads/
Publish flow: create container (POST /{user-id}/threads) then publish
(POST /{user-id}/threads_publish). Text posts use media_type=TEXT.

OAuth (APP_ID / APP_SECRET) is only for the authorization-code helper —
posting still requires VERIDIQ_THREADS_ACCESS_TOKEN + VERIDIQ_THREADS_USER_ID.
"""

from __future__ import annotations

import os
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from veridiq.integrations.base import status_shape

ACCESS_TOKEN = "VERIDIQ_THREADS_ACCESS_TOKEN"
THREADS_USER_ID = "VERIDIQ_THREADS_USER_ID"
APP_ID = "VERIDIQ_THREADS_APP_ID"
APP_SECRET = "VERIDIQ_THREADS_APP_SECRET"
REDIRECT_URI = "VERIDIQ_THREADS_REDIRECT_URI"
# Posting / live status still hinges on user token + user id.
ENV_VARS = [ACCESS_TOKEN, THREADS_USER_ID]
# App credentials used only by OAuth helpers (authorize URL / code exchange).
OAUTH_ENV_VARS = [APP_ID, APP_SECRET, REDIRECT_URI]
CAPABILITIES = [
    "profile_lookup (GET /me — threads_basic)",
    "publish_text (TEXT container + threads_publish — after explicit comms approval)",
    "publish_image (IMAGE container when image_url provided — after explicit comms approval)",
    "reply_to_post (reply_to_id on container create — after explicit comms approval)",
]
DOCS = "https://developers.facebook.com/docs/threads/"
API_BASE = "https://graph.threads.net/v1.0"
AUTH_URL = "https://threads.com/oauth/authorize"
TOKEN_URL = "https://graph.threads.net/oauth/access_token"
LONG_LIVED_TOKEN_URL = "https://graph.threads.net/access_token"
DEFAULT_REDIRECT_URI = "https://localhost/"
# threads_manage_replies unlocks reply/comment publishes via reply_to_id.
DEFAULT_SCOPES = "threads_basic,threads_content_publish,threads_manage_replies"
# Threads text posts are capped at 500 characters (UTF-8 byte length for emoji).
_TEXT_LIMIT = 500


def redirect_uri() -> str:
    return (os.getenv(REDIRECT_URI) or DEFAULT_REDIRECT_URI).strip() or DEFAULT_REDIRECT_URI


def authorize_url(*, scopes: str = DEFAULT_SCOPES, state: Optional[str] = None) -> str:
    """Build the Threads Authorization Window URL (needs APP_ID)."""
    client_id = (os.getenv(APP_ID) or "").strip()
    if not client_id:
        raise ValueError(f"Set {APP_ID} to build the Threads authorize URL.")
    params: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "scope": scopes,
        "response_type": "code",
    }
    if state:
        params["state"] = state
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str, *, long_lived: bool = True) -> dict[str, Any]:
    """Exchange an OAuth authorization `code` for access_token (+ user_id).

    Short-lived token first (POST oauth/access_token), then optionally upgrade
    to a long-lived token (GET access_token?grant_type=th_exchange_token).
    Does not publish anything.
    """
    client_id = (os.getenv(APP_ID) or "").strip()
    client_secret = (os.getenv(APP_SECRET) or "").strip()
    missing = [n for n, v in [(APP_ID, client_id), (APP_SECRET, client_secret)] if not v]
    if missing:
        return {"status": "configuration_required", "message": f"Set {', '.join(missing)} to exchange a code."}
    auth_code = (code or "").strip().rstrip("#_")
    if not auth_code:
        return {"status": "error", "message": "Authorization code is empty."}

    try:
        short = requests.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri(),
                "code": auth_code,
            },
            timeout=20,
        )
    except Exception as exc:
        return {"status": "error", "message": f"Threads token exchange unreachable: {str(exc)[:200]}"}

    if short.status_code not in (200, 201):
        return {
            "status": "error",
            "api_response_status": short.status_code,
            "message": f"Threads code exchange failed: HTTP {short.status_code} {short.text[:200]}",
        }

    payload = short.json() or {}
    access_token = payload.get("access_token")
    user_id = payload.get("user_id")
    if not access_token:
        return {"status": "error", "message": "Threads code exchange returned no access_token."}

    result: dict[str, Any] = {
        "status": "ok",
        "access_token": access_token,
        "user_id": str(user_id) if user_id is not None else None,
        "token_type": payload.get("token_type") or "bearer",
        "expires_in": payload.get("expires_in"),
        "long_lived": False,
    }

    if long_lived:
        try:
            long_resp = requests.get(
                LONG_LIVED_TOKEN_URL,
                params={
                    "grant_type": "th_exchange_token",
                    "client_secret": client_secret,
                    "access_token": access_token,
                },
                timeout=20,
            )
            if long_resp.status_code in (200, 201):
                long_payload = long_resp.json() or {}
                if long_payload.get("access_token"):
                    result["access_token"] = long_payload["access_token"]
                    result["expires_in"] = long_payload.get("expires_in") or result.get("expires_in")
                    result["long_lived"] = True
            else:
                result["long_lived_warning"] = (
                    f"Long-lived upgrade failed HTTP {long_resp.status_code}; using short-lived token."
                )
        except Exception as exc:
            result["long_lived_warning"] = f"Long-lived upgrade unreachable: {str(exc)[:200]}"

    return result


def status() -> dict[str, Any]:
    token = os.getenv(ACCESS_TOKEN)
    if not token:
        return status_shape(
            "threads",
            "Threads (Meta)",
            "social",
            status="configuration_required",
            configured=False,
            message=(
                f"Set {ACCESS_TOKEN} (Threads user access token with threads_basic) "
                f"and {THREADS_USER_ID} to enable official Threads API calls."
            ),
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    return status_shape(
        "threads",
        "Threads (Meta)",
        "social",
        status="configured",
        configured=True,
        message="Access token present — use /test to verify with a live call. Publishing also needs "
        f"{THREADS_USER_ID}.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def test_connection() -> dict[str, Any]:
    token = os.getenv(ACCESS_TOKEN)
    if not token:
        return {
            "platform": "threads",
            "status": "configuration_required",
            "message": f"Set {ACCESS_TOKEN} to run a live test.",
        }
    try:
        resp = requests.get(
            f"{API_BASE}/me",
            params={"fields": "id,username", "access_token": token},
            timeout=6,
        )
        if resp.status_code == 200:
            data = resp.json() or {}
            return {
                "platform": "threads",
                "status": "ok",
                "api_response_status": resp.status_code,
                "threads_user_id": data.get("id"),
                "message": f"Verified Threads account @{data.get('username', '?')} (id {data.get('id', '?')}).",
            }
        return {
            "platform": "threads",
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"Threads API returned HTTP {resp.status_code}: {resp.text[:200]}",
        }
    except Exception as exc:
        return {"platform": "threads", "status": "error", "message": f"Threads API unreachable: {str(exc)[:200]}"}


def publish_text(
    *,
    text: str,
    image_url: Optional[str] = None,
    reply_to_id: Optional[str] = None,
) -> dict[str, Any]:
    """Publish a real Threads post (or reply) via the official Meta Threads API.

    Only ever invoked after explicit approval of a comms draft
    (`veridiq.comms.assistant.approve_external_action`, channel="threads"
    or "threads_comment").

    Two-step container flow per Meta docs:
      1. POST /{threads-user-id}/threads  (media_type TEXT or IMAGE; optional reply_to_id)
      2. POST /{threads-user-id}/threads_publish  (creation_id)
    """
    token = os.getenv(ACCESS_TOKEN)
    user_id = os.getenv(THREADS_USER_ID)
    missing = [name for name, val in [(ACCESS_TOKEN, token), (THREADS_USER_ID, user_id)] if not val]
    if missing:
        return {
            "status": "configuration_required",
            "message": f"Set {', '.join(missing)} (Threads API) to publish to Threads.",
        }
    content = (text or "").strip()
    image = (image_url or "").strip()
    parent_id = (reply_to_id or "").strip()
    if not content and not image:
        return {"status": "error", "message": "Threads post text is empty — nothing to publish."}

    create_data: dict[str, Any] = {"access_token": token}
    if image:
        create_data["media_type"] = "IMAGE"
        create_data["image_url"] = image
        if content:
            create_data["text"] = content[:_TEXT_LIMIT]
    else:
        create_data["media_type"] = "TEXT"
        create_data["text"] = content[:_TEXT_LIMIT]
    if parent_id:
        create_data["reply_to_id"] = parent_id

    try:
        create = requests.post(
            f"{API_BASE}/{user_id}/threads",
            data=create_data,
            timeout=15,
        )
        if create.status_code not in (200, 201):
            return {
                "status": "error",
                "api_response_status": create.status_code,
                "message": f"Threads container create failed: HTTP {create.status_code} {create.text[:200]}",
            }
        container_id = (create.json() or {}).get("id")
        if not container_id:
            return {
                "status": "error",
                "message": "Threads container create returned no id — cannot publish.",
            }
        publish = requests.post(
            f"{API_BASE}/{user_id}/threads_publish",
            data={"creation_id": container_id, "access_token": token},
            timeout=15,
        )
        if publish.status_code in (200, 201):
            media_id = (publish.json() or {}).get("id")
            kind = "reply" if parent_id else "post"
            return {
                "status": "ok",
                "media_id": media_id,
                "creation_id": container_id,
                "reply_to_id": parent_id or None,
                "message": f"Threads {kind} published (id {media_id}).",
            }
        return {
            "status": "error",
            "api_response_status": publish.status_code,
            "message": f"Threads publish failed: HTTP {publish.status_code} {publish.text[:200]}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Threads publish failed: {str(exc)[:200]}"}


def reply_to_post(*, text: str, reply_to_id: str) -> dict[str, Any]:
    """Reply/comment on an existing Threads media id (official reply_to_id flow)."""
    parent = (reply_to_id or "").strip()
    if not parent:
        return {
            "status": "unsupported",
            "message": "Threads reply needs reply_to_id (parent Threads media id) in recipient_hint.",
        }
    return publish_text(text=text, reply_to_id=parent)
