"""Optional Clerk session JWT verification (JWKS) alongside FastAPI HS256 JWTs."""

from __future__ import annotations

import base64
import secrets
from functools import lru_cache
from typing import Any, Optional

import jwt
from jwt import PyJWKClient

from veridiq.integrations.base import first_env


def clerk_publishable_key() -> Optional[str]:
    return first_env(
        "VERIDIQ_CLERK_PUBLISHABLE_KEY",
        "CLERK_PUBLISHABLE_KEY",
        "VITE_CLERK_PUBLISHABLE_KEY",
    )


def clerk_secret_key() -> Optional[str]:
    return first_env("VERIDIQ_CLERK_SECRET_KEY", "CLERK_SECRET_KEY")


def clerk_frontend_api() -> Optional[str]:
    """Frontend API host, e.g. worthy-hedge-12.clerk.accounts.dev."""
    explicit = first_env(
        "VERIDIQ_CLERK_FRONTEND_API",
        "CLERK_FRONTEND_API",
        "CLERK_JWT_ISSUER",
    )
    if explicit:
        host = explicit.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
        return host or None
    pk = clerk_publishable_key()
    if not pk:
        return None
    try:
        # pk_test_<base64url(frontend_api + "$")>
        raw = pk.split("_", 2)[-1]
        padded = raw + "=" * (-len(raw) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        return decoded.rstrip("$").strip() or None
    except Exception:
        return None


def clerk_configured() -> bool:
    return bool(clerk_publishable_key() and clerk_secret_key())


@lru_cache(maxsize=4)
def _jwks_client(frontend_api: str) -> PyJWKClient:
    return PyJWKClient(f"https://{frontend_api}/.well-known/jwks.json", cache_keys=True)


# Allow local clock skew vs Clerk (iat/nbf/exp). Common when host clock is slightly behind.
CLERK_JWT_LEEWAY_SEC = 120


def verify_clerk_token(token: str) -> dict[str, Any]:
    """Verify a Clerk session JWT via JWKS. Raises jwt.PyJWTError on failure."""
    fapi = clerk_frontend_api()
    if not fapi:
        raise jwt.InvalidTokenError("Clerk frontend API not configured")
    client = _jwks_client(fapi)
    signing_key = client.get_signing_key_from_jwt(token)
    issuer = f"https://{fapi}"
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        issuer=issuer,
        leeway=CLERK_JWT_LEEWAY_SEC,
        options={"verify_aud": False},
    )


def fetch_clerk_user(clerk_user_id: str) -> Optional[dict[str, Any]]:
    """Fetch user profile from Clerk Backend API (needs secret key)."""
    sk = clerk_secret_key()
    if not sk or not clerk_user_id:
        return None
    try:
        import requests

        resp = requests.get(
            f"https://api.clerk.com/v1/users/{clerk_user_id}",
            headers={"Authorization": f"Bearer {sk}"},
            timeout=12,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _email_from_clerk_user(data: dict[str, Any]) -> str:
    emails = data.get("email_addresses") or []
    primary_id = data.get("primary_email_address_id")
    if primary_id and isinstance(emails, list):
        for item in emails:
            if isinstance(item, dict) and item.get("id") == primary_id and item.get("email_address"):
                return str(item["email_address"]).strip().lower()
    if isinstance(emails, list):
        for item in emails:
            if isinstance(item, dict) and item.get("email_address"):
                return str(item["email_address"]).strip().lower()
    return ""


def _name_from_clerk_user(data: dict[str, Any]) -> str:
    first = (data.get("first_name") or "").strip()
    last = (data.get("last_name") or "").strip()
    full = f"{first} {last}".strip()
    if full:
        return full
    return (data.get("username") or "").strip()


def upsert_user_from_clerk(
    *,
    clerk_user_id: str,
    email: str = "",
    full_name: str = "",
) -> dict[str, Any]:
    """Map a Clerk identity onto veridiq_users (creates row if needed)."""
    from database import db_session, initialize_database

    initialize_database()
    email_n = (email or "").strip().lower()
    name = (full_name or "").strip()
    cid = (clerk_user_id or "").strip()
    if not cid:
        raise ValueError("clerk_user_id required")

    if not email_n or not name:
        remote = fetch_clerk_user(cid)
        if remote:
            email_n = email_n or _email_from_clerk_user(remote)
            name = name or _name_from_clerk_user(remote)

    if not email_n:
        email_n = f"{cid}@clerk.users"

    from datetime import datetime, timezone

    from .security import hash_password, issue_token

    stamped = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    with db_session() as conn:
        row = conn.execute(
            "SELECT id, email, full_name, role, clerk_user_id FROM veridiq_users WHERE clerk_user_id = ?",
            (cid,),
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT id, email, full_name, role, clerk_user_id FROM veridiq_users WHERE email = ?",
                (email_n,),
            ).fetchone()

        if row is None:
            # Unusable local password — Clerk is the credential store.
            pw_hash = hash_password(secrets.token_urlsafe(32))
            cur = conn.execute(
                """
                INSERT INTO veridiq_users (email, password_hash, full_name, role, created_at, clerk_user_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (email_n, pw_hash, name or "Clerk User", "analyst", stamped, cid),
            )
            return {
                "id": int(cur.lastrowid),
                "email": email_n,
                "full_name": name or "Clerk User",
                "role": "analyst",
                "clerk_user_id": cid,
                "auth_provider": "clerk",
            }

        updates: list[str] = []
        params: list[Any] = []
        if not row["clerk_user_id"]:
            updates.append("clerk_user_id = ?")
            params.append(cid)
        if name and not (row["full_name"] or "").strip():
            updates.append("full_name = ?")
            params.append(name)
        if updates:
            params.append(int(row["id"]))
            conn.execute(
                f"UPDATE veridiq_users SET {', '.join(updates)} WHERE id = ?",
                params,
            )
        return {
            "id": int(row["id"]),
            "email": row["email"],
            "full_name": name or row["full_name"],
            "role": row["role"],
            "clerk_user_id": cid,
            "auth_provider": "clerk",
        }


def sync_clerk_session(token: str, *, email: str = "", full_name: str = "") -> dict[str, Any]:
    """Verify Clerk JWT, upsert local user, issue VERIDIQ access token."""
    from .security import issue_token

    claims = verify_clerk_token(token)
    sub = str(claims.get("sub") or "").strip()
    if not sub:
        raise ValueError("Clerk token missing sub")
    # Prefer claim email when JWT template includes it
    claim_email = str(claims.get("email") or claims.get("primary_email_address") or "").strip()
    user = upsert_user_from_clerk(
        clerk_user_id=sub,
        email=email or claim_email,
        full_name=full_name,
    )
    return {
        "user": user,
        "access_token": issue_token(user),
        "token_type": "bearer",
        "auth_provider": "clerk",
    }


def try_decode_as_clerk(token: str) -> Optional[dict[str, Any]]:
    """Return local user dict if token is a valid Clerk JWT; else None."""
    if not clerk_frontend_api():
        return None
    # Fast reject: Clerk uses RS256 (header alg) — local uses HS256
    try:
        header = jwt.get_unverified_header(token)
    except Exception:
        return None
    if header.get("alg") != "RS256":
        return None
    try:
        claims = verify_clerk_token(token)
        sub = str(claims.get("sub") or "").strip()
        if not sub:
            return None
        user = upsert_user_from_clerk(clerk_user_id=sub)
        return user
    except Exception:
        return None
