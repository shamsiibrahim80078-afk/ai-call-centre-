"""VERIDIQ authentication — JWT sessions, password hashing, role checks."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import db_session, initialize_database  # noqa: E402

security = HTTPBearer(auto_error=False)

JWT_SECRET = os.getenv("VERIDIQ_JWT_SECRET", "veridiq-dev-secret-change-me")
JWT_ALG = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("VERIDIQ_JWT_EXPIRE_HOURS", "24"))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_user(email: str, password: str, full_name: str = "", role: str = "analyst") -> dict[str, Any]:
    initialize_database()
    email_n = email.strip().lower()
    if not email_n or "@" not in email_n:
        raise ValueError("valid email required")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    stamped = _utc_now().replace(microsecond=0).isoformat()
    with db_session() as conn:
        existing = conn.execute("SELECT id FROM veridiq_users WHERE email = ?", (email_n,)).fetchone()
        if existing:
            raise ValueError("email already registered")
        cur = conn.execute(
            """
            INSERT INTO veridiq_users (email, password_hash, full_name, role, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (email_n, hash_password(password), full_name.strip(), role, stamped),
        )
        return {"id": int(cur.lastrowid), "email": email_n, "full_name": full_name, "role": role}


def authenticate_user(email: str, password: str) -> dict[str, Any]:
    initialize_database()
    email_n = email.strip().lower()
    with db_session() as conn:
        row = conn.execute("SELECT * FROM veridiq_users WHERE email = ?", (email_n,)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        raise ValueError("invalid credentials")
    return {
        "id": int(row["id"]),
        "email": row["email"],
        "full_name": row["full_name"],
        "role": row["role"],
    }


def issue_token(user: dict[str, Any]) -> str:
    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "role": user.get("role") or "analyst",
        "exp": _utc_now() + timedelta(hours=JWT_EXPIRE_HOURS),
        "iat": _utc_now(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"invalid token: {exc}") from exc


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict[str, Any]:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="authentication required")
    token = credentials.credentials
    # Prefer native VERIDIQ HS256 JWT; fall back to optional Clerk RS256 session JWT.
    try:
        data = decode_token(token)
    except HTTPException:
        try:
            from veridiq.auth.clerk_jwt import try_decode_as_clerk

            clerk_user = try_decode_as_clerk(token)
        except Exception:
            clerk_user = None
        if clerk_user:
            return {
                "id": clerk_user["id"],
                "email": clerk_user["email"],
                "full_name": clerk_user.get("full_name"),
                "role": clerk_user.get("role") or "analyst",
            }
        raise
    with db_session() as conn:
        row = conn.execute(
            "SELECT id, email, full_name, role FROM veridiq_users WHERE id = ?",
            (int(data["sub"]),),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="user not found")
    return dict(row)


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict[str, Any]]:
    if credentials is None or not credentials.credentials:
        return None
    try:
        return get_current_user(credentials)
    except HTTPException:
        return None


def ensure_bootstrap_admin() -> None:
    initialize_database()
    with db_session() as conn:
        row = conn.execute("SELECT id FROM veridiq_users WHERE email = ?", ("admin@veridiq.ai",)).fetchone()
        if row:
            return
    create_user("admin@veridiq.ai", "VeridiqAdmin!23", full_name="VERIDIQ Admin", role="admin")
