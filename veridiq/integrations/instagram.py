"""Instagram integration — official Instagram Graph API only. No scraping."""

from __future__ import annotations

import os
from typing import Any

import requests

from veridiq.integrations.base import status_shape

ACCESS_TOKEN = "VERIDIQ_INSTAGRAM_ACCESS_TOKEN"
IG_USER_ID = "VERIDIQ_INSTAGRAM_USER_ID"
ENV_VARS = [ACCESS_TOKEN, IG_USER_ID]
CAPABILITIES = [
    "profile_lookup",
    "media_publish (business accounts, image required — after explicit comms approval)",
    "reply_to_comment (business accounts, replies to an existing comment on your own media only — "
    "the Graph API does not support creating a new top-level comment on another account's post)",
]
DOCS = "https://developers.facebook.com/docs/instagram-api/"


def status() -> dict[str, Any]:
    token = os.getenv(ACCESS_TOKEN)
    if not token:
        return status_shape(
            "instagram",
            "Instagram",
            "social",
            status="configuration_required",
            configured=False,
            message=f"Set {ACCESS_TOKEN} (Instagram Graph API access token) to enable official Instagram calls.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    return status_shape(
        "instagram",
        "Instagram",
        "social",
        status="configured",
        configured=True,
        message="Access token present — use /test to verify with a live call.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def test_connection() -> dict[str, Any]:
    token = os.getenv(ACCESS_TOKEN)
    if not token:
        return {
            "platform": "instagram",
            "status": "configuration_required",
            "message": f"Set {ACCESS_TOKEN} to run a live test.",
        }
    try:
        resp = requests.get(
            "https://graph.instagram.com/me",
            params={"fields": "id,username", "access_token": token},
            timeout=6,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "platform": "instagram",
                "status": "ok",
                "api_response_status": resp.status_code,
                "message": f"Verified Instagram account @{data.get('username', '?')}.",
            }
        return {
            "platform": "instagram",
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"Instagram API returned HTTP {resp.status_code}.",
        }
    except Exception as exc:
        return {"platform": "instagram", "status": "error", "message": f"Instagram API unreachable: {str(exc)[:200]}"}


def publish_media(*, caption: str, image_url: str) -> dict[str, Any]:
    """Publish a real post via the official Instagram Graph API (business accounts only).

    Only ever invoked after explicit approval of a comms draft
    (`veridiq.comms.assistant.approve_external_action`, channel="instagram").
    Instagram's Graph API has no text-only post type, so a public `image_url`
    is required — this is reported as a request error, never as a fabricated
    "configured" state.
    """
    token = os.getenv(ACCESS_TOKEN)
    ig_user_id = os.getenv(IG_USER_ID)
    missing = [name for name, val in [(ACCESS_TOKEN, token), (IG_USER_ID, ig_user_id)] if not val]
    if missing:
        return {
            "status": "configuration_required",
            "message": f"Set {', '.join(missing)} (Instagram Business Account) to publish to Instagram.",
        }
    if not (image_url or "").strip():
        return {
            "status": "error",
            "message": "Instagram Graph API requires an image_url for feed posts — text-only posts are not supported.",
        }
    try:
        create = requests.post(
            f"https://graph.facebook.com/v19.0/{ig_user_id}/media",
            data={"image_url": image_url, "caption": (caption or "")[:2200], "access_token": token},
            timeout=10,
        )
        if create.status_code not in (200, 201):
            return {
                "status": "error",
                "api_response_status": create.status_code,
                "message": f"Instagram media create failed: HTTP {create.status_code} {create.text[:200]}",
            }
        container_id = (create.json() or {}).get("id")
        publish = requests.post(
            f"https://graph.facebook.com/v19.0/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": token},
            timeout=10,
        )
        if publish.status_code in (200, 201):
            media_id = (publish.json() or {}).get("id")
            return {"status": "ok", "media_id": media_id, "message": f"Instagram post published (id {media_id})."}
        return {
            "status": "error",
            "api_response_status": publish.status_code,
            "message": f"Instagram publish failed: HTTP {publish.status_code} {publish.text[:200]}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Instagram publish failed: {str(exc)[:200]}"}


def reply_to_comment(*, comment_id: str, message: str) -> dict[str, Any]:
    """Reply to an existing comment on the connected business account's own
    media via the official Instagram Graph API (`POST /{comment-id}/replies`).

    Only ever invoked after explicit approval of a comms draft
    (`veridiq.comms.assistant.approve_external_action`, channel="instagram_comment").
    Instagram's Graph API has no way to create a brand-new top-level comment
    on someone else's media — that's a platform limitation, not a
    misconfiguration, so a missing `comment_id` is reported as `unsupported`
    rather than fabricating a successful comment.
    """
    token = os.getenv(ACCESS_TOKEN)
    if not token:
        return {"status": "configuration_required", "message": f"Set {ACCESS_TOKEN} to reply to Instagram comments."}
    comment_id = (comment_id or "").strip()
    if not comment_id:
        return {
            "status": "unsupported",
            "message": (
                "Instagram Graph API does not support creating a new top-level comment on another account's "
                "media — it only supports replying to an existing comment on your own business account's "
                "media. Provide comment_id (an existing comment id on your media) to reply."
            ),
        }
    content = (message or "").strip()
    if not content:
        return {"status": "error", "message": "Reply text is empty — nothing to publish."}
    try:
        resp = requests.post(
            f"https://graph.facebook.com/v19.0/{comment_id}/replies",
            data={"message": content[:2200], "access_token": token},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            reply_id = (resp.json() or {}).get("id")
            return {"status": "ok", "reply_id": reply_id, "message": f"Instagram reply published (id {reply_id})."}
        return {
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"Instagram reply failed: HTTP {resp.status_code} {resp.text[:200]}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Instagram reply failed: {str(exc)[:200]}"}
