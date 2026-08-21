"""Timed voice-call sessions — schedule, start, auto-end at budget limits.

Async-friendly: ``schedule_timed_call`` returns immediately; the calling worker
loop advances sessions without blocking FastAPI request threads.

LiveKit invite / meeting flows are untouched — this module only manages the
timed budget ledger + optional Twilio dial when a campaign is approved separately.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from database import db_session

from veridiq.calling import budget as calling_budget
from veridiq.calling.chain_hooks import intent_to_json, record_call_intent

logger = logging.getLogger("veridiq.calling.timed_calls")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: Optional[datetime] = None) -> str:
    return (dt or _utc_now()).replace(microsecond=0).isoformat()


def _row_to_session(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d.pop("id", None)
    raw = d.pop("chain_intent_json", None)
    try:
        d["chain_intent"] = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        d["chain_intent"] = None
    return d


def schedule_timed_call(
    *,
    purpose: str = "Timed AI calling session",
    script: str = "",
    to_number: str = "",
    requested_seconds: Optional[int] = None,
    agent_type: str = "ai_calling",
    user_key: str = "default",
    record_chain: bool = True,
) -> dict[str, Any]:
    """Queue a timed call. Does not dial immediately — worker or start_session activates it."""
    calling_budget._ensure_tables()
    clamp = calling_budget.clamp_requested_seconds(
        requested_seconds, agent_type=agent_type, user_key=user_key
    )
    if not clamp.get("ok"):
        return {
            "ok": False,
            "status": "budget_exhausted",
            "message": clamp.get("message"),
            "budget": clamp,
        }

    session_id = f"tcall-{uuid.uuid4().hex[:12]}"
    now = _utc_iso()
    allowed = int(clamp["allowed_seconds"])
    chain: Optional[dict[str, Any]] = None
    if record_chain:
        try:
            chain = record_call_intent(
                session_id=session_id,
                agent_type=agent_type,
                user_key=user_key,
                purpose=purpose,
                allowed_seconds=allowed,
                metadata={"to_number": to_number[:40] if to_number else None},
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("chain intent failed for %s", session_id)
            chain = {"ok": False, "status": "error", "message": str(exc)[:200]}

    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO veridiq_calling_timed_sessions
                (session_id, agent_type, user_key, purpose, script, to_number, status,
                 requested_seconds, allowed_seconds, consumed_seconds, chain_intent_json,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'scheduled', ?, ?, 0, ?, ?, ?)
            """,
            (
                session_id,
                agent_type,
                user_key,
                (purpose or "")[:400],
                (script or "")[:4000],
                (to_number or "")[:40],
                int(clamp["requested_seconds"]),
                allowed,
                intent_to_json(chain) if chain else None,
                now,
                now,
            ),
        )

    session = get_session(session_id)
    logger.info("scheduled timed call %s allowed=%ss", session_id, allowed)
    return {
        "ok": True,
        "status": "scheduled",
        "message": (
            f"Timed call scheduled for up to {allowed}s "
            f"(per-call max {clamp['per_call_max_seconds']}s; "
            f"daily remaining after this: {max(0, clamp['remaining_seconds'] - allowed):.0f}s)."
        ),
        "session": session,
        "budget": clamp,
        "chain": chain,
    }


def get_session(session_id: str) -> Optional[dict[str, Any]]:
    calling_budget._ensure_tables()
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM veridiq_calling_timed_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return _row_to_session(row) if row else None


def list_sessions(
    *,
    agent_type: Optional[str] = None,
    user_key: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    calling_budget._ensure_tables()
    query = "SELECT * FROM veridiq_calling_timed_sessions WHERE 1=1"
    params: list[Any] = []
    if agent_type:
        query += " AND agent_type = ?"
        params.append(agent_type)
    if user_key:
        query += " AND user_key = ?"
        params.append(user_key)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(200, int(limit))))
    with db_session() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [_row_to_session(r) for r in rows]


def start_session(session_id: str) -> dict[str, Any]:
    """Mark a scheduled session active. Enforces remaining daily budget at start time."""
    session = get_session(session_id)
    if not session:
        return {"ok": False, "status": "error", "message": "unknown session_id"}
    if session["status"] not in {"scheduled", "queued"}:
        return {
            "ok": False,
            "status": "invalid_state",
            "message": f"session is {session['status']}, expected scheduled",
            "session": session,
        }

    clamp = calling_budget.clamp_requested_seconds(
        int(session["allowed_seconds"]),
        agent_type=session["agent_type"],
        user_key=session["user_key"],
    )
    if not clamp.get("ok"):
        with db_session() as conn:
            conn.execute(
                """
                UPDATE veridiq_calling_timed_sessions
                SET status = 'budget_blocked', error = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (clamp.get("message"), _utc_iso(), session_id),
            )
        return {
            "ok": False,
            "status": "budget_exhausted",
            "message": clamp.get("message"),
            "session": get_session(session_id),
            "budget": clamp,
        }

    allowed = int(clamp["allowed_seconds"])
    now = _utc_iso()
    with db_session() as conn:
        conn.execute(
            """
            UPDATE veridiq_calling_timed_sessions
            SET status = 'active', started_at = ?, allowed_seconds = ?,
                updated_at = ?, error = NULL
            WHERE session_id = ?
            """,
            (now, allowed, now, session_id),
        )
    logger.info("started timed call %s allowed=%ss", session_id, allowed)
    return {
        "ok": True,
        "status": "active",
        "message": f"Call active — hard stop at {allowed}s (daily + per-call budget).",
        "session": get_session(session_id),
        "budget": clamp,
    }


def end_session(
    session_id: str,
    *,
    reason: str = "completed",
    consumed_override: Optional[float] = None,
) -> dict[str, Any]:
    """End an active/scheduled session and charge daily budget for elapsed time.

    Pass ``consumed_override=0`` to cancel without charging (failed / abandoned joins).
    Sessions that never left ``scheduled`` are cancelled with zero charge by default.
    """
    session = get_session(session_id)
    if not session:
        return {"ok": False, "status": "error", "message": "unknown session_id"}
    if session["status"] in {"completed", "expired", "cancelled", "failed"}:
        return {"ok": True, "status": session["status"], "session": session, "message": "already closed"}

    now_dt = _utc_now()
    started = session.get("started_at")
    elapsed = 0.0
    if consumed_override is not None:
        elapsed = max(0.0, float(consumed_override))
    elif started:
        try:
            start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            elapsed = max(0.0, (now_dt - start_dt).total_seconds())
        except ValueError:
            elapsed = 0.0
    elif session["status"] in {"scheduled", "queued", "budget_blocked"}:
        # Never connected — do not charge
        elapsed = 0.0

    allowed = float(session.get("allowed_seconds") or calling_budget.max_call_seconds())
    consumed = min(elapsed, allowed)
    status = "expired" if reason == "budget_timeout" or (elapsed >= allowed and allowed > 0 and started) else (
        "cancelled" if reason == "cancelled" else "completed"
    )
    if reason == "failed":
        status = "failed"

    if consumed > 0:
        calling_budget.record_consumption(
            seconds=consumed,
            agent_type=session["agent_type"],
            user_key=session["user_key"],
        )
    now = _utc_iso(now_dt)
    with db_session() as conn:
        conn.execute(
            """
            UPDATE veridiq_calling_timed_sessions
            SET status = ?, ended_at = ?, consumed_seconds = ?, updated_at = ?,
                error = CASE WHEN ? IN ('failed', 'cancelled') THEN ? ELSE error END
            WHERE session_id = ?
            """,
            (status, now, consumed, now, reason, reason[:200], session_id),
        )
    logger.info("ended timed call %s status=%s consumed=%.1fs", session_id, status, consumed)
    return {
        "ok": True,
        "status": status,
        "consumed_seconds": round(consumed, 2),
        "message": f"Call {status}; charged {consumed:.1f}s to daily budget.",
        "session": get_session(session_id),
        "budget": calling_budget.budget_status(
            agent_type=session["agent_type"], user_key=session["user_key"]
        ),
    }


def tick_active_sessions() -> dict[str, Any]:
    """Worker tick: auto-start scheduled? No — only auto-end over-budget active calls.

    Operators / agent process explicitly start; this loop enforces the time cap.
    """
    calling_budget._ensure_tables()
    closed = []
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM veridiq_calling_timed_sessions WHERE status = 'active'"
        ).fetchall()
    now = _utc_now()
    for row in rows:
        session = _row_to_session(row)
        started = session.get("started_at")
        if not started:
            continue
        try:
            start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        elapsed = (now - start_dt).total_seconds()
        allowed = float(session.get("allowed_seconds") or 0)
        if allowed > 0 and elapsed >= allowed:
            result = end_session(session["session_id"], reason="budget_timeout")
            closed.append(result.get("session"))
    return {"ok": True, "closed_count": len(closed), "closed": closed}
