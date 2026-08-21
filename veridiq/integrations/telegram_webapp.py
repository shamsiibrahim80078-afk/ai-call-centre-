"""Telegram Mini App (WebApp) initData validation + optional VERIDIQ session.

Official algorithm:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import parse_qsl

from veridiq.integrations import telegram

# Reject initData older than this (seconds). Telegram recommends checking auth_date.
DEFAULT_MAX_AGE_SEC = 86400  # 24h


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_init_data(init_data: str) -> dict[str, str]:
    """Parse Telegram ``initData`` query string into a flat string map."""
    raw = (init_data or "").strip()
    if not raw:
        return {}
    return {k: v for k, v in parse_qsl(raw, keep_blank_values=True)}


def build_data_check_string(fields: dict[str, str]) -> str:
    """Alphabetically sorted ``key=value`` lines excluding ``hash``."""
    pairs = [(k, v) for k, v in fields.items() if k != "hash"]
    pairs.sort(key=lambda item: item[0])
    return "\n".join(f"{k}={v}" for k, v in pairs)


def compute_webapp_hash(data_check_string: str, bot_token: str) -> str:
    """HMAC-SHA256 hex digest per Telegram WebApp validation rules."""
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def validate_init_data(
    init_data: str,
    *,
    bot_token: Optional[str] = None,
    max_age_sec: int = DEFAULT_MAX_AGE_SEC,
    now_ts: Optional[int] = None,
) -> dict[str, Any]:
    """Validate Mini App ``initData`` HMAC and optional freshness.

    Returns a dict with ``ok`` (bool). On success includes ``user`` (dict|None),
    ``auth_date``, ``query_id``, and raw ``fields``. On failure includes ``error``.
    """
    token = (bot_token if bot_token is not None else telegram.bot_token() or "").strip()
    if not token:
        return {
            "ok": False,
            "error": f"Set {telegram.BOT_TOKEN} to validate Telegram Mini App initData.",
        }

    fields = parse_init_data(init_data)
    if not fields:
        return {"ok": False, "error": "initData is empty or unparseable."}

    received_hash = (fields.get("hash") or "").strip().lower()
    if not received_hash:
        return {"ok": False, "error": "initData missing hash."}

    data_check = build_data_check_string(fields)
    expected = compute_webapp_hash(data_check, token)
    if not hmac.compare_digest(expected.lower(), received_hash):
        return {"ok": False, "error": "initData hash mismatch — not from this bot."}

    auth_raw = fields.get("auth_date") or ""
    try:
        auth_date = int(auth_raw)
    except (TypeError, ValueError):
        return {"ok": False, "error": "initData auth_date is invalid."}

    if max_age_sec > 0:
        now = int(now_ts if now_ts is not None else time.time())
        if auth_date > now + 60:
            return {"ok": False, "error": "initData auth_date is in the future."}
        if now - auth_date > max_age_sec:
            return {"ok": False, "error": "initData expired (auth_date too old)."}

    user: Optional[dict[str, Any]] = None
    user_raw = fields.get("user")
    if user_raw:
        try:
            parsed = json.loads(user_raw)
            if isinstance(parsed, dict):
                user = parsed
        except (TypeError, json.JSONDecodeError):
            return {"ok": False, "error": "initData user field is not valid JSON."}

    return {
        "ok": True,
        "user": user,
        "auth_date": auth_date,
        "query_id": fields.get("query_id"),
        "fields": fields,
    }


def upsert_user_from_telegram(tg_user: dict[str, Any]) -> dict[str, Any]:
    """Map a Telegram WebApp user onto ``veridiq_users`` (creates row if needed)."""
    from database import db_session, initialize_database
    from veridiq.auth.security import hash_password

    initialize_database()
    tg_id = tg_user.get("id")
    if tg_id is None:
        raise ValueError("Telegram user missing id")
    tg_id_str = str(int(tg_id))

    first = (tg_user.get("first_name") or "").strip()
    last = (tg_user.get("last_name") or "").strip()
    username = (tg_user.get("username") or "").strip()
    full_name = f"{first} {last}".strip() or username or f"Telegram {tg_id_str}"
    email_n = f"tg_{tg_id_str}@telegram.veridiq.local"
    stamped = _utc_now_iso()

    with db_session() as conn:
        row = conn.execute(
            "SELECT id, email, full_name, role FROM veridiq_users WHERE email = ?",
            (email_n,),
        ).fetchone()
        if row is None:
            pw_hash = hash_password(secrets.token_urlsafe(32))
            cur = conn.execute(
                """
                INSERT INTO veridiq_users (email, password_hash, full_name, role, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (email_n, pw_hash, full_name, "analyst", stamped),
            )
            return {
                "id": int(cur.lastrowid),
                "email": email_n,
                "full_name": full_name,
                "role": "analyst",
                "telegram_user_id": int(tg_id_str),
                "telegram_username": username or None,
                "auth_provider": "telegram_webapp",
            }

        if full_name and not (row["full_name"] or "").strip():
            conn.execute(
                "UPDATE veridiq_users SET full_name = ? WHERE id = ?",
                (full_name, int(row["id"])),
            )
        return {
            "id": int(row["id"]),
            "email": row["email"],
            "full_name": full_name or row["full_name"],
            "role": row["role"],
            "telegram_user_id": int(tg_id_str),
            "telegram_username": username or None,
            "auth_provider": "telegram_webapp",
        }


def authenticate_webapp(
    init_data: str,
    *,
    issue_session: bool = True,
    max_age_sec: int = DEFAULT_MAX_AGE_SEC,
) -> dict[str, Any]:
    """Validate initData; optionally upsert user and issue a VERIDIQ JWT."""
    checked = validate_init_data(init_data, max_age_sec=max_age_sec)
    if not checked.get("ok"):
        return checked

    tg_user = checked.get("user")
    public_user: Optional[dict[str, Any]] = None
    if isinstance(tg_user, dict):
        public_user = {
            "id": tg_user.get("id"),
            "first_name": tg_user.get("first_name"),
            "last_name": tg_user.get("last_name"),
            "username": tg_user.get("username"),
            "language_code": tg_user.get("language_code"),
            "is_premium": tg_user.get("is_premium"),
            "photo_url": tg_user.get("photo_url"),
        }

    out: dict[str, Any] = {
        "ok": True,
        "user": public_user,
        "auth_date": checked.get("auth_date"),
        "query_id": checked.get("query_id"),
    }

    if issue_session and isinstance(tg_user, dict) and tg_user.get("id") is not None:
        from veridiq.auth.security import issue_token

        local = upsert_user_from_telegram(tg_user)
        out["session_user"] = {
            "id": local["id"],
            "email": local["email"],
            "full_name": local["full_name"],
            "role": local["role"],
            "auth_provider": "telegram_webapp",
        }
        out["access_token"] = issue_token(local)
        out["token_type"] = "bearer"

    return out
