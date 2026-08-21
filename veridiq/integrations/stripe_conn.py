"""Stripe — status only until a valid sk_/pk_ key is provided."""

from __future__ import annotations

from typing import Any

from veridiq.integrations.base import first_env, status_shape
from veridiq.integrations.llm._common import http_get_json

PLATFORM = "stripe"
DISPLAY = "Stripe"
CATEGORY = "payments"
ENV_VARS = (
    "VERIDIQ_STRIPE_SECRET_KEY",
    "VERIDIQ_STRIPE_PUBLISHABLE_KEY",
    "VERIDIQ_STRIPE_KEY_RAW",
)
CAPABILITIES = ["status"]
DOCS = "https://docs.stripe.com/api"


def _valid_secret() -> str | None:
    return first_env("VERIDIQ_STRIPE_SECRET_KEY", "STRIPE_SECRET_KEY")


def _valid_publishable() -> str | None:
    return first_env("VERIDIQ_STRIPE_PUBLISHABLE_KEY", "STRIPE_PUBLISHABLE_KEY")


def _raw() -> str | None:
    return first_env("VERIDIQ_STRIPE_KEY_RAW")


def _looks_like_stripe(key: str | None) -> bool:
    if not key:
        return False
    return key.startswith("sk_test_") or key.startswith("sk_live_") or key.startswith("pk_test_") or key.startswith("pk_live_")


def status() -> dict[str, Any]:
    sk = _valid_secret()
    pk = _valid_publishable()
    raw = _raw()
    if _looks_like_stripe(sk) or (_looks_like_stripe(pk) and sk is None):
        # Prefer secret for server; publishable alone is client-side only
        if _looks_like_stripe(sk):
            return status_shape(
                PLATFORM,
                DISPLAY,
                CATEGORY,
                status="configured",
                configured=True,
                message="Valid Stripe secret key shape present — use /test to verify.",
                env_vars=ENV_VARS,
                capabilities=CAPABILITIES + ["balance_probe"],
                docs_url=DOCS,
            )
        return status_shape(
            PLATFORM,
            DISPLAY,
            CATEGORY,
            status="configuration_required",
            configured=False,
            message="Publishable key alone is insufficient for server actions. Set VERIDIQ_STRIPE_SECRET_KEY (sk_test_/sk_live_).",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    if raw and not _looks_like_stripe(raw):
        return status_shape(
            PLATFORM,
            DISPLAY,
            CATEGORY,
            status="configuration_required",
            configured=False,
            message=(
                "VERIDIQ_STRIPE_KEY_RAW is set but does not look like a Stripe sk_/pk_ key "
                "(expected sk_test_/sk_live_ or pk_test_/pk_live_). Stored for operator review only."
            ),
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
            extra={"raw_key_present": True, "valid_key_shape": False},
        )
    return status_shape(
        PLATFORM,
        DISPLAY,
        CATEGORY,
        status="configuration_required",
        configured=False,
        message="Set VERIDIQ_STRIPE_SECRET_KEY (sk_test_/sk_live_) for Stripe. No charges until configured.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def test_connection() -> dict[str, Any]:
    sk = _valid_secret()
    raw = _raw()
    if not _looks_like_stripe(sk):
        if raw and not _looks_like_stripe(raw):
            return {
                "platform": PLATFORM,
                "status": "configuration_required",
                "ok": False,
                "message": "Raw key present but invalid Stripe shape (need sk_test_/sk_live_). No live Stripe call attempted.",
                "valid_key_shape": False,
            }
        return {
            "platform": PLATFORM,
            "status": "configuration_required",
            "ok": False,
            "message": "Set VERIDIQ_STRIPE_SECRET_KEY (sk_test_/sk_live_).",
        }
    resp, data, exc = http_get_json(
        "https://api.stripe.com/v1/balance",
        headers={"Authorization": f"Bearer {sk}"},
        timeout=12,
    )
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    if resp.status_code == 200:
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "message": "Stripe balance endpoint reachable.",
            "livemode": (data or {}).get("livemode"),
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": f"Stripe HTTP {resp.status_code}.",
    }
