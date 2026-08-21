"""LinkedIn integration — official LinkedIn API (OAuth 2.0) only. No scraping."""

from __future__ import annotations

import os
from typing import Any, Optional
from urllib.parse import quote

import requests

from veridiq.integrations.base import status_shape

CLIENT_ID = "VERIDIQ_LINKEDIN_CLIENT_ID"
CLIENT_SECRET = "VERIDIQ_LINKEDIN_CLIENT_SECRET"
ACCESS_TOKEN = "VERIDIQ_LINKEDIN_ACCESS_TOKEN"
PERSON_URN = "VERIDIQ_LINKEDIN_PERSON_URN"

ENV_VARS = [CLIENT_ID, CLIENT_SECRET, ACCESS_TOKEN]
CAPABILITIES = [
    "profile_lookup (OpenID userinfo)",
    "share_post (w_member_social, requires member token — after explicit comms approval)",
    "comment_on_post (Social Actions API — typically requires Marketing Developer Platform access "
    "beyond basic w_member_social; reports configuration_required/error honestly if the token lacks it)",
]
DOCS = "https://learn.microsoft.com/linkedin/"


def status() -> dict[str, Any]:
    client_id = os.getenv(CLIENT_ID)
    client_secret = os.getenv(CLIENT_SECRET)
    token = os.getenv(ACCESS_TOKEN)
    if not (client_id and client_secret):
        return status_shape(
            "linkedin",
            "LinkedIn",
            "social",
            status="configuration_required",
            configured=False,
            message=f"Set {CLIENT_ID} and {CLIENT_SECRET} to register the official LinkedIn OAuth 2.0 app.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    return status_shape(
        "linkedin",
        "LinkedIn",
        "social",
        status="configured",
        configured=True,
        message=(
            "OAuth token present — use /test to verify with a live call."
            if token
            else f"OAuth client configured. Complete the member OAuth flow and set {ACCESS_TOKEN} to enable live calls."
        ),
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def test_connection() -> dict[str, Any]:
    token = os.getenv(ACCESS_TOKEN)
    if not token:
        return {
            "platform": "linkedin",
            "status": "configuration_required",
            "message": f"Set {ACCESS_TOKEN} to run a live test.",
        }
    try:
        resp = requests.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=6,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "platform": "linkedin",
                "status": "ok",
                "api_response_status": resp.status_code,
                "message": f"Verified LinkedIn token for {data.get('name', 'member')}.",
            }
        return {
            "platform": "linkedin",
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"LinkedIn API returned HTTP {resp.status_code}.",
        }
    except Exception as exc:
        return {"platform": "linkedin", "status": "error", "message": f"LinkedIn API unreachable: {str(exc)[:200]}"}


def _resolve_author_urn(token: str) -> Optional[str]:
    """Resolve the member URN required as `author` on a UGC post.

    Prefers an explicit `VERIDIQ_LINKEDIN_PERSON_URN` (org/member URN can vary
    by API product); falls back to the OpenID `sub` claim from `/v2/userinfo`.
    """
    explicit = os.getenv(PERSON_URN)
    if explicit:
        return explicit if explicit.startswith("urn:li:") else f"urn:li:person:{explicit}"
    try:
        resp = requests.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=6,
        )
        if resp.status_code == 200:
            sub = resp.json().get("sub")
            if sub:
                return f"urn:li:person:{sub}"
    except Exception:
        pass
    return None


def share_post(text: str) -> dict[str, Any]:
    """Publish a real post via the official LinkedIn UGC Posts API (w_member_social).

    Only ever invoked after explicit approval of a comms draft
    (`veridiq.comms.assistant.approve_external_action`, channel="linkedin").
    Never fabricates a successful post — any non-2xx response or missing
    credential is reported honestly.
    """
    token = os.getenv(ACCESS_TOKEN)
    if not token:
        return {"status": "configuration_required", "message": f"Set {ACCESS_TOKEN} to publish LinkedIn posts."}
    content = (text or "").strip()
    if not content:
        return {"status": "error", "message": "Post text is empty — nothing to publish."}

    author = _resolve_author_urn(token)
    if not author:
        return {
            "status": "configuration_required",
            "message": (
                f"Could not resolve a LinkedIn member URN from the access token. "
                f"Set {PERSON_URN} explicitly (e.g. urn:li:person:XXXX) to publish."
            ),
        }

    payload = {
        "author": author,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": content[:3000]},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    try:
        resp = requests.post(
            "https://api.linkedin.com/v2/ugcPosts",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            json=payload,
            timeout=10,
        )
        if resp.status_code in (200, 201):
            post_id = resp.headers.get("x-restli-id") or resp.headers.get("X-RestLi-Id")
            return {"status": "ok", "post_id": post_id, "message": f"LinkedIn post published (id {post_id})."}
        return {
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"LinkedIn publish failed: HTTP {resp.status_code} {resp.text[:200]}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"LinkedIn publish failed: {str(exc)[:200]}"}


def comment_on_post(*, post_urn: str, text: str) -> dict[str, Any]:
    """Comment on an existing LinkedIn post via the official Social Actions API
    (`POST /v2/socialActions/{urn}/comments`).

    Only ever invoked after explicit approval of a comms draft
    (`veridiq.comms.assistant.approve_external_action`, channel="linkedin_comment").
    This endpoint typically requires LinkedIn Marketing Developer Platform
    access beyond the basic `w_member_social` scope used for `share_post` —
    a 401/403 from LinkedIn is reported honestly as `configuration_required`
    rather than fabricating a successful comment.
    """
    token = os.getenv(ACCESS_TOKEN)
    if not token:
        return {"status": "configuration_required", "message": f"Set {ACCESS_TOKEN} to comment on LinkedIn posts."}
    urn = (post_urn or "").strip()
    if not urn:
        return {
            "status": "error",
            "message": "post_urn (the LinkedIn share/post URN to comment on, e.g. urn:li:share:XXXX) is required.",
        }
    content = (text or "").strip()
    if not content:
        return {"status": "error", "message": "Comment text is empty — nothing to publish."}
    author = _resolve_author_urn(token)
    if not author:
        return {
            "status": "configuration_required",
            "message": f"Could not resolve a LinkedIn member URN from the access token. Set {PERSON_URN} explicitly.",
        }
    url = f"https://api.linkedin.com/v2/socialActions/{quote(urn, safe='')}/comments"
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            json={"actor": author, "object": urn, "message": {"text": content[:1250]}},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return {"status": "ok", "message": "LinkedIn comment published."}
        if resp.status_code in (401, 403):
            return {
                "status": "configuration_required",
                "api_response_status": resp.status_code,
                "message": (
                    "LinkedIn rejected the comment request (HTTP "
                    f"{resp.status_code}). Commenting via the Social Actions API usually requires Marketing "
                    "Developer Platform / Community Management API access beyond basic w_member_social — "
                    f"request that access from LinkedIn, or comment manually. {resp.text[:200]}"
                ),
            }
        return {
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"LinkedIn comment failed: HTTP {resp.status_code} {resp.text[:200]}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"LinkedIn comment failed: {str(exc)[:200]}"}
