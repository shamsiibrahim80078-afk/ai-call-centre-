"""Clerk — status, Backend API probe, and JWT bridge notes.

Browser auth uses @clerk/clerk-react + /api/v1/auth/clerk/sync.
FastAPI HS256 JWTs remain the API session after sync; Clerk RS256 is also accepted.
"""

from __future__ import annotations

from typing import Any

from veridiq.integrations.base import first_env, status_shape
from veridiq.integrations.llm._common import http_get_json

PLATFORM = "clerk"
DISPLAY = "Clerk"
CATEGORY = "auth"
ENV_VARS = (
    "VERIDIQ_CLERK_PUBLISHABLE_KEY",
    "VERIDIQ_CLERK_SECRET_KEY",
    "VITE_CLERK_PUBLISHABLE_KEY",
)
CAPABILITIES = ["status", "sign_in", "sign_up", "optional_jwt_verify_stub", "jwks_verify"]
DOCS = "https://clerk.com/docs"


def status() -> dict[str, Any]:
    pk = first_env("VERIDIQ_CLERK_PUBLISHABLE_KEY", "CLERK_PUBLISHABLE_KEY", "VITE_CLERK_PUBLISHABLE_KEY")
    sk = first_env("VERIDIQ_CLERK_SECRET_KEY", "CLERK_SECRET_KEY")
    if not pk and not sk:
        return status_shape(
            PLATFORM,
            DISPLAY,
            CATEGORY,
            status="configuration_required",
            configured=False,
            message="Set VERIDIQ_CLERK_PUBLISHABLE_KEY / VERIDIQ_CLERK_SECRET_KEY (+ VITE_CLERK_PUBLISHABLE_KEY for Vite).",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
            extra={"auth_policy": "clerk_ui_plus_fastapi_jwt"},
        )
    missing = []
    if not pk:
        missing.append("publishable")
    if not sk:
        missing.append("secret")
    if missing:
        return status_shape(
            PLATFORM,
            DISPLAY,
            CATEGORY,
            status="configuration_required",
            configured=False,
            message=f"Clerk partial config (missing: {', '.join(missing)}).",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
            extra={
                "auth_policy": "clerk_ui_plus_fastapi_jwt",
                "publishable_set": bool(pk),
                "secret_set": bool(sk),
            },
        )
    return status_shape(
        PLATFORM,
        DISPLAY,
        CATEGORY,
        status="configured",
        configured=True,
        message=(
            "Clerk development keys (pk_test_) — local OK; production needs pk_live_/sk_live_."
            if (pk or "").startswith("pk_test_")
            else "Clerk keys present — use /sign-in and /sign-up; API sync at /api/v1/auth/clerk/sync."
        ),
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
        extra={
            "auth_policy": "clerk_ui_plus_fastapi_jwt",
            "publishable_set": True,
            "secret_set": True,
            "key_mode": (
                "live"
                if (pk or "").startswith("pk_live_")
                else "test"
                if (pk or "").startswith("pk_test_")
                else "unknown"
            ),
            "production_ready": (pk or "").startswith("pk_live_") and (sk or "").startswith("sk_live_"),
        },
    )


def test_connection() -> dict[str, Any]:
    sk = first_env("VERIDIQ_CLERK_SECRET_KEY", "CLERK_SECRET_KEY")
    if not sk:
        return {
            "platform": PLATFORM,
            "status": "configuration_required",
            "ok": False,
            "message": "Set VERIDIQ_CLERK_SECRET_KEY to probe Clerk Backend API.",
        }
    resp, data, exc = http_get_json(
        "https://api.clerk.com/v1/users",
        headers={"Authorization": f"Bearer {sk}", "Content-Type": "application/json"},
        params={"limit": 1},
        timeout=12,
    )
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    if resp.status_code == 200:
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            count = len(data["data"])
        elif isinstance(data, dict) and "id" in data:
            count = 1
        else:
            count = 0
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "message": f"Clerk Backend API reachable (users probe, sample={count}).",
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": f"Clerk HTTP {resp.status_code}.",
    }


def optional_jwt_verify_stub(*, token: str = "", **_kwargs: Any) -> dict[str, Any]:
    """Shape check + optional real JWKS verify when cryptography + keys are present."""
    sk = first_env("VERIDIQ_CLERK_SECRET_KEY", "CLERK_SECRET_KEY")
    if not sk:
        return {
            "platform": PLATFORM,
            "status": "configuration_required",
            "ok": False,
            "message": "Set VERIDIQ_CLERK_SECRET_KEY.",
            "auth_policy": "clerk_ui_plus_fastapi_jwt",
        }
    t = (token or "").strip()
    if not t:
        return {
            "platform": PLATFORM,
            "status": "invalid_args",
            "ok": False,
            "message": "token is required for optional_jwt_verify_stub.",
            "auth_policy": "clerk_ui_plus_fastapi_jwt",
            "verified": False,
        }
    parts = t.split(".")
    if len(parts) != 3:
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "verified": False,
            "message": "Token is not a JWT (3 segments).",
            "auth_policy": "clerk_ui_plus_fastapi_jwt",
            "full_jwks_verification": False,
        }
    try:
        from veridiq.auth.clerk_jwt import verify_clerk_token

        claims = verify_clerk_token(t)
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "verified": True,
            "message": "Clerk JWKS verification succeeded.",
            "auth_policy": "clerk_ui_plus_fastapi_jwt",
            "full_jwks_verification": True,
            "sub": claims.get("sub"),
        }
    except Exception as exc:
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "verified": False,
            "message": f"JWT shape OK; JWKS verify failed: {exc}",
            "auth_policy": "clerk_ui_plus_fastapi_jwt",
            # Attempted, but did not succeed — callers must not treat this as verified.
            "full_jwks_verification": False,
            "segments": 3,
        }
