"""Timed calling budgets — per-call max duration + daily total budget.

Defaults (overridable via env):
  VERIDIQ_CALLING_MAX_SECONDS=120          # hard cap per individual call
  VERIDIQ_CALLING_DAILY_BUDGET_SECONDS=120 # total voice seconds per agent/user per UTC day
  VERIDIQ_CALLING_BUDGET_RESET=1           # local/dev: zero today's usage on process boot / reset API

Clarify: both limits apply. A call cannot exceed MAX; sum of completed+active
seconds for the day cannot exceed DAILY_BUDGET.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from database import db_session, initialize_database

logger = logging.getLogger("veridiq.calling.budget")

_boot_reset_done = False


def max_call_seconds() -> int:
    return max(1, int(os.getenv("VERIDIQ_CALLING_MAX_SECONDS", "120") or "120"))


def daily_budget_seconds() -> int:
    # Slightly higher default for local testing; production can set env explicitly.
    default = "300" if (os.getenv("VERIDIQ_ENV") or "").lower() in {"dev", "local", "development"} else "120"
    return max(1, int(os.getenv("VERIDIQ_CALLING_DAILY_BUDGET_SECONDS", default) or default))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_day(dt: Optional[datetime] = None) -> str:
    return (dt or _utc_now()).date().isoformat()


def _ensure_tables() -> None:
    initialize_database()
    with db_session() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS veridiq_calling_timed_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                agent_type TEXT NOT NULL DEFAULT 'ai_calling',
                user_key TEXT NOT NULL DEFAULT 'default',
                purpose TEXT,
                script TEXT,
                to_number TEXT,
                status TEXT NOT NULL DEFAULT 'scheduled',
                requested_seconds INTEGER NOT NULL,
                allowed_seconds INTEGER NOT NULL,
                started_at TEXT,
                ended_at TEXT,
                consumed_seconds REAL NOT NULL DEFAULT 0,
                chain_intent_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS veridiq_calling_daily_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usage_day TEXT NOT NULL,
                agent_type TEXT NOT NULL,
                user_key TEXT NOT NULL,
                consumed_seconds REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(usage_day, agent_type, user_key)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_timed_sessions_status "
            "ON veridiq_calling_timed_sessions(status, agent_type)"
        )
    maybe_boot_reset()


def budget_reset_enabled() -> bool:
    raw = (os.getenv("VERIDIQ_CALLING_BUDGET_RESET") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def reset_daily_budget(
    *,
    agent_type: str = "ai_calling",
    user_key: Optional[str] = None,
    day: Optional[str] = None,
) -> dict[str, Any]:
    """Zero UTC-day usage (and cancel active timed sessions that never connected)."""
    _ensure_tables()
    usage_day = day or _utc_day()
    now = _utc_now().replace(microsecond=0).isoformat()
    with db_session() as conn:
        if user_key:
            conn.execute(
                """
                INSERT INTO veridiq_calling_daily_usage
                    (usage_day, agent_type, user_key, consumed_seconds, updated_at)
                VALUES (?, ?, ?, 0, ?)
                ON CONFLICT(usage_day, agent_type, user_key) DO UPDATE SET
                    consumed_seconds = 0, updated_at = excluded.updated_at
                """,
                (usage_day, agent_type, user_key, now),
            )
            conn.execute(
                """
                UPDATE veridiq_calling_timed_sessions
                SET status = 'cancelled', ended_at = ?, consumed_seconds = 0,
                    updated_at = ?, error = 'budget_reset'
                WHERE agent_type = ? AND user_key = ? AND status IN ('active', 'scheduled', 'queued')
                """,
                (now, now, agent_type, user_key),
            )
        else:
            conn.execute(
                """
                UPDATE veridiq_calling_daily_usage
                SET consumed_seconds = 0, updated_at = ?
                WHERE usage_day = ? AND agent_type = ?
                """,
                (now, usage_day, agent_type),
            )
            conn.execute(
                """
                UPDATE veridiq_calling_timed_sessions
                SET status = 'cancelled', ended_at = ?, consumed_seconds = 0,
                    updated_at = ?, error = 'budget_reset'
                WHERE agent_type = ? AND status IN ('active', 'scheduled', 'queued')
                """,
                (now, now, agent_type),
            )
    info = remaining_budget_seconds(agent_type=agent_type, user_key=user_key or "default")
    logger.info(
        "calling budget reset day=%s agent=%s user=%s remaining=%.0f",
        usage_day,
        agent_type,
        user_key or "*",
        info["remaining_seconds"],
    )
    return {
        "ok": True,
        "status": "reset",
        "message": (
            f"Daily calling budget reset for UTC day {usage_day}. "
            f"{info['remaining_seconds']:.0f}s available "
            f"(resets again at next UTC midnight)."
        ),
        **info,
    }


def maybe_boot_reset() -> None:
    """If VERIDIQ_CALLING_BUDGET_RESET=1, clear today's usage once per process."""
    global _boot_reset_done
    if _boot_reset_done or not budget_reset_enabled():
        return
    _boot_reset_done = True
    try:
        reset_daily_budget(agent_type="ai_calling", user_key=None)
        logger.warning(
            "VERIDIQ_CALLING_BUDGET_RESET=1 — cleared today's ai_calling usage (local/dev)."
        )
    except Exception:  # noqa: BLE001
        logger.exception("budget boot reset failed")


def get_daily_consumed(
    *,
    agent_type: str = "ai_calling",
    user_key: str = "default",
    day: Optional[str] = None,
) -> float:
    _ensure_tables()
    usage_day = day or _utc_day()
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT consumed_seconds FROM veridiq_calling_daily_usage
            WHERE usage_day = ? AND agent_type = ? AND user_key = ?
            """,
            (usage_day, agent_type, user_key),
        ).fetchone()
    return float(row["consumed_seconds"]) if row else 0.0


def remaining_budget_seconds(
    *,
    agent_type: str = "ai_calling",
    user_key: str = "default",
) -> dict[str, Any]:
    consumed = get_daily_consumed(agent_type=agent_type, user_key=user_key)
    daily = float(daily_budget_seconds())
    remaining = max(0.0, daily - consumed)
    per_call = float(max_call_seconds())
    return {
        "usage_day": _utc_day(),
        "agent_type": agent_type,
        "user_key": user_key,
        "daily_budget_seconds": daily,
        "per_call_max_seconds": per_call,
        "consumed_seconds": round(consumed, 2),
        "remaining_seconds": round(remaining, 2),
        "can_start_call": remaining >= 1.0,
        "max_allowed_for_next_call": round(min(per_call, remaining), 2),
        "resets_at": f"{_utc_day()}T24:00:00+00:00",
        "resets_note": "Daily budget resets at UTC midnight.",
    }


def clamp_requested_seconds(
    requested: Optional[int],
    *,
    agent_type: str = "ai_calling",
    user_key: str = "default",
) -> dict[str, Any]:
    """Return allowed seconds for a new call given daily + per-call caps."""
    budget = remaining_budget_seconds(agent_type=agent_type, user_key=user_key)
    per_call = int(budget["per_call_max_seconds"])
    remaining = int(budget["remaining_seconds"])
    want = int(requested) if requested is not None else per_call
    want = max(1, want)
    allowed = max(0, min(want, per_call, remaining))
    return {
        **budget,
        "requested_seconds": want,
        "allowed_seconds": allowed,
        "ok": allowed >= 1,
        "message": (
            f"Allowed {allowed}s (per-call max {per_call}s, daily remaining {remaining}s)."
            if allowed >= 1
            else (
                f"Daily calling budget exhausted ({budget['consumed_seconds']:.0f}/"
                f"{budget['daily_budget_seconds']:.0f}s used UTC day {budget['usage_day']}). "
                "Resets at UTC midnight. For local dev set VERIDIQ_CALLING_BUDGET_RESET=1 "
                "or POST /api/v1/veridiq/calling/budget/reset."
            )
        ),
    }


def record_consumption(
    *,
    seconds: float,
    agent_type: str = "ai_calling",
    user_key: str = "default",
    day: Optional[str] = None,
) -> float:
    """Add consumed seconds to the daily ledger. Returns new total for the day."""
    _ensure_tables()
    usage_day = day or _utc_day()
    add = max(0.0, float(seconds))
    now = _utc_now().replace(microsecond=0).isoformat()
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO veridiq_calling_daily_usage
                (usage_day, agent_type, user_key, consumed_seconds, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(usage_day, agent_type, user_key) DO UPDATE SET
                consumed_seconds = consumed_seconds + excluded.consumed_seconds,
                updated_at = excluded.updated_at
            """,
            (usage_day, agent_type, user_key, add, now),
        )
        row = conn.execute(
            """
            SELECT consumed_seconds FROM veridiq_calling_daily_usage
            WHERE usage_day = ? AND agent_type = ? AND user_key = ?
            """,
            (usage_day, agent_type, user_key),
        ).fetchone()
    total = float(row["consumed_seconds"]) if row else add
    logger.info(
        "calling budget +%.1fs → %.1f/%ss day=%s agent=%s user=%s",
        add,
        total,
        daily_budget_seconds(),
        usage_day,
        agent_type,
        user_key,
    )
    return total


def budget_status(
    *,
    agent_type: str = "ai_calling",
    user_key: str = "default",
) -> dict[str, Any]:
    info = remaining_budget_seconds(agent_type=agent_type, user_key=user_key)
    return {
        "ok": True,
        "status": "ok" if info["can_start_call"] else "budget_exhausted",
        **info,
        "policy": {
            "per_call_max_seconds": info["per_call_max_seconds"],
            "daily_budget_seconds": info["daily_budget_seconds"],
            "note": (
                "Each timed call is capped at VERIDIQ_CALLING_MAX_SECONDS; "
                "all timed calls for an agent/user share VERIDIQ_CALLING_DAILY_BUDGET_SECONDS "
                "per UTC calendar day. Budget is charged only after the agent has connected."
            ),
        },
    }
