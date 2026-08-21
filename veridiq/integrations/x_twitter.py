"""X (Twitter) integration — official X API v2 only. No scraping."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
import uuid as uuidlib
from typing import Any
from urllib.parse import quote

import requests

from veridiq.integrations.base import first_env, status_shape

BEARER_TOKEN = "VERIDIQ_X_BEARER_TOKEN"
API_KEY = "VERIDIQ_X_API_KEY"
API_SECRET = "VERIDIQ_X_API_SECRET"
TEST_USERNAME = "VERIDIQ_X_TEST_USERNAME"
ACCESS_TOKEN = "VERIDIQ_X_ACCESS_TOKEN"
ACCESS_TOKEN_SECRET = "VERIDIQ_X_ACCESS_TOKEN_SECRET"

ENV_VARS = [BEARER_TOKEN, API_KEY, API_SECRET]
POST_ENV_VARS = [API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]
CAPABILITIES = [
    "user_lookup",
    "recent_search (access-tier dependent)",
    "post_tweet (OAuth 1.0a user context — after explicit comms approval)",
    "reply_tweet / comment on a tweet (OAuth 1.0a user context — after explicit comms approval)",
]
DOCS = "https://developer.x.com/"


def status() -> dict[str, Any]:
    token = first_env(BEARER_TOKEN)
    if not token:
        return status_shape(
            "x_twitter",
            "X (Twitter)",
            "social",
            status="configuration_required",
            configured=False,
            message=f"Set {BEARER_TOKEN} (App-only Bearer Token from the official X Developer Portal).",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    return status_shape(
        "x_twitter",
        "X (Twitter)",
        "social",
        status="configured",
        configured=True,
        message="Bearer token present — use /test to verify with a live call.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def test_connection() -> dict[str, Any]:
    token = os.getenv(BEARER_TOKEN)
    if not token:
        return {
            "platform": "x_twitter",
            "status": "configuration_required",
            "message": f"Set {BEARER_TOKEN} to run a live test.",
        }
    username = os.getenv(TEST_USERNAME, "veridiq")
    try:
        resp = requests.get(
            f"https://api.twitter.com/2/users/by/username/{username}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=6,
        )
        if resp.status_code == 200:
            return {
                "platform": "x_twitter",
                "status": "ok",
                "api_response_status": resp.status_code,
                "message": "X API bearer token verified with a live lookup.",
            }
        return {
            "platform": "x_twitter",
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"X API returned HTTP {resp.status_code}.",
        }
    except Exception as exc:
        return {"platform": "x_twitter", "status": "error", "message": f"X API unreachable: {str(exc)[:200]}"}


def _oauth1_percent_encode(value: str) -> str:
    return quote(str(value), safe="~")


def _oauth1_header(
    method: str,
    url: str,
    *,
    consumer_key: str,
    consumer_secret: str,
    token: str,
    token_secret: str,
) -> str:
    """Build an OAuth 1.0a `Authorization` header (HMAC-SHA1) — no third-party
    signing library required. Used for X API v2 endpoints that require
    user-context authentication (posting tweets)."""
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": uuidlib.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    param_str = "&".join(
        f"{_oauth1_percent_encode(k)}={_oauth1_percent_encode(v)}" for k, v in sorted(oauth_params.items())
    )
    base_str = "&".join(
        [method.upper(), _oauth1_percent_encode(url), _oauth1_percent_encode(param_str)]
    )
    signing_key = f"{_oauth1_percent_encode(consumer_secret)}&{_oauth1_percent_encode(token_secret)}"
    signature = base64.b64encode(hmac.new(signing_key.encode(), base_str.encode(), hashlib.sha1).digest()).decode()
    oauth_params["oauth_signature"] = signature
    return "OAuth " + ", ".join(
        f'{_oauth1_percent_encode(k)}="{_oauth1_percent_encode(v)}"' for k, v in sorted(oauth_params.items())
    )


def _missing_post_creds() -> list[str]:
    return [
        name
        for name, val in [
            (API_KEY, os.getenv(API_KEY)),
            (API_SECRET, os.getenv(API_SECRET)),
            (ACCESS_TOKEN, os.getenv(ACCESS_TOKEN)),
            (ACCESS_TOKEN_SECRET, os.getenv(ACCESS_TOKEN_SECRET)),
        ]
        if not val
    ]


def _publish_tweet(body: dict[str, Any], *, action: str) -> dict[str, Any]:
    """Shared OAuth1.0a `POST /2/tweets` call used by both new tweets and replies."""
    missing = _missing_post_creds()
    if missing:
        return {
            "status": "configuration_required",
            "message": f"Set {', '.join(missing)} (OAuth 1.0a user-context credentials) to {action}.",
        }
    consumer_key = os.getenv(API_KEY)
    consumer_secret = os.getenv(API_SECRET)
    token = os.getenv(ACCESS_TOKEN)
    token_secret = os.getenv(ACCESS_TOKEN_SECRET)
    url = "https://api.twitter.com/2/tweets"
    header = _oauth1_header(
        "POST", url, consumer_key=consumer_key, consumer_secret=consumer_secret, token=token, token_secret=token_secret
    )
    try:
        resp = requests.post(
            url,
            headers={"Authorization": header, "Content-Type": "application/json"},
            json=body,
            timeout=10,
        )
        if resp.status_code in (200, 201):
            data = (resp.json() or {}).get("data") or {}
            return {"status": "ok", "tweet_id": data.get("id"), "message": f"Tweet posted (id {data.get('id')})."}
        return {
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"X publish failed: HTTP {resp.status_code} {resp.text[:200]}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"X publish failed: {str(exc)[:200]}"}


def post_tweet(text: str) -> dict[str, Any]:
    """Publish a real tweet via the official X API v2 (`POST /2/tweets`).

    Only ever invoked after explicit approval of a comms draft
    (`veridiq.comms.assistant.approve_external_action`, channel="x_twitter").
    Posting requires user-context OAuth 1.0a credentials (app-only bearer
    tokens cannot create tweets) — never fabricates a successful post.
    """
    content = (text or "").strip()
    if not content:
        return {"status": "error", "message": "Tweet text is empty — nothing to publish."}
    return _publish_tweet({"text": content[:280]}, action="publish tweets")


def reply_tweet(*, text: str, in_reply_to_tweet_id: str) -> dict[str, Any]:
    """Publish a real reply/comment on an existing tweet via `POST /2/tweets`
    with `reply.in_reply_to_tweet_id` — the official X API v2 mechanism for
    commenting on a post. Same OAuth 1.0a user-context requirement and
    approval gate as `post_tweet`; never fabricates a successful comment.
    """
    if not (in_reply_to_tweet_id or "").strip():
        return {"status": "error", "message": "in_reply_to_tweet_id is required to reply/comment on a tweet."}
    content = (text or "").strip()
    if not content:
        return {"status": "error", "message": "Reply text is empty — nothing to publish."}
    return _publish_tweet(
        {"text": content[:280], "reply": {"in_reply_to_tweet_id": in_reply_to_tweet_id.strip()}},
        action="reply to/comment on tweets",
    )
